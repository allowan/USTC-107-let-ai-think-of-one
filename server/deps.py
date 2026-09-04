"""
Dependency injection for the local single-user client.
No JWT, no passwords — the app runs on the user's own machine.
"""

LOCAL_USER = "local_user"


async def get_user() -> str:
    """All requests are from the local user."""
    return LOCAL_USER
