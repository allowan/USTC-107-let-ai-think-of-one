"""
Dependency injection for the local single-user client.
No JWT, no passwords — the app runs on the user's own machine.
"""

import logging
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)
LOCAL_USER = "local_user"


def is_local_origin(value: str) -> bool:
    """精确检查本机 HTTP 来源，不把域名前缀当作可信主机。"""
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ("http", "https")
                and parsed.hostname in ("localhost", "127.0.0.1", "::1")
                and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment
                and not any(char.isspace() for char in value)
                and parsed.port != 0)
    except ValueError:
        return False


def ensure_local_origin(request: Request) -> None:
    """供独立挂载的路由复用本机来源检查。"""
    origins = request.headers.getlist("origin")
    if origins and (len(origins) != 1 or not is_local_origin(origins[0])):
        logger.warning("拒绝非本地页面请求")
        raise HTTPException(status_code=403, detail="仅允许本机页面访问")


class LocalAccessMiddleware:
    """在业务处理前校验访问边界，纯 ASGI 实现保留 SSE 流式行为。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            hosts, origins = headers.getlist("host"), headers.getlist("origin")
            if (len(hosts) != 1 or not is_local_origin(f"http://{hosts[0]}")
                    or (origins and (len(origins) != 1 or not is_local_origin(origins[0])))):
                logger.warning("拒绝非本地 HTTP 请求")
                await JSONResponse({"detail": "仅允许本机访问"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def get_user() -> str:
    """All requests are from the local user."""
    return LOCAL_USER
