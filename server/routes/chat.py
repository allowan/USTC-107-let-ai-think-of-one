"""Chat routes: POST /api/chat/stream (SSE)"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from server.deps import get_user
from server.services.chat_service import ChatService, get_chat_service

logger = logging.getLogger("server")

router = APIRouter(tags=["chat"])


@router.post("/api/chat/stream")
async def chat_stream(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    content = (body.get("content") or "").strip()
    topic_id = (body.get("topic_id") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if len(content) > 10000:
        raise HTTPException(status_code=400, detail="消息长度不能超过 10000 字符")

    return StreamingResponse(
        chat.sse_generator(user, content, topic_id),
        media_type="text/event-stream; charset=utf-8",
    )
