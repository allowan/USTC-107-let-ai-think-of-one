"""
Sync Server — 公共通知数据库同步服务端。
纯文档存储 + 版本管理，不依赖 LLM / ChromaDB / Ollama。

启动: python main.py  (默认端口 8001)
"""

import sys
from pathlib import Path

# Allow running as python main.py from within sync_server/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from sync_server.routes.admin import router as admin_router
from sync_server.routes.sync import router as sync_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_server")

app = FastAPI(
    title="USTC Campus Sync Server",
    version="0.1.0",
    docs_url="/api/docs",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(sync_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/admin")
async def admin_page():
    """管理后台页面"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.is_file():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(admin_html.read_text(encoding="utf-8"))
    return RedirectResponse(url="/api/docs")


@app.get("/api/health")
async def health():
    from sync_server.database import current_version, get_documents
    return {
        "status": "ok",
        "version": current_version(),
        "document_count": len(get_documents()),
    }


if __name__ == "__main__":
    import signal
    import uvicorn

    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 直接传入 app 对象而非 "main:app" 字符串，避免 sys.path.insert(0, ..)
    # 导致 Python 解析到项目根目录的 main.py（不含 app 变量）
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        reload=False,
        timeout_graceful_shutdown=5,
    )
