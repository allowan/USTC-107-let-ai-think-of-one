"""
Auth service: topic CRUD. Delegates to campus_rag.auth.
"""

import logging

logger = logging.getLogger("server")


class AuthService:
    """Thin wrapper around campus_rag.auth for topic management."""

    @staticmethod
    def list_topics(username: str) -> list:
        from campus_rag import list_topics
        return list_topics(username)

    @staticmethod
    def create_topic(username: str, name: str) -> dict:
        from campus_rag import create_topic
        return create_topic(username, name)

    @staticmethod
    def get_topic(username: str, topic_id: str) -> dict | None:
        from campus_rag import get_topic
        return get_topic(username, topic_id)

    @staticmethod
    def delete_topic(username: str, topic_id: str) -> bool:
        from campus_rag import delete_topic
        return delete_topic(username, topic_id)

    @staticmethod
    def rename_topic(username: str, topic_id: str, new_name: str) -> bool:
        from campus_rag import rename_topic
        return rename_topic(username, topic_id, new_name)


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
