# ingest.py
from llama_index.core import Document
from .index_manager import RAGSystem

_rag = None


def _get_rag() -> RAGSystem:
    global _rag
    if _rag is None:
        _rag = RAGSystem()
    return _rag


def add_public_activity(text: str, admin_check: bool = False, source: str = ""):
    """添加公共通知文档（仅管理员可调用）。"""
    if not admin_check:
        raise PermissionError("需要管理员权限")
    doc = Document(text=text, metadata={"source": source or "manual_public"})
    _get_rag().add_documents_to_public([doc])


def add_user_activity(user_id: str, text: str):
    """添加用户个人文档。"""
    doc = Document(text=text, metadata={"source": "manual_user", "owner": user_id})
    _get_rag().add_user_documents(user_id, [doc])


# add_user_files 已移至 query.py，那里会正确清除检索器缓存
# 如需此功能请使用 from campus_rag import add_user_files
