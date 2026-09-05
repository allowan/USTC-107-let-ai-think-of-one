# query_engine.py
import logging
import math
import time
import os
import threading
from collections import OrderedDict

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
    融合排名，不影响检索功能。
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

    def compute_score(self, pairs: List[List[str]], normalize: bool = True) -> list[float]:
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
        seen = set()
        for r in resp.json()["results"]:
            index = r["index"]
            if type(index) is not int or index < 0 or index >= len(documents) or index in seen:
                raise ValueError("重排序结果索引无效")
            seen.add(index)
            scores[index] = float(r.get("relevance_score", r.get("score")))
        if len(seen) != len(documents):
            raise ValueError("重排序结果不完整")
        return scores


_reranker = None
_reranker_retry_at = 0.0
_reranker_lock = threading.Lock()

_retriever_cache: OrderedDict[tuple, VectorIndexRetriever] = OrderedDict()
_retriever_lock = threading.Lock()
_MAX_RETRIEVERS = 64
_bm25_cache: OrderedDict = OrderedDict()
_bm25_lock = threading.Lock()


def reset_caches() -> None:
    """清空检索器/BM25 缓存。

    底层向量集合被删除重建（全量同步、--reindex）后，缓存的 retriever
    仍指向旧集合对象，查询会报错或返回旧数据，必须随 query.reset_caches
    一并失效。
    """
    global _retriever_cache
    with _retriever_lock:
        _retriever_cache.clear()
    invalidate_keyword_cache()


def _get_reranker() -> _APIReranker | None:
    global _reranker, _reranker_retry_at
    with _reranker_lock:
        if time.monotonic() < _reranker_retry_at or os.getenv("RERANK_PROVIDER") != "api":
            return None
        if _reranker is None:
            try:
                _reranker = _APIReranker(
                    model=os.getenv("RERANK_MODEL", "qwen3-reranker"),
                    api_key=os.getenv("RERANK_API_KEY", ""),
                    base_url=os.getenv("RERANK_BASE_URL", ""),
                )
            except Exception:
                logger.exception("重排序初始化失败，60 秒后重试")
                _reranker_retry_at = time.monotonic() + 60
        return _reranker


def invalidate_keyword_cache() -> None:
    """写入前后失效，避免等量替换或失败写入留下旧关键词快照。"""
    with _bm25_lock:
        _bm25_cache.clear()


def _get_bm25_cached(index: VectorStoreIndex):
    from .keyword_retriever import BM25Retriever
    with _bm25_lock:
        key = id(index)
        if key not in _bm25_cache:
            bm25 = BM25Retriever(nodes=index.vector_store.get_nodes(node_ids=None))
            # 持有索引引用，防止对象释放后 id 重用命中错误语料。
            _bm25_cache[key] = (index, bm25)
        _bm25_cache.move_to_end(key)
        if len(_bm25_cache) > _MAX_RETRIEVERS:
            _bm25_cache.popitem(last=False)
        return _bm25_cache[key][1]


def _get_cached_retriever(index: VectorStoreIndex, top_k: int) -> VectorIndexRetriever:
    """按索引对象缓存检索器，限制高级调用方不断创建索引时的驻留数量。"""
    key = (id(index), top_k)
    with _retriever_lock:
        if key not in _retriever_cache:
            _retriever_cache[key] = VectorIndexRetriever(index=index, similarity_top_k=top_k)
        _retriever_cache.move_to_end(key)
        if len(_retriever_cache) > _MAX_RETRIEVERS:
            _retriever_cache.popitem(last=False)
        return _retriever_cache[key]


def rerank_nodes(query: str, nodes: List[NodeWithScore], top_n: int = 10) -> List[NodeWithScore]:
    """验证完整分数后返回新包装节点，失败时保留输入排名。"""
    if not nodes or top_n <= 0:
        return []
    reranker = _get_reranker()
    if reranker is None:
        return sorted(nodes, key=lambda n: n.score or 0, reverse=True)[:top_n]
    global _reranker_retry_at
    try:
        scores = reranker.compute_score([[query, node.node.text] for node in nodes], normalize=True)
        if hasattr(scores, "ndim") and scores.ndim > 1:
            scores = scores.flatten()
        scores = [float(score) for score in scores]
        if len(scores) != len(nodes) or not all(math.isfinite(score) for score in scores):
            raise ValueError("重排序分数数量或数值无效")
        nodes = [NodeWithScore(node=node.node, score=score) for node, score in zip(nodes, scores)]
    except Exception:
        logger.exception("重排序失败，保留融合结果，60 秒后重试")
        with _reranker_lock:
            _reranker_retry_at = time.monotonic() + 60
    return sorted(nodes, key=lambda n: n.score or 0, reverse=True)[:top_n]


def retrieve_nodes(
    query: str, public_index: Optional[VectorStoreIndex] = None,
    user_index: Optional[VectorStoreIndex] = None, top_k: int = 10,
    rerank: bool = True,
) -> List[NodeWithScore]:
    """从各自集合召回向量和关键词候选，按 RRF 融合，不调用生成模型。"""
    if not query.strip() or top_k <= 0:
        return []
    all_nodes = []
    for index in (public_index, user_index):
        if index is None:
            continue
        vector_nodes = _get_cached_retriever(index, top_k).retrieve(query)
        if not vector_nodes:
            from .keyword_retriever import extract_keywords
            retry = extract_keywords(query)
            if retry and retry != query.strip():
                vector_nodes = _get_cached_retriever(index, top_k).retrieve(retry)
        try:
            keyword_nodes = _get_bm25_cached(index).retrieve(query, top_k=top_k)
        except Exception:
            logger.exception("关键词召回失败，回退向量候选")
            keyword_nodes = []
        fused = {}
        for ranking in (vector_nodes, keyword_nodes):
            seen = set()
            for rank, node in enumerate(ranking, 1):
                key = node.node.node_id
                if key in seen:
                    continue
                seen.add(key)
                if key not in fused:
                    fused[key] = NodeWithScore(node=node.node, score=0.0)
                fused[key].score += 1.0 / (60 + rank)
        all_nodes.extend(fused.values())
    if rerank and len(all_nodes) > 1:
        return rerank_nodes(query, all_nodes, top_n=top_k)
    return sorted(all_nodes, key=lambda n: n.score or 0, reverse=True)[:top_k]


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
    """共用纯检索管线并生成回答；data_dir 仅保留参数兼容，语料来自集合。"""
    final_nodes = retrieve_nodes(query, public_index, user_index, top_k, rerank)
    if not final_nodes:
        return "未找到相关信息。"

    context = "\n\n".join([_node_context_block(node) for node in final_nodes])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    # 统一走 require_llm 守卫：不可用时抛出可操作的错误，禁止静默降级到 MockLLM
    llm = config.require_llm()
    from llama_index.core.llms import ChatMessage
    response = llm.chat([ChatMessage(role="user", content=prompt)])
    return str(response.message.content or "")
