"""Personal data routes: /api/personal-data/*"""

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from server.deps import ensure_local_origin, get_user
from server.services.rag_service import RAGService, get_rag_service
from server.services.schedule_service import ScheduleService, get_schedule_service
from server.services.ustc_schedule import (
    format_schedule_for_personal_data,
    schedule_data_to_payload,
)

from server.services.file_import import extract_file, FileImportError, MAX_FILE_BYTES

router = APIRouter(prefix="/api/personal-data", tags=["personal-data"])
logger = logging.getLogger(__name__)


def _embed_unavailable_to_503(exc: RuntimeError):
    """campus_rag 的 fail-fast 守卫（嵌入不可用）抛 RuntimeError：这是服务
    不可用而非内部错误，用 503 + 原始详情回传，前端能展示可操作的提示，
    也避免与真实的 500 混淆。"""
    raise HTTPException(status_code=503, detail=str(exc))

# 注意：路径参数已由框架解码一次，禁止再次 unquote——双重解码会把字面含 %
# 的 source（如 "100%进度"、"a%20b"）损坏，导致更新/删除找错目标。


class ExistingScheduleImport(BaseModel):
    """Select a semester from the local structured schedule database."""

    semester: str | None = Field(default="", max_length=100)


@router.get("")
async def get_personal_data(
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    # ChromaDB 读取是同步阻塞，丢进线程池避免卡住事件循环
    try:
        data = await asyncio.to_thread(rag.list_user_data, user)
        items = await asyncio.to_thread(RAGService.format_user_data, data)
    except Exception:
        logger.warning("个人资料列表暂时无法读取")
        raise HTTPException(status_code=503, detail="个人资料读取失败，请稍后重试；这不表示资料为空") from None
    return {"items": items}


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
    # 入库含嵌入 API 调用，同步阻塞会卡住事件循环（可能数秒）
    try:
        await asyncio.to_thread(rag.add_user_data, user, content, source)
    except RuntimeError as e:
        _embed_unavailable_to_503(e)
    return {"message": "数据已添加"}


@router.post("/parse-file")
async def parse_personal_file(
    request: Request,
    file: UploadFile = File(...),
    user: str = Depends(get_user),
):
    ensure_local_origin(request)
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="文件不能超过 10 MB")
        return await asyncio.to_thread(extract_file, file.filename or "", data)
    except FileImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


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
    # 入库含嵌入 API 调用，同步阻塞会卡住事件循环（可能数秒）
    try:
        await asyncio.to_thread(
            rag.update_user_data, user, source, format_schedule_for_personal_data(parsed)
        )
    except RuntimeError as e:
        _embed_unavailable_to_503(e)
    return {
        "message": "已有课表已同步到个人数据",
        "semester": parsed["semester"],
        "source": source,
        "course_count": len(parsed["courses"]),
        "meeting_count": len(stored["courses"]),
    }


@router.put("/{source:path}")
async def update_personal_data(
    source: str,
    body: dict,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    try:
        await asyncio.to_thread(rag.update_user_data, user, source, content)
    except RuntimeError as e:
        _embed_unavailable_to_503(e)
    return {"message": "数据已更新"}


@router.delete("/{source:path}")
async def delete_personal_data(
    source: str,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    count = await asyncio.to_thread(rag.delete_user_data, user, source)
    if count == 0:
        raise HTTPException(status_code=404, detail="数据不存在")
    return {"message": f"已删除 {count} 条数据"}
