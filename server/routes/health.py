"""Health check route: /api/health"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends

from server.services.chat_service import ChatService, get_chat_service

router = APIRouter(tags=["health"])
ROOT = Path(__file__).resolve().parent.parent.parent

# LLM ping 限超时：网关不可达时默认重试会挂很久，健康检查不能拖死事件循环
_LLM_PING_TIMEOUT = 30.0

# 健康检查可能被高频调用，PersistentClient 构造很重，进程内复用（探测只读，
# 客户端不可用时保留 None 下次重试）
_chroma_client = None


@router.get("/api/health")
async def health(chat: ChatService = Depends(get_chat_service)):
    ctx = await chat.get_agent()
    checks = {"agent": ctx.agent is not None}

    # 同步阻塞调用必须丢进线程池，否则一次慢探测会卡住整个后端
    try:
        from model.config import init_chat

        def _ping():
            llm = init_chat()
            llm.invoke([{"role": "user", "content": "ping"}])

        await asyncio.wait_for(asyncio.to_thread(_ping), timeout=_LLM_PING_TIMEOUT)
        checks["llm"] = True
    except Exception:
        checks["llm"] = False

    try:
        import chromadb

        def _chroma_ok():
            global _chroma_client
            if _chroma_client is None:
                _chroma_client = chromadb.PersistentClient(path=str(ROOT / "chroma_db"))
            _chroma_client.list_collections()

        await asyncio.to_thread(_chroma_ok)
        checks["chromadb"] = True
    except Exception:
        checks["chromadb"] = False

    all_ok = all(checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
