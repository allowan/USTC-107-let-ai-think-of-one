"""Structured personal schedule routes."""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, model_validator

from server.deps import get_user
from server.services.academic_calendar import (
    AcademicCalendarParseError,
    parse_academic_calendar_ics,
)
from server.services.schedule_service import ScheduleImportValidationError, ScheduleService, get_schedule_service
from server.services.ustc_schedule import UstcScheduleParseError, parse_ustc_schedule

router = APIRouter(prefix="/api/schedule", tags=["schedule"])
logger = logging.getLogger(__name__)


class Meeting(BaseModel):
    weekday: Any = None
    sections: list[Any] = Field(default_factory=list)
    weeks: list[Any] = Field(default_factory=list)
    location: str = ""
    start_time: str | None = None
    end_time: str | None = None


class Course(BaseModel):
    course_code: str = ""
    name: str = Field(min_length=1)
    teachers: list[str] = Field(default_factory=list)
    credits: float | None = None
    raw_schedule: str = ""
    meetings: list[Meeting] = Field(default_factory=list)


class ScheduleImport(BaseModel):
    semester: str = Field(min_length=1, max_length=100)
    courses: list[Course] = Field(max_length=500)


class UstcScheduleImport(BaseModel):
    """Content explicitly exported or pasted by the user from USTC JW."""

    content: str = Field(min_length=1, max_length=5_000_000)
    filename: str = Field(default="", max_length=255)


class SpecialDate(BaseModel):
    date: date
    kind: Literal["holiday", "no_class", "makeup", "note"]
    label: str = Field(min_length=1, max_length=100)
    course_weekday: int | None = Field(default=None, ge=1, le=7)


class AcademicCalendarUpdate(BaseModel):
    semester: str = Field(min_length=1, max_length=100)
    start_date: date | None = None
    total_weeks: int | None = Field(default=None, ge=1, le=30)
    special_dates: list[SpecialDate] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_calendar(self) -> "AcademicCalendarUpdate":
        """校历以周一为周起点，并拒绝范围外或相互冲突的特殊日期。"""

        if self.start_date is not None and self.start_date.weekday() != 0:
            raise ValueError("第一周开始日期必须是周一")
        seen_dates: set[date] = set()
        for item in self.special_dates:
            if item.date in seen_dates:
                raise ValueError("同一天只能配置一项特殊安排")
            if item.kind == "makeup" and item.course_weekday is None:
                raise ValueError("调课或补课必须指定按星期几的课程安排")
            seen_dates.add(item.date)
        return self


def ensure_local_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    allowed_origin = (
        not origin
        or origin.startswith("http://localhost")
        or origin.startswith("http://127.0.0.1")
    )
    if not allowed_origin:
        raise HTTPException(status_code=403, detail="不允许的课表导入来源")


@router.get("")
async def list_schedule(
    semester: str | None = None,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> dict:
    # SQLite 同步阻塞，与项目其他路由一致丢线程池（AGENTS.md 3.4）
    return await asyncio.to_thread(service.list, user, semester)


@router.get("/calendar")
async def get_academic_calendar(
    semester: str,
    on_date: date | None = None,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> dict:
    calendar = await asyncio.to_thread(service.get_calendar, user, semester, on_date)
    if calendar is None:
        raise HTTPException(status_code=404, detail="该学期尚未配置校历")
    return calendar


@router.get("/reminders")
async def get_course_reminders(
    on_date: date | None = None,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> dict:
    return await asyncio.to_thread(service.get_course_reminders, user, on_date)


@router.put("/calendar")
async def update_academic_calendar(
    payload: AcademicCalendarUpdate,
    request: Request,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> dict:
    ensure_local_origin(request)
    existing = await asyncio.to_thread(service.get_calendar, user, payload.semester)
    start_date = payload.start_date or (date.fromisoformat(existing["start_date"]) if existing else None)
    total_weeks = payload.total_weeks or (existing["total_weeks"] if existing else None)
    if start_date is None or total_weeks is None:
        raise HTTPException(status_code=400, detail="请先导入校历，再校正日期或教学周数")
    end_date = start_date + timedelta(days=total_weeks * 7)
    special_dates = [item.model_dump(mode="json") for item in payload.special_dates]
    if any(not start_date <= item.date < end_date for item in payload.special_dates):
        raise HTTPException(status_code=400, detail="特殊日期必须位于该学期教学周范围内")
    calendar = await asyncio.to_thread(
        service.save_calendar,
        user,
        payload.semester,
        start_date,
        total_weeks,
        special_dates,
    )
    return {"message": "校历保存成功", "calendar": calendar}


async def _save_imported_calendars(
    calendars: list[dict], user: str, service: ScheduleService
) -> list[dict]:
    saved = []
    for item in calendars:
        calendar = await asyncio.to_thread(
            service.save_calendar,
            user,
            item["semester"],
            item["start_date"],
            item["total_weeks"],
            item["special_dates"],
        )
        calendar["warnings"] = item.get("warnings", [])
        saved.append(calendar)
    return saved


@router.post("/calendar/import-ics")
async def import_academic_calendar_ics(
    request: Request,
    file: UploadFile = File(...),
    semester: str = Form(...),
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> dict:
    """解析用户主动上传的 USTC 教学日历 iCalendar。"""

    ensure_local_origin(request)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="校历 iCalendar 不能超过 10 MB")
    try:
        parsed = await asyncio.to_thread(parse_academic_calendar_ics, file.filename or "", data, semester)
    except AcademicCalendarParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing_calendars = []
    new_items = []
    for item in parsed:
        existing = await asyncio.to_thread(service.get_calendar, user, item["semester"])
        if existing is None:
            new_items.append(item)
        else:
            existing_calendars.append(existing)
    if not new_items:
        return {
            "message": "文件中的校历已导入",
            "already_exists": True,
            "calendars": existing_calendars,
        }
    saved = await _save_imported_calendars(new_items, user, service)
    return {
        "message": "校历 iCalendar 导入成功",
        "already_exists": False,
        "calendars": existing_calendars + saved,
    }


@router.post("/import")
async def import_schedule(
    payload: ScheduleImport,
    request: Request,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
):
    ensure_local_origin(request)
    if not payload.courses:
        raise HTTPException(status_code=400, detail="未读取到课程")
    try:
        count = await asyncio.to_thread(
            service.replace, user, payload.semester,
            [course.model_dump() for course in payload.courses],
        )
    except ScheduleImportValidationError as exc:
        logger.warning("结构化课表导入被拒绝：%d 项校验问题", len(exc.errors))
        raise HTTPException(status_code=400, detail={
            "message": "课表校验失败，原有课表未修改", "errors": exc.errors,
        }) from exc
    return {"message": "课表同步成功", "semester": payload.semester, "meeting_count": count}


@router.post("/import-ustc")
async def import_ustc_schedule(
    payload: UstcScheduleImport,
    request: Request,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
):
    """Parse an exported USTC course-table page and replace that semester."""

    ensure_local_origin(request)
    try:
        parsed = await asyncio.to_thread(parse_ustc_schedule, payload.content, payload.filename)
        count = await asyncio.to_thread(service.replace, user, parsed["semester"], parsed["courses"])
    except ScheduleImportValidationError as exc:
        logger.warning("教务课表导入被拒绝：%d 项校验问题", len(exc.errors))
        raise HTTPException(status_code=400, detail={
            "message": "课表校验失败，原有课表未修改", "errors": exc.errors,
        }) from exc
    except UstcScheduleParseError as exc:
        logger.warning("教务课表解析失败：%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "教务课表解析并同步成功",
        "semester": parsed["semester"],
        "course_count": len(parsed["courses"]),
        "meeting_count": count,
    }
