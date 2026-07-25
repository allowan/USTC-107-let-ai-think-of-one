"""Topic routes: /api/topics/*"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.auth_service import AuthService, get_auth_service
from server.services.chat_service import ChatService, get_chat_service

logger = logging.getLogger("server")

router = APIRouter(prefix="/api/topics", tags=["topics"])


@router.get("")
async def get_topics(
    user: str = Depends(get_user),
    auth: AuthService = Depends(get_auth_service),
):
    return {"topics": auth.list_topics(user)}


@router.post("")
async def add_topic(
    body: dict,
    user: str = Depends(get_user),
    auth: AuthService = Depends(get_auth_service),
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="话题名称不能为空")
    return auth.create_topic(user, name)


@router.delete("/{topic_id}")
async def remove_topic(
    topic_id: str,
    user: str = Depends(get_user),
    auth: AuthService = Depends(get_auth_service),
    chat: ChatService = Depends(get_chat_service),
):
    t = auth.get_topic(user, topic_id)
    if not t:
        raise HTTPException(status_code=404, detail="话题不存在")
    ok = auth.delete_topic(user, topic_id)
    if not ok:
        raise HTTPException(status_code=500, detail="删除话题失败")
    await chat.delete_thread(t["thread_id"])
    return {"message": "话题已删除"}


@router.put("/{topic_id}")
async def update_topic(
    topic_id: str,
    body: dict,
    user: str = Depends(get_user),
    auth: AuthService = Depends(get_auth_service),
):
    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="话题名称不能为空")
    ok = auth.rename_topic(user, topic_id, new_name)
    if not ok:
        raise HTTPException(status_code=404, detail="话题不存在")
    return {"message": "话题已重命名", "name": new_name}


@router.post("/{topic_id}/summarize")
async def summarize_topic(
    topic_id: str,
    body: dict,
    user: str = Depends(get_user),
    auth: AuthService = Depends(get_auth_service),
):
    user_msg = (body.get("user_message") or "").strip()
    ai_msg = (body.get("ai_message") or "").strip()
    if not user_msg or not ai_msg:
        raise HTTPException(status_code=400, detail="缺少对话内容")

    try:
        from model.config import init_chat
        llm = init_chat()
        prompt = f"根据以下对话，生成一个简短的标题（10字以内，只返回标题本身，不加任何引号或解释）：\n\n用户：{user_msg[:200]}\nAI：{ai_msg[:200]}\n\n标题："
        result = await asyncio.wait_for(
            asyncio.to_thread(llm.invoke, [{"role": "user", "content": prompt}]),
            timeout=10,
        )
        title = str(result.content).strip()[:20]
        if not title:
            title = "默认话题"
    except (Exception, asyncio.TimeoutError):
        logger.warning("Topic summarization failed for user %s, topic %s", user, topic_id, exc_info=True)
        title = "默认话题"

    auth.rename_topic(user, topic_id, title)
    return {"name": title}


@router.get("/{topic_id}/history")
async def get_topic_history(
    topic_id: str,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    messages = await chat.get_history(user, topic_id)
    return {"messages": messages}
