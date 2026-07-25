"""Chat routes: POST /api/chat/stream (SSE) and WS /ws/chat"""

import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from server.deps import get_user, LOCAL_USER
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


@router.websocket("/ws/chat")
async def chat_websocket(ws: WebSocket):
    await ws.accept()
    username = LOCAL_USER
    chat = await get_chat_service()

    try:
        while True:
            data = await ws.receive_json()
            content = (data.get("content") or "").strip()
            topic_id = (data.get("topic_id") or "").strip()
            if not content:
                continue

            thread_id = chat._thread_id(username, topic_id)
            logger.info("WS message from %s: %s", username, content[:50])

            try:
                await chat.handle_ws_stream(ws, username, content, topic_id)
            except Exception as exc:
                err_msg = str(exc)
                if "tool_calls" in err_msg and "tool messages" in err_msg:
                    logger.warning("WS checkpoint corrupted for thread %s, retrying", thread_id)
                    await chat.delete_thread(thread_id)
                    try:
                        await chat.handle_ws_stream(ws, username, content, topic_id)
                    except Exception as exc2:
                        logger.error("WS retry failed for thread %s: %s", thread_id, exc2)
                        await ws.send_json({"type": "error", "content": "处理失败，请重试"})
                else:
                    logger.error("WS error for thread %s: %s", thread_id, exc)
                    await ws.send_json({"type": "error", "content": "处理失败，请重试"})

            await ws.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("WS client disconnected: %s", username)
    except Exception:
        logger.exception("WS unexpected error for user %s", username)
