"""
Auth service: user authentication, topic CRUD, tool preferences.
Delegates to campus_rag.auth.
"""

import logging

logger = logging.getLogger("server")


class AuthService:
    """Thin wrapper around campus_rag.auth for user/topic/tool-pref management."""

    # ── User auth ──────────────────────────────────────────────────

    @staticmethod
    def authenticate(username: str, password: str) -> tuple:
        from campus_rag import authenticate as _auth
        return _auth(username, password)

    @staticmethod
    def register(username: str, password: str) -> bool:
        from campus_rag import register_user
        return register_user(username, password)

    @staticmethod
    def change_password(username: str, old_password: str, new_password: str) -> tuple:
        from campus_rag import change_password
        return change_password(username, old_password, new_password)

    @staticmethod
    def is_admin(username: str) -> bool:
        from campus_rag.auth import get_user_admin_status
        return get_user_admin_status(username)

    # ── Topics ─────────────────────────────────────────────────────

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

    @staticmethod
    def thread_id(username: str, topic_id: str) -> str:
        from campus_rag.auth import _thread_id
        return _thread_id(username, topic_id)

    # ── Tool preferences ───────────────────────────────────────────

    @staticmethod
    def get_tool_prefs(username: str) -> dict:
        from campus_rag.auth import get_user_tool_prefs
        return get_user_tool_prefs(username)

    @staticmethod
    def set_tool_prefs(username: str, prefs: dict[str, bool]):
        from campus_rag.auth import set_user_tool_prefs
        set_user_tool_prefs(username, prefs)

    @staticmethod
    def get_enabled_tool_names(username: str) -> list[str] | None:
        from campus_rag.auth import get_enabled_tool_names
        return get_enabled_tool_names(username)


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
