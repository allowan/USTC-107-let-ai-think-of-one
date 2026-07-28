"""Health check route: /api/health"""

from pathlib import Path

from fastapi import APIRouter, Depends

from server.services.chat_service import ChatService, get_chat_service

router = APIRouter(tags=["health"])
ROOT = Path(__file__).resolve().parent.parent.parent


@router.get("/api/health")
async def health(chat: ChatService = Depends(get_chat_service)):
    ctx = await chat._get_agent()
    checks = {"agent": ctx.agent is not None}

    try:
        from model.config import init_chat
        llm = init_chat()
        llm.invoke([{"role": "user", "content": "ping"}])
        checks["llm"] = True
    except Exception:
        checks["llm"] = False

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / "chroma_db"))
        client.list_collections()
        checks["chromadb"] = True
    except Exception:
        checks["chromadb"] = False

    all_ok = all(checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
