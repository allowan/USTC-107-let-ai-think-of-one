# query_engine.py
import os

# Force offline mode for HuggingFace (model already cached locally).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from typing import List, Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.core.prompts import PromptTemplate

from . import config


class _CrossEncoderReranker:
    """bge-reranker-base 的本地轻量封装。

    不直接用 FlagEmbedding.FlagReranker 的原因：FlagEmbedding 1.4.0 内部调用
    tokenizer.prepare_for_model()，该方法在 transformers 5.x 中已被移除，会抛
    AttributeError。这里改用 AutoTokenizer + AutoModelForSequenceClassification
    走标准的 __call__ tokenize 路径（该路径在 transformers 5.x 下正常），并保留
    compute_score(pairs, normalize) 接口，使调用处无需改动。若日后 FlagEmbedding
    修复了该兼容问题，可直接切回 FlagReranker。

    运行前提：bge-reranker-base 模型需提前下载到本地 HF 缓存（约 1GB），并将
    HF_HOME 环境变量指向缓存目录（本项目示例为 E:\\HFCache）。模型缺失时
    _get_reranker 会捕获异常并优雅降级为按原始分数排序，不影响检索功能。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()

    def compute_score(self, pairs: List[List[str]], normalize: bool = True):
        queries = [p[0] for p in pairs]
        passages = [p[1] for p in pairs]
        with self._torch.no_grad():
            enc = self._tokenizer(
                queries,
                passages,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            logits = self._model(**enc).logits.view(-1).float()
            return self._torch.sigmoid(logits) if normalize else logits


_reranker = None
_reranker_available = True

_retriever_cache: dict[tuple, VectorIndexRetriever] = {}
_bm25_cache: dict[str, object] = {}


def _get_reranker():
    global _reranker, _reranker_available
    if _reranker is not None and _reranker_available:
        return _reranker
    if not _reranker_available:
        return None
    try:
        _reranker = _CrossEncoderReranker("BAAI/bge-reranker-base")
    except Exception:
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
    except Exception:
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
    "请在回答末尾列出各条信息的来源文件名或出处。\n\n"
    "参考资料：\n{context_str}\n\n"
    "用户问题：{query_str}\n\n你的回答："
)


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
        except Exception:
            pass

    if rerank and len(unique_nodes) > 1:
        final_nodes = rerank_nodes(query, unique_nodes, top_n=10)
    else:
        final_nodes = sorted(unique_nodes, key=lambda n: n.score or 0, reverse=True)[:10]

    context = "\n\n".join([
        f"[来源: {node.node.metadata.get('source', '未知来源')}]\n{node.node.text}"
        for node in final_nodes
    ])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    if not config.init_llm():
        raise RuntimeError("LLM 未配置或初始化失败")
    llm = config.Settings.llm
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

    context = "\n\n".join([
        f"[来源: {node.node.metadata.get('source', '未知来源')}]\n{node.node.text}"
        for node in final_nodes
    ])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    if not config.init_llm():
        raise RuntimeError("LLM 未配置或初始化失败")
    llm = config.Settings.llm
    from llama_index.core.llms import ChatMessage
    response = llm.chat([ChatMessage(role="user", content=prompt)])
    return str(response.message.content or "")
