# query_engine.py
from typing import List, Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.core.prompts import PromptTemplate
from FlagEmbedding import FlagReranker

from . import config

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
        _reranker = FlagReranker("BAAI/bge-reranker-base", use_fp16=False)
    except Exception:
        _reranker_available = False
        _reranker = None
    return _reranker


def _get_bm25_prefilter(data_dir: str):
    """Return a cached BM25 retriever over chunked documents (same granularity as vector index)."""
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
    "如果资料不足以回答问题，请如实说明。\n\n"
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

    # BM25 pre-filter: keep only nodes whose text overlaps with BM25 top hits
    if data_dir is not None and len(unique_nodes) > 10:
        try:
            bm25 = _get_bm25_prefilter(data_dir)
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

    context = "\n\n".join([node.node.text for node in final_nodes])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    config.init_llm()
    llm = config.Settings.llm
    from llama_index.core.llms import ChatMessage
    response = llm.chat([ChatMessage(role="user", content=prompt)])
    return str(response.message.content or "")
