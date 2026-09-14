"""Digest route: /api/digest — 最近新通知 + 临近事件（截止/开始）的聚合摘要。

数据全部来自 P0 的 events 时间索引（纯本地 SQLite，不依赖嵌入/LLM）。
供前端“今日/最近”面板消费，把 Agent 从“被动问”推进到“主动给”。
同模块托管“追踪事件”CRUD（用户把关心的事件置顶到今日面板，便于到期提醒）。
"""

import asyncio
from datetime import date
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query

from campus_rag import EventQueryError
from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("")
async def digest_api(
    days: int = Query(7, ge=0, le=365),
    rag: RAGService = Depends(get_rag_service),
):
    # 事件库为同步 SQLite 查询，丢线程池避免阻塞事件循环（AGENTS.md 3.4）。
    try:
        return await asyncio.to_thread(rag.get_digest, days)
    except EventQueryError:
        raise HTTPException(status_code=503, detail="事件数据暂时不可用，请稍后重试。")


@router.get("/tracked")
async def list_tracked(user: str = Depends(get_user)):
    from campus_rag import list_tracked_events
    return {"items": await asyncio.to_thread(list_tracked_events, user)}


def _optional_text(body: dict, key: str, limit: int) -> str | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} 必须是字符串")
    value = value.strip()
    if len(value) > limit:
        raise HTTPException(status_code=400, detail=f"{key} 不能超过 {limit} 个字符")
    return value or None


@router.post("/tracked")
async def add_tracked(body: dict, user: str = Depends(get_user)):
    source = _optional_text(body, "source", 1024) or ""
    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")
    date_kind = _optional_text(body, "date_kind", 16) or "deadline"
    if date_kind not in ("deadline", "start"):
        raise HTTPException(status_code=400, detail="date_kind 必须是 deadline 或 start")
    date_value = _optional_text(body, "date_value", 10)
    if date_value:
        try:
            if date.fromisoformat(date_value).isoformat() != date_value:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="date_value 必须是 ISO 日期（YYYY-MM-DD）")
    url = _optional_text(body, "url", 2048)
    if url:
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or any(char.isspace() for char in url)):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="url 必须是无认证信息的 HTTP(S) 地址")
    from campus_rag import track_event
    return await asyncio.to_thread(
        track_event,
        username=user, source=source,
        title=_optional_text(body, "title", 500), category=_optional_text(body, "category", 100),
        date_kind=date_kind, date_value=date_value,
        url=url,
    )


@router.delete("/tracked/{source:path}")
async def remove_tracked(source: str, user: str = Depends(get_user)):
    from campus_rag import untrack_event
    if not await asyncio.to_thread(untrack_event, user, source):
        raise HTTPException(status_code=404, detail="未追踪该事件")
    return {"message": "已取消追踪"}
