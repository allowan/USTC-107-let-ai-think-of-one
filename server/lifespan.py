"""
Server lifespan: initializes and shuts down the ChatService singleton.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from server.services.chat_service import get_chat_service

logger = logging.getLogger("server")


@asynccontextmanager
async def lifespan(app):
    logger.info("Server starting up...")
    # 事件时间索引是纯正则抽取、不依赖嵌入/LLM，故在启动时就绪：
    # 即使用户首个问题就直奔 get_upcoming_events（未触发任何 RAG 检索）、
    # 或嵌入未配置，事件工具也能返回种子语料的截止日。best-effort，
    # 失败不阻断启动（sync 内部已吞异常，此处再兜一层）。
    try:
        from campus_rag import sync_notice_events
        await asyncio.to_thread(sync_notice_events)
    except Exception:
        logger.warning("启动时同步通知事件索引失败，不影响其他功能", exc_info=True)
    chat = await get_chat_service()
    if chat.is_ready:
        logger.info("ChatService initialized")
    else:
        logger.warning(
            "ChatService is unavailable; chat endpoints will report the configuration error, "
            "but schedule and personal-data APIs remain available"
        )
    yield
    logger.info("Server shutting down...")
    await chat.shutdown()
    logger.info("Server stopped")
