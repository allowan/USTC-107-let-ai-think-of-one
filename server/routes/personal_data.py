"""Personal data routes: /api/personal-data/*"""

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/personal-data", tags=["personal-data"])


@router.get("")
async def get_personal_data(
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    data = rag.list_user_data(user)
    ids = data.get("ids") or []
    metadatas = data.get("metadatas") or []
    previews = data.get("previews") or []
    documents = data.get("documents") or []

    seen: dict[str, dict] = {}
    for i in range(len(ids)):
        source = metadatas[i].get("source", "手动输入") if i < len(metadatas) else "手动输入"
        if source not in seen:
            seen[source] = {
                "source": source,
                "preview": previews[i] if i < len(previews) else "",
                "full_content": documents[i] if i < len(documents) else "",
                "chunks": 0,
            }
        seen[source]["chunks"] += 1
        if i < len(documents) and i > 0 and metadatas[i].get("source", "") == source:
            seen[source]["full_content"] += "\n" + documents[i]

    return {"items": list(seen.values())}


@router.post("")
async def add_personal_data(
    body: dict,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    content = (body.get("content") or "").strip()
    source = (body.get("source") or "").strip() or "手动输入"
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    rag.add_user_data(user, content, source)
    return {"message": "数据已添加"}


@router.put("/{source}")
async def update_personal_data(
    source: str,
    body: dict,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    source = unquote(source)
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    rag.update_user_data(user, source, content)
    return {"message": "数据已更新"}


@router.delete("/{source}")
async def delete_personal_data(
    source: str,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    source = unquote(source)
    count = rag.delete_user_data(user, source)
    if count == 0:
        raise HTTPException(status_code=404, detail="数据不存在")
    return {"message": f"已删除 {count} 条数据"}
