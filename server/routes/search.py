"""Search routes: /api/search/*"""

import asyncio

from fastapi import APIRouter, Depends, Query

from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/notices")
async def search_notices_api(
    q: str = Query(...),
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    # 检索含嵌入 API 调用，同步阻塞会卡住事件循环，丢进线程池
    results = await asyncio.to_thread(rag.search_notices, q)
    return {"query": q, "results": results}


@router.get("/my-data")
async def search_my_data_api(
    q: str = Query(...),
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    results = await asyncio.to_thread(rag.search_user_data, q, user)
    return {"query": q, "results": results}
