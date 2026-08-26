"""Structured personal schedule routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.deps import get_user
from server.services.schedule_service import ScheduleService, get_schedule_service

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class Meeting(BaseModel):
    weekday: int | None = Field(default=None, ge=1, le=7)
    sections: list[int] = Field(default_factory=list)
    weeks: list[int] = Field(default_factory=list)
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


@router.get("")
async def list_schedule(
    semester: str | None = None,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
):
    return service.list(user, semester)


@router.post("/import")
async def import_schedule(
    payload: ScheduleImport,
    request: Request,
    user: str = Depends(get_user),
    service: ScheduleService = Depends(get_schedule_service),
):
    origin = request.headers.get("origin", "")
    allowed_origin = (
        not origin
        or origin.startswith("http://localhost")
        or origin.startswith("http://127.0.0.1")
    )
    if not allowed_origin:
        raise HTTPException(status_code=403, detail="不允许的课表导入来源")
    if not payload.courses:
        raise HTTPException(status_code=400, detail="未读取到课程")
    count = service.replace(user, payload.semester, [course.model_dump() for course in payload.courses])
    return {"message": "课表同步成功", "semester": payload.semester, "meeting_count": count}
