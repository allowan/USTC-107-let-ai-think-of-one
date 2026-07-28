import logging
from pathlib import Path
from llama_index.core import Document

_base = Path(__file__).resolve().parent

from .index_manager import RAGSystem

logger = logging.getLogger("campus_rag.query")

_rag = None
_public_retriever = None
_user_retrievers: dict[str, object] = {}


def _reset():
    """重置所有缓存状态，下次调用时自动重建。"""
    global _rag, _public_retriever, _user_retrievers
    _rag = None
    _public_retriever = None
    _user_retrievers = {}


def _init():
    global _rag, _public_retriever
    if _rag is None:
        _rag = RAGSystem()
        index = _rag.get_or_create_public_index(str(_base / "data"))
        _public_retriever = index.as_retriever(similarity_top_k=10)
    return True


def _ensure_init():
    """确保 RAG 已初始化。ChromaDB 恢复由 get_public_index 内部处理。"""
    global _rag, _public_retriever
    if _rag is None:
        return _init()
    return True


def _get_user_retriever(user_id: str):
    if user_id not in _user_retrievers:
        index = _rag.get_or_create_user_index(user_id)
        _user_retrievers[user_id] = index.as_retriever(similarity_top_k=10)
    return _user_retrievers[user_id]


def _format_nodes(nodes, empty_message: str) -> str:
    if not nodes:
        return empty_message
    contexts = []
    for node in nodes:
        contexts.append(node.get_content())
    return "\n\n".join(contexts)


def search_notices(query: str) -> str:
    """只在官方通知（公共数据）中搜索。"""
    _ensure_init()
    return _format_nodes(_public_retriever.retrieve(query),
                         "未在通知中找到相关信息。")


def search_user_data(query: str, user_id: str) -> str:
    """只在用户个人数据中搜索。"""
    _ensure_init()
    retriever = _get_user_retriever(user_id)
    return _format_nodes(retriever.retrieve(query),
                         "未在个人数据中找到相关信息。")


def search_notices_answer(query: str) -> str:
    """搜索官方通知，经 LLM 总结后返回回答。"""
    _ensure_init()
    pub_idx = _rag.get_public_index()
    from .query_engine import get_rag_response
    return get_rag_response(query, public_index=pub_idx, data_dir=str(_base / "data"))


def search_user_data_answer(query: str, user_id: str) -> str:
    """搜索用户个人数据，经 LLM 总结后返回回答。"""
    _ensure_init()
    user_idx = _rag.get_or_create_user_index(user_id)
    from .query_engine import get_rag_response
    return get_rag_response(query, user_index=user_idx)



def add_user_data(user_id: str, documents: list):
    """向用户个人索引添加文档（llama_index Document 列表）。"""
    _ensure_init()
    _rag.add_user_documents(user_id, documents)
    _user_retrievers.pop(user_id, None)


def add_user_files(user_id: str, path: str):
    """向用户个人索引导入 txt 文件。path 可以是单个 .txt 文件或目录（扫描目录下所有 .txt）。"""
    from .data_loader import load_documents_from_files
    import os

    docs = []
    if os.path.isfile(path):
        if not path.endswith(".txt"):
            raise ValueError("目前只支持 .txt 文件")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if content:
            docs = [Document(text=content, metadata={"source": os.path.basename(path)})]
    elif os.path.isdir(path):
        docs = load_documents_from_files(path)
    else:
        raise FileNotFoundError(f"路径不存在: {path}")

    if docs:
        add_user_data(user_id, docs)
    return len(docs)


def list_user_data(user_id: str) -> dict:
    """列出用户个人知识库中的所有文档。"""
    _ensure_init()
    return _rag.list_user_documents(user_id)


def delete_user_data(user_id: str, source: str) -> int:
    """删除用户个人知识库中指定来源的所有文档块。"""
    _ensure_init()
    count = _rag.delete_user_documents_by_source(user_id, source)
    _user_retrievers.pop(user_id, None)
    return count
