"""Search routes: /api/search/*"""

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
    return {"query": q, "results": rag.search_notices(q)}


@router.get("/my-data")
async def search_my_data_api(
    q: str = Query(...),
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    return {"query": q, "results": rag.search_user_data(q, user)}
