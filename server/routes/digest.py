"""Digest route: /api/digest — 最近新通知 + 临近事件（截止/开始）的聚合摘要。

数据全部来自 P0 的 events 时间索引（纯本地 SQLite，不依赖嵌入/LLM）。
供前端“今日/最近”面板消费，把 Agent 从“被动问”推进到“主动给”。
同模块托管“追踪事件”CRUD（用户把关心的事件置顶到今日面板，便于到期提醒）。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("")
async def digest_api(
    days: int = Query(7, ge=0, le=365),
    rag: RAGService = Depends(get_rag_service),
):
    # 事件库为同步 SQLite 查询，丢线程池避免阻塞事件循环（AGENTS.md 3.4）。
    return await asyncio.to_thread(rag.get_digest, days)


@router.get("/tracked")
async def list_tracked(user: str = Depends(get_user)):
    from campus_rag import list_tracked_events
    return {"items": list_tracked_events(user)}


@router.post("/tracked")
async def add_tracked(body: dict, user: str = Depends(get_user)):
    source = (body.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")
    date_kind = body.get("date_kind") or "deadline"
    if date_kind not in ("deadline", "start"):
        raise HTTPException(status_code=400, detail="date_kind 必须是 deadline 或 start")
    date_value = body.get("date_value")
    if date_value:
        # 前端按 ISO 解析计算剩余天数，非法值会让面板显示 NaN——入口即拦
        from datetime import date
        try:
            date.fromisoformat(str(date_value).strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="date_value 必须是 ISO 日期（YYYY-MM-DD）")
    from campus_rag import track_event
    return track_event(
        username=user, source=source,
        title=body.get("title"), category=body.get("category"),
        date_kind=date_kind, date_value=date_value,
        url=body.get("url"),
    )


@router.delete("/tracked/{source}")
async def remove_tracked(source: str, user: str = Depends(get_user)):
    from campus_rag import untrack_event
    if not untrack_event(user, source):
        raise HTTPException(status_code=404, detail="未追踪该事件")
    return {"message": "已取消追踪"}
