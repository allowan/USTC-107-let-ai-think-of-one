# query_engine.py
from typing import List, Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.core.prompts import PromptTemplate
from FlagEmbedding import FlagReranker

from .keyword_retriever import BM25Retriever
from . import config

_reranker = None
_reranker_available = True


def _get_reranker():
    global _reranker, _reranker_available
    if _reranker is None and _reranker_available:
        try:
            _reranker = FlagReranker("BAAI/bge-reranker-base", use_fp16=True)
        except Exception:
            _reranker_available = False
            _reranker = None
    return _reranker


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
    public_index: VectorStoreIndex,
    user_index: Optional[VectorStoreIndex] = None,
    top_k: int = 20,
) -> str:
    """向量检索 + 重排序 + LLM 生成回答。"""
    all_nodes = []

    pub_retriever = VectorIndexRetriever(index=public_index, similarity_top_k=top_k)
    all_nodes.extend(pub_retriever.retrieve(query))

    if user_index is not None:
        user_retriever = VectorIndexRetriever(index=user_index, similarity_top_k=top_k)
        all_nodes.extend(user_retriever.retrieve(query))

    if not all_nodes:
        return "未找到相关信息。"

    unique_nodes = _dedup_nodes(all_nodes)
    reranked = rerank_nodes(query, unique_nodes, top_n=10)

    context = "\n\n".join([node.node.text for node in reranked])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    llm = config.Settings.llm
    response = llm.complete(prompt)
    return str(response)


def get_rag_response_hybrid(
    query: str,
    public_index: VectorStoreIndex,
    data_dir: str = "./data",
    user_index: Optional[VectorStoreIndex] = None,
    top_k_vector: int = 20,
) -> str:
    """混合检索：向量 + BM25，合并去重后重排序，LLM 生成回答。"""
    all_nodes: List[NodeWithScore] = []

    # 向量检索
    if public_index is not None:
        pub_ret = VectorIndexRetriever(index=public_index, similarity_top_k=top_k_vector)
        all_nodes.extend(pub_ret.retrieve(query))

    if user_index is not None:
        user_ret = VectorIndexRetriever(index=user_index, similarity_top_k=top_k_vector)
        all_nodes.extend(user_ret.retrieve(query))

    # BM25 关键词检索
    try:
        bm25_ret = BM25Retriever(data_dir)
        bm25_nodes = bm25_ret.retrieve(query, top_k=top_k_vector)
        all_nodes.extend(bm25_nodes)
    except Exception:
        pass

    if not all_nodes:
        return "未找到相关信息。"

    unique_nodes = _dedup_nodes(all_nodes)
    reranked = rerank_nodes(query, unique_nodes, top_n=10)

    context = "\n\n".join([node.node.text for node in reranked])
    prompt = QA_PROMPT.format(context_str=context, query_str=query)
    llm = config.Settings.llm
    response = llm.complete(prompt)
    return str(response)
