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

from server.lifespan import lifespan
from server.routes.topics import router as topics_router
from server.routes.chat import router as chat_router
from server.routes.search import router as search_router
from server.routes.personal_data import router as personal_data_router
from server.routes.settings import router as settings_router
from server.routes.sync import router as sync_router
from server.routes.news import router as news_router
from server.routes.health import router as health_router
from server.routes.schedule import router as schedule_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("server")


def create_app() -> FastAPI:
    app = FastAPI(
        title="USTC AI Assistant",
        version="0.1.0",
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(topics_router)
    app.include_router(chat_router)
    app.include_router(search_router)
    app.include_router(personal_data_router)
    app.include_router(settings_router)
    app.include_router(sync_router)
    app.include_router(health_router)
    app.include_router(news_router)
    app.include_router(schedule_router)

    # Serve frontend static files (production build must exist)
    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
