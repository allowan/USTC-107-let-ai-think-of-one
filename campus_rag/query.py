from pathlib import Path

_base = Path(__file__).resolve().parent

from .index_manager import RAGSystem

_rag = None
_retriever = None


def _init():
    global _rag, _retriever
    if _rag is None:
        _rag = RAGSystem()
        index = _rag.get_or_create_public_index(str(_base / "data"))
        _retriever = index.as_retriever(similarity_top_k=10)


def search_notices(query: str) -> str:
    """在校园通知中搜索相关信息，返回相关通知片段的原始文本。"""
    _init()
    nodes = _retriever.retrieve(query)
    if not nodes:
        return "未在通知中找到相关信息。"
    contexts = []
    for i, node in enumerate(nodes, 1):
        source = node.metadata.get("source", "未知来源")
        contexts.append(f"[{i}] 来源: {source}\n{node.get_content()}")
    return "\n\n---\n\n".join(contexts)
