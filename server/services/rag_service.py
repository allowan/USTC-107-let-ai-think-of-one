"""
RAG service: search, personal data CRUD.
Delegates to campus_rag.query and campus_rag.index_manager.
"""

import logging
from llama_index.core import Document

logger = logging.getLogger("server")


class RAGService:
    """Encapsulates RAG operations: search and personal data management."""

    # ── Search ─────────────────────────────────────────────────────

    @staticmethod
    def search_notices(query: str) -> str:
        from campus_rag import search_notices as _search
        return _search(query)

    @staticmethod
    def search_user_data(query: str, username: str) -> str:
        from campus_rag import search_user_data
        return search_user_data(query, username)

    # ── Personal data ──────────────────────────────────────────────

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
        from campus_rag import delete_user_data, add_user_data
        delete_user_data(username, source)
        doc = Document(text=content, metadata={"source": source})
        add_user_data(username, [doc])

    @staticmethod
    def delete_user_data(username: str, source: str) -> int:
        from campus_rag import delete_user_data
        return delete_user_data(username, source)

    # ── Admin helpers ──────────────────────────────────────────────

    @staticmethod
    def get_user_collection_size(username: str) -> int:
        from campus_rag.index_manager import RAGSystem
        return RAGSystem().get_user_collection_size(username)

    @staticmethod
    def clear_user_index(username: str):
        from campus_rag.index_manager import RAGSystem
        RAGSystem().clear_user_index(username)

    @staticmethod
    def list_public_documents() -> dict:
        from campus_rag.index_manager import RAGSystem
        return RAGSystem().list_public_documents()

    @staticmethod
    def get_public_documents_by_source(source: str) -> dict:
        from campus_rag.index_manager import RAGSystem
        return RAGSystem().get_public_documents_by_source(source)

    @staticmethod
    def delete_public_documents_by_source(source: str) -> int:
        from campus_rag.index_manager import RAGSystem
        return RAGSystem().delete_public_documents_by_source(source)

    @staticmethod
    def add_public_document(content: str, source: str = ""):
        from llama_index.core import Document
        from campus_rag.index_manager import RAGSystem
        doc = Document(text=content, metadata={"source": source or "manual_public"})
        RAGSystem().add_documents_to_public([doc])

    @staticmethod
    def add_public_notice(content: str, source: str = ""):
        from campus_rag.ingest import add_public_activity
        add_public_activity(content, source=source, admin_check=True)

    @staticmethod
    def get_collection_stats() -> dict:
        from campus_rag.index_manager import RAGSystem
        return RAGSystem().get_collection_stats()


_rag_service: RAGService | None = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
