"""
Dependency injection for the local single-user client.
No JWT, no passwords — the app runs on the user's own machine.
"""

from fastapi import Depends

LOCAL_USER = "local_user"


async def get_user() -> str:
    """All requests are from the local user."""
    return LOCAL_USER


async def require_admin(user: str = Depends(get_user)) -> str:
    """The local user is always admin of their own instance."""
    return user
