# ingest.py
from llama_index.core import Document
from .index_manager import RAGSystem

_rag = None


def _get_rag() -> RAGSystem:
    global _rag
    if _rag is None:
        _rag = RAGSystem()
    return _rag


def add_public_activity(text: str, admin_check: bool = False):
    """添加公共通知文档（仅管理员可调用）。"""
    if not admin_check:
        raise PermissionError("需要管理员权限")
    doc = Document(text=text, metadata={"source": "manual_public"})
    _get_rag().add_documents_to_public([doc])


def add_user_activity(user_id: str, text: str):
    """添加用户个人文档。"""
    doc = Document(text=text, metadata={"source": "manual_user", "owner": user_id})
    _get_rag().add_user_documents(user_id, [doc])


def add_user_files(user_id: str, path: str):
    """向用户个人索引导入 txt 文件。path 可以是单个 .txt 或目录。"""
    from .data_loader import load_documents_from_files
    import os

    if os.path.isfile(path):
        if not path.endswith(".txt"):
            raise ValueError("目前只支持 .txt 文件")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return 0
        docs = [Document(text=content, metadata={"source": os.path.basename(path), "owner": user_id})]
    elif os.path.isdir(path):
        docs = load_documents_from_files(path)
        for doc in docs:
            doc.metadata["owner"] = user_id
    else:
        raise FileNotFoundError(f"路径不存在: {path}")

    if docs:
        _get_rag().add_user_documents(user_id, docs)
    return len(docs)
