# query_engine.py
import logging
import os

from typing import List, Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.core.prompts import PromptTemplate

from . import config

logger = logging.getLogger("campus_rag.query_engine")


class _APIReranker:
    """qwen3-reranker 的 API 封装（Cohere/Jina 风格 /rerank 端点）。

    保留 compute_score(pairs, normalize) 接口与本地 cross-encoder 一致，
    使 rerank_nodes 调用处无需改动；normalize 参数仅为兼容接口保留，
    API 返回的 relevance_score 本身已是归一化相关性分数。

    配置来自 campus_rag/.env 的 RERANK_* 变量。端点不可用时由
    _get_reranker / rerank_nodes 的既有异常处理降级为按原始
    向量分数排序，不影响检索功能。
    """

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        import httpx
        self._model = model
        self._url = base_url.rstrip("/") + "/rerank"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=30.0)

    def compute_score(self, pairs: List[List[str]], normalize: bool = True):
        query = pairs[0][0]
        documents = [p[1] for p in pairs]
        resp = self._client.post(
            self._url,
            headers=self._headers,
            json={
                "model": self._model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
            },
        )
        resp.raise_for_status()
        # 兼容 relevance_score / score 两种字段命名
        scores = [0.0] * len(documents)
        for r in resp.json()["results"]:
            scores[int(r["index"])] = float(r.get("relevance_score", r.get("score", 0.0)))
        return scores


_reranker = None
_reranker_available = True

_retriever_cache: dict[tuple, VectorIndexRetriever] = {}
_bm25_cache: dict[str, object] = {}


def _get_reranker():
    """按 .env 的 RERANK_* 配置构建 API reranker；未配置或失败时返回 None。"""
    global _reranker, _reranker_available
    if _reranker is not None and _reranker_available:
        return _reranker
    if not _reranker_available:
        return None
    if os.getenv("RERANK_PROVIDER") != "api":
        return None  # 未配置 API reranker，走原始分数排序
    try:
        _reranker = _APIReranker(
            model=os.getenv("RERANK_MODEL", "qwen3-reranker"),
            api_key=os.getenv("RERANK_API_KEY", ""),
            base_url=os.getenv("RERANK_BASE_URL", ""),
        )
    except Exception as e:
        logger.warning("API reranker 构建失败，降级为原始向量分数排序: %s", e)
        _reranker_available = False
        _reranker = None
    return _reranker


def _get_bm25_cached(data_dir: str):
    """返回按 data_dir 缓存的 BM25 检索器（与向量索引同粒度的分块文档）。

    该函数本身只是「带缓存 + 按 txt 文件 mtime 失效」的 BM25 检索器工厂，不绑定
    具体用途：既可用于 get_rag_response 中对向量结果的预过滤，也可用于
    get_rag_response_hybrid 中作为独立检索源并入候选集。缓存键为 data_dir。
    """
    import os
    if data_dir in _bm25_cache:
        cached_mtime, cached_bm25 = _bm25_cache[data_dir]
        current_mtime = 0.0
        if os.path.isdir(data_dir):
            for fname in os.listdir(data_dir):
                if fname.endswith(".txt"):
                    try:
                        current_mtime = max(current_mtime, os.path.getmtime(os.path.join(data_dir, fname)))
                    except OSError:
                        pass
        if current_mtime == cached_mtime:
            return cached_bm25
    from .keyword_retriever import BM25Retriever
    bm25 = BM25Retriever(data_dir)
    import os as _os
    mtime = 0.0
    if _os.path.isdir(data_dir):
        for fname in _os.listdir(data_dir):
            if fname.endswith(".txt"):
                try:
                    mtime = max(mtime, _os.path.getmtime(_os.path.join(data_dir, fname)))
                except OSError:
                    pass
    _bm25_cache[data_dir] = (mtime, bm25)
    return bm25


def _get_cached_retriever(index: VectorStoreIndex, top_k: int) -> VectorIndexRetriever:
    """Cache retrievers by index_id + top_k to avoid recreating on every call."""
    key = (index.index_id, top_k)
    if key not in _retriever_cache:
        _retriever_cache[key] = VectorIndexRetriever(index=index, similarity_top_k=top_k)
    return _retriever_cache[key]


def rerank_nodes(query: str, nodes: List[NodeWithScore], top_n: int = 10) -> List[NodeWithScore]:
    if not nodes:
        return []
    reranker = _get_reranker()
    if reranker is None:
        return sorted(nodes, key=lambda n: n.score or 0, reverse=True)[:top_n]
    global _reranker_available
    try:
        pairs = [[query, node.node.text] for node in nodes]
        scores = reranker.compute_score(pairs, normalize=True)
        if hasattr(scores, "ndim") and scores.ndim > 1:
            scores = scores.flatten()
        for i, node in enumerate(nodes):
            node.score = float(scores[i])
    except Exception as e:
        # 降级为原始分数排序是有意为之，但静默禁用会让重排序失效且无线索；
        # 留痕后仍按原策略继续，不影响检索功能。
        logger.warning("reranker 不可用，降级为原始向量分数排序: %s", e)
        _reranker_available = False
        _reranker = None
    sorted_nodes = sorted(nodes, key=lambda n: n.score, reverse=True)
    return sorted_nodes[:top_n]


def _dedup_nodes(nodes: List[NodeWithScore]) -> List[NodeWithScore]:
    seen = set()
    unique = []
    for node in nodes:
        if node.node.text not in seen:
            seen.add(node.node.text)
            unique.append(node)
    return unique


QA_PROMPT = PromptTemplate(
    "你是一个校园助手。请根据下面的参考资料回答用户问题。\n"
    "如果资料中包含多条相关信息，请用序号列出。\n"
    "如果资料不足以回答问题，请如实说明。\n"
    "请在回答末尾列出各条信息的来源（文件名）；资料带源链接时务必一并给出，方便用户溯源。\n\n"
    "参考资料：\n{context_str}\n\n"
    "用户问题：{query_str}\n\n你的回答："
)


def _node_context_block(node: NodeWithScore) -> str:
    """拼装单个节点的上下文：来源头（文件名 + 源链接）+ 正文。"""
    meta = node.node.metadata or {}
    header = f"[来源: {meta.get('source', '未知来源')}]"
    if meta.get("url"):
        header += f" [源链接: {meta['url']}]"
    return f"{header}\n{node.node.text}"


def get_rag_response(
    query: str,
    public_index: Optional[VectorStoreIndex] = None,
    user_index: Optional[VectorStoreIndex] = None,
    top_k: int = 10,
    rerank: bool = True,
    data_dir: str = None,
) -> str:
    all_nodes: List[NodeWithScore] = []

    if public_index is not None:
        retriever = _get_cached_retriever(public_index, top_k)
        all_nodes.extend(retriever.retrieve(query))

    if user_index is not None:
        retriever = _get_cached_retriever(user_index, top_k)
        all_nodes.extend(retriever.retrieve(query))

    if not all_nodes:
        return "未找到相关信息。"

    unique_nodes = _dedup_nodes(all_nodes)

    # BM25 预过滤：只保留与 BM25 top 命中重叠的节点
    if data_dir is not None and len(unique_nodes) > 10:
        try:
            bm25 = _get_bm25_cached(data_dir)
            bm25_nodes = bm25.retrieve(query, top_k=max(10, top_k))
            bm25_texts = {n.node.text for n in bm25_nodes}
            # Score boost for nodes that match both BM25 and vector search
            filtered = []
            for node in unique_nodes:
                if node.node.text in bm25_texts:
                    node.score = (node.score or 0) * 1.2  # boost BM25 matches
                    filtered.append(node)
            if len(filtered) >= 3:
                unique_nodes = filtered
        except Exception as e:
            # BM25 预过滤失败时回退纯向量结果，留痕便于排查检索质量异常
            logger.debug("BM25 预过滤失败，跳过: %s", e)

    if rerank and len(unique_nodes) > 1:
        final_nodes = rerank_nodes(query, unique_nodes, top_n=10)
    else:
        final_nodes = sorted(unique_nodes, key=lambda n: n.score or 0, reverse=True)[:10]

    context = "\n\n".join([_node_context_block(node) for node in final_nodes])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    # require_llm：未初始化时抛异常，避免静默使用 MockLLM 回声 prompt 假回答
    llm = config.require_llm()
    from llama_index.core.llms import ChatMessage
    response = llm.chat([ChatMessage(role="user", content=prompt)])
    return str(response.message.content or "")


def get_rag_response_hybrid(
    query: str,
    public_index: VectorStoreIndex,
    data_dir: str,
    top_k: int = 20,
) -> str:
    """向量检索 + BM25关键词检索 + 重排序 + LLM 生成回答。"""
    all_nodes: List[NodeWithScore] = []

    retriever = _get_cached_retriever(public_index, top_k)
    all_nodes.extend(retriever.retrieve(query))

    # 作为独立检索源，将 BM25 结果并入候选集
    bm25 = _get_bm25_cached(data_dir)
    all_nodes.extend(bm25.retrieve(query, top_k=top_k))

    if not all_nodes:
        return "未找到相关信息。"

    unique_nodes = _dedup_nodes(all_nodes)
    if len(unique_nodes) > 1:
        final_nodes = rerank_nodes(query, unique_nodes, top_n=10)
    else:
        final_nodes = sorted(unique_nodes, key=lambda n: n.score or 0, reverse=True)[:10]

    context = "\n\n".join([_node_context_block(node) for node in final_nodes])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    llm = config.require_llm()
    from llama_index.core.llms import ChatMessage
    response = llm.chat([ChatMessage(role="user", content=prompt)])
    return str(response.message.content or "")
