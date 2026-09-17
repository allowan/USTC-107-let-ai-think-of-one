"""
USTC AI Assistant - FastAPI application factory.
"""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from server.lifespan import lifespan
from server.deps import LocalAccessMiddleware
from server.routes.topics import router as topics_router
from server.routes.chat import router as chat_router
from server.routes.search import router as search_router
from server.routes.personal_data import router as personal_data_router
from server.routes.settings import router as settings_router
from server.routes.sync import router as sync_router
from server.routes.news import router as news_router
from server.routes.health import router as health_router
from server.routes.schedule import router as schedule_router
from server.routes.digest import router as digest_router
from server.routes.backup import router as backup_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("server")


class FrontendStaticFiles(StaticFiles):
    """仅为已知前端页面提供入口，保留静态资源的安全检查。"""

    page_paths = frozenset({
        "/today", "/chat", "/personal-data", "/schedule", "/news", "/sync", "/backup",
    })

    async def get_response(self, path: str, scope: Scope) -> Response:
        """页面刷新复用入口文件；未知路径仍由 StaticFiles 处理。"""
        # 使用尚未归一化的请求路径，避免含 .. 的路径误匹配前端页面。
        request_path = scope["path"]
        if (scope["method"] in {"GET", "HEAD"}
                and (request_path in self.page_paths
                     or request_path.removesuffix("/") in self.page_paths)):
            path = "index.html"
        return await super().get_response(path, scope)


def create_app() -> FastAPI:
    app = FastAPI(
        title="USTC AI Assistant",
        version="0.1.0",
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LocalAccessMiddleware)
    app.include_router(topics_router)
    app.include_router(chat_router)
    app.include_router(search_router)
    app.include_router(personal_data_router)
    app.include_router(settings_router)
    app.include_router(sync_router)
    app.include_router(health_router)
    app.include_router(news_router)
    app.include_router(schedule_router)
    app.include_router(digest_router)
    app.include_router(backup_router)

    # Serve frontend static files (production build must exist)
    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", FrontendStaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
