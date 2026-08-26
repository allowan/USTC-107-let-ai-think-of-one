"""Personal data routes: /api/personal-data/*"""

from urllib.parse import unquote

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service
from server.services.schedule_service import ScheduleService, get_schedule_service
from server.services.ustc_schedule import (
    format_schedule_for_personal_data,
    schedule_data_to_payload,
)
from server.routes.schedule import ensure_local_origin

router = APIRouter(prefix="/api/personal-data", tags=["personal-data"])


class ExistingScheduleImport(BaseModel):
    """Select a semester from the local structured schedule database."""

    semester: str | None = Field(default="", max_length=100)


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
        text = documents[i] if i < len(documents) else ""
        if source not in seen:
            seen[source] = {
                "source": source,
                "preview": previews[i] if i < len(previews) else "",
                "full_content": text,
                "chunks": 1,
            }
        else:
            seen[source]["full_content"] += "\n" + text
            seen[source]["chunks"] += 1

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


@router.post("/import-schedule")
async def import_schedule_to_personal_data(
    request: Request,
    payload: ExistingScheduleImport | None = Body(default=None),
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
    schedule: ScheduleService = Depends(get_schedule_service),
):
    """Copy an existing local schedule into the personal searchable data."""

    ensure_local_origin(request)
    selected_semester = (payload.semester if payload and payload.semester else "").strip() or None
    stored = schedule.list(user, selected_semester)
    if not stored["courses"] or not stored.get("semester"):
        raise HTTPException(
            status_code=400,
            detail="当前没有已导入的课表，请先在‘我的课表’中导入课表",
        )

    parsed = schedule_data_to_payload(stored)
    source = f"课表-{parsed['semester']}"
    rag.update_user_data(user, source, format_schedule_for_personal_data(parsed))
    return {
        "message": "已有课表已同步到个人数据",
        "semester": parsed["semester"],
        "source": source,
        "course_count": len(parsed["courses"]),
        "meeting_count": len(stored["courses"]),
    }


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
