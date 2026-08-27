"""
RAG service: search, personal data CRUD.
Delegates to campus_rag.query and campus_rag.index_manager.
"""

import logging
from llama_index.core import Document

logger = logging.getLogger("server")


class RAGService:
    """Encapsulates RAG operations: search and personal data management."""

    @staticmethod
    def search_notices(query: str) -> str:
        from campus_rag import search_notices as _search
        return _search(query)

    @staticmethod
    def search_user_data(query: str, username: str) -> str:
        from campus_rag import search_user_data
        return search_user_data(query, username)

    @staticmethod
    def list_user_data(username: str) -> dict:
        from campus_rag import list_user_data
        return list_user_data(username)

    @staticmethod
    def add_user_data(username: str, content: str, source: str = "手动输入"):
        from campus_rag import add_user_data
        doc = Document(text=content, metadata={"source": source})
        add_user_data(username, [doc])

    @staticmethod
    def update_user_data(username: str, source: str, content: str):
        # 委托给 campus_rag.query.update_user_data：先探测嵌入可用性再删除写入，
        # 避免先删后写时嵌入不可用导致用户数据丢失（不可在 service 层拼装）。
        from campus_rag import update_user_data
        update_user_data(username, source, content)

    @staticmethod
    def delete_user_data(username: str, source: str) -> int:
        from campus_rag import delete_user_data
        return delete_user_data(username, source)


_rag_service: RAGService | None = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
