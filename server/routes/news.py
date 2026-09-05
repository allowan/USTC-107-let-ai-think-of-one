from fastapi import APIRouter, Depends
from server.deps import get_user
from server.services.news_service import news_service

router = APIRouter(prefix='/api/news', tags=['news'])


@router.get('')
async def news(refresh: bool = False, user: str = Depends(get_user)):
    return await news_service.get_news(refresh)
