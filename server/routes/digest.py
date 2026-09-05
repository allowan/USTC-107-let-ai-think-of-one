"""Digest route: /api/digest — 最近新通知 + 临近截止事件的聚合摘要。

数据全部来自 P0 的 events 时间索引（纯本地 SQLite，不依赖嵌入/LLM）。
供前端“今日/最近”面板消费，把 Agent 从“被动问”推进到“主动给”。
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("")
async def digest_api(
    days: int = Query(7, ge=0, le=365),
    rag: RAGService = Depends(get_rag_service),
):
    # 事件库为同步 SQLite 查询，丢线程池避免阻塞事件循环（AGENTS.md 3.4）。
    return await asyncio.to_thread(rag.get_digest, days)
