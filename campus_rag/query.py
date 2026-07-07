from pathlib import Path
from llama_index.core import Document

_base = Path(__file__).resolve().parent

from .index_manager import RAGSystem

_rag = None
_public_retriever = None
_user_retrievers: dict[str, object] = {}


def _init():
    global _rag, _public_retriever
    if _rag is None:
        _rag = RAGSystem()
        index = _rag.get_or_create_public_index(str(_base / "data"))
        _public_retriever = index.as_retriever(similarity_top_k=10)


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
    _init()
    return _format_nodes(_public_retriever.retrieve(query),
                         "未在通知中找到相关信息。")


def search_user_data(query: str, user_id: str) -> str:
    """只在用户个人数据中搜索。"""
    _init()
    retriever = _get_user_retriever(user_id)
    return _format_nodes(retriever.retrieve(query),
                         "未在个人数据中找到相关信息。")


def search_all(query: str, user_id: str) -> str:
    """同时搜索官方通知和用户个人数据。"""
    _init()
    pub_nodes = _public_retriever.retrieve(query)
    user_retriever = _get_user_retriever(user_id)
    user_nodes = user_retriever.retrieve(query)

    parts = []
    if pub_nodes:
        parts.append("=== 官方通知 ===\n" + _format_nodes(pub_nodes, ""))
    if user_nodes:
        parts.append("=== 个人数据 ===\n" + _format_nodes(user_nodes, ""))

    return "\n\n".join(parts) if parts else "未找到相关信息。"


def add_user_data(user_id: str, documents: list):
    """向用户个人索引添加文档（llama_index Document 列表）。"""
    _init()
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
