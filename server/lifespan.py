"""
Server lifespan: initializes and shuts down the ChatService singleton.
"""

import logging
from contextlib import asynccontextmanager

from server.services.chat_service import get_chat_service

logger = logging.getLogger("server")


@asynccontextmanager
async def lifespan(app):
    logger.info("Server starting up...")
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
