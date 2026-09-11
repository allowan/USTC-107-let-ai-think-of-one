"""Local structured schedule storage."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "schedule.db"
logger = logging.getLogger(__name__)

# USTC's standard period ranges. Imported files can provide exact times; these
# ranges keep older section-only records useful in the local UI as well.
SECTION_TIME_RANGES = {
    (1, 2): ("08:00", "09:35"),
    (3, 4): ("10:00", "11:35"),
    (5, 6): ("14:00", "15:35"),
    (8, 9): ("15:55", "17:30"),
    (11, 12): ("19:00", "20:35"),
    (13, 14): ("20:40", "22:15"),
}


class ScheduleImportValidationError(ValueError):
    """课表未通过完整校验，errors 包含各项可定位的问题。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("；".join(errors))


def _integer(value: object) -> int | None:
    # 保留数字字符串兼容，但禁止 bool、小数以及部分可解析的字符串。
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        try:
            return int(value)
        except ValueError:
            logger.warning("课表整数值超过可解析范围")
            return None
    return None


def validate_schedule_import(semester: str, courses: list[dict]) -> list[str]:
    """校验完整课表并返回所有问题；不写库，也不修改传入数据。"""
    errors: list[str] = []
    if not isinstance(semester, str) or not semester.strip():
        errors.append("学期名称不能为空")
    if not isinstance(courses, list) or not courses:
        errors.append("课程必须是非空数组")
        return errors
    for course_index, course in enumerate(courses, 1):
        prefix = f"第{course_index}门课程"
        if not isinstance(course, dict):
            errors.append(f"{prefix}：必须是课程对象")
            continue
        name = course.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}：课程名称不能为空")
        else:
            prefix += f"（{name.strip()}）"
        meetings = course.get("meetings", [])
        if not isinstance(meetings, list):
            errors.append(f"{prefix}：安排必须是数组")
            continue
        for meeting_index, meeting in enumerate(meetings, 1):
            position = f"{prefix}第{meeting_index}项安排"
            if not isinstance(meeting, dict):
                errors.append(f"{position}：必须是安排对象")
                continue
            weekday = meeting.get("weekday")
            day = _integer(weekday)
            if weekday is not None and (day is None or not 1 <= day <= 7):
                errors.append(f"{position}：星期必须是1–7的整数")
            for field, label in (("sections", "节次"), ("weeks", "周次")):
                values = meeting.get(field, [])
                if not isinstance(values, list):
                    errors.append(f"{position}：{label}必须是数组")
                    continue
                numbers = [_integer(value) for value in values]
                if any(number is None or number < 1 or (field == "sections" and number > 13)
                       for number in numbers):
                    constraint = "1–13的整数" if field == "sections" else "正整数"
                    errors.append(f"{position}：{label}必须全部为{constraint}")
                elif field == "sections" and any(left >= right for left, right in zip(numbers, numbers[1:])):
                    errors.append(f"{position}：节次必须升序排列且不能重复")
            start, end = meeting.get("start_time"), meeting.get("end_time")
            if start is not None or end is not None:
                valid_times = all(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)
                                  for value in (start, end))
                if not valid_times:
                    errors.append(f"{position}：开始和结束时间必须成对提供，格式为HH:MM")
                elif start >= end:
                    errors.append(f"{position}：结束时间必须晚于开始时间")
    return errors


def current_semester(today: datetime | None = None) -> str:
    """按今天日期推断当前学期名（中科大三学期制）。"""

    now = today or datetime.now()
    if 2 <= now.month <= 6:
        return f"{now.year}年春季学期"
    if now.month in (7, 8):
        return f"{now.year}年夏季学期"
    # 秋季学期跨年：1 月仍属于上一年秋季
    return f"{now.year - 1 if now.month == 1 else now.year}年秋季学期"


class ScheduleService:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        # closing 必不可少：sqlite3 的 with 只管理事务不关闭连接，
        # 未关闭的句柄在 Windows 上会持续锁住 db 文件。
        with closing(self._connect()) as db, db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    semester TEXT NOT NULL,
                    course_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    teachers TEXT NOT NULL,
                    weekday INTEGER,
                    start_section INTEGER,
                    end_section INTEGER,
                    weeks TEXT NOT NULL,
                    location TEXT NOT NULL,
                    credits REAL,
                    start_time TEXT,
                    end_time TEXT,
                    raw_schedule TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(schedule_courses)")}
            if "start_time" not in columns:
                db.execute("ALTER TABLE schedule_courses ADD COLUMN start_time TEXT")
            if "end_time" not in columns:
                db.execute("ALTER TABLE schedule_courses ADD COLUMN end_time TEXT")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS academic_calendars (
                    username TEXT NOT NULL,
                    semester TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    total_weeks INTEGER NOT NULL,
                    special_dates TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (username, semester)
                )
                """
            )

    def replace(self, username: str, semester: str, courses: list[dict]) -> int:
        """完整校验后原子替换指定用户学期课表；校验失败保留全部原数据。"""
        errors = validate_schedule_import(semester, courses)
        if errors:
            logger.warning("课表导入校验失败，共 %d 项问题", len(errors))
            raise ScheduleImportValidationError(errors)
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for course in courses:
            meetings = course.get("meetings") or [{}]
            for meeting in meetings:
                sections = [int(x) for x in meeting.get("sections", [])]
                rows.append(
                    (
                        username,
                        semester,
                        str(course.get("course_code", "")),
                        str(course.get("name", "")),
                        json.dumps(course.get("teachers", []), ensure_ascii=False),
                        int(meeting["weekday"]) if meeting.get("weekday") is not None else None,
                        min(sections) if sections else None,
                        max(sections) if sections else None,
                        json.dumps([int(x) for x in meeting.get("weeks", [])], ensure_ascii=False),
                        str(meeting.get("location", "")),
                        course.get("credits"),
                        meeting.get("start_time"),
                        meeting.get("end_time"),
                        str(course.get("raw_schedule", "")),
                        now,
                    )
                )
        with closing(self._connect()) as db, db:
            db.execute(
                "DELETE FROM schedule_courses WHERE username = ? AND semester = ?",
                (username, semester),
            )
            db.executemany(
                """
                INSERT INTO schedule_courses (
                    username, semester, course_code, name, teachers, weekday,
                    start_section, end_section, weeks, location, credits,
                    start_time, end_time, raw_schedule, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def list(self, username: str, semester: str | None = None) -> dict:
        """查询课表。semester 为 None 时返回该用户所有学期的课程。"""
        query = "SELECT * FROM schedule_courses WHERE username = ?"
        params: list = [username]
        if semester:
            query += " AND semester = ?"
            params.append(semester)
        query += " ORDER BY semester DESC, weekday, start_section, name"
        # 学期列表是数据集的属性，必须独立于 semester 过滤条件查询；
        # 否则按学期过滤后下拉框只剩当前学期，前端无法切回其他学期。
        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute(query, params).fetchall()]
            semesters = [
                row["semester"]
                for row in db.execute(
                    "SELECT DISTINCT semester FROM schedule_courses WHERE username = ? ORDER BY semester DESC",
                    (username,),
                ).fetchall()
            ]
        for row in rows:
            row["teachers"] = json.loads(row["teachers"])
            row["weeks"] = json.loads(row["weeks"])
            # 旧版本曾截断多段周次；读取时按原始安排重新推导，避免用户必须手工改库。
            if row.get("raw_schedule"):
                from server.services.ustc_schedule import parse_schedule_entries

                candidates = parse_schedule_entries(row["raw_schedule"])
                for candidate in candidates:
                    if candidate["weekday"] != row.get("weekday"):
                        continue
                    if candidate["sections"] and tuple(candidate["sections"]) != tuple(
                        range(row.get("start_section") or 0, (row.get("end_section") or 0) + 1)
                    ):
                        continue
                    if candidate["start_time"] and row.get("start_time") and candidate["start_time"] != row.get("start_time"):
                        continue
                    row["weeks"] = candidate["weeks"]
                    break
            if not row.get("start_time") and row.get("start_section") and row.get("end_section"):
                start, end = SECTION_TIME_RANGES.get(
                    (row["start_section"], row["end_section"]), (None, None)
                )
                row["start_time"], row["end_time"] = start, end
        return {"semester": semester or (semesters[0] if semesters else None), "semesters": semesters, "courses": rows}

    def save_calendar(
        self,
        username: str,
        semester: str,
        start_date: date,
        total_weeks: int,
        special_dates: list[dict],
    ) -> dict:
        """保存学期校历；重复保存同一学期时原子覆盖配置。"""

        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db, db:
            db.execute(
                """
                INSERT INTO academic_calendars (
                    username, semester, start_date, total_weeks, special_dates, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(username, semester) DO UPDATE SET
                    start_date = excluded.start_date,
                    total_weeks = excluded.total_weeks,
                    special_dates = excluded.special_dates,
                    updated_at = excluded.updated_at
                """,
                (
                    username,
                    semester,
                    start_date.isoformat(),
                    total_weeks,
                    json.dumps(special_dates, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_calendar(username, semester) or {}

    def get_calendar(
        self,
        username: str,
        semester: str,
        on_date: date | None = None,
    ) -> dict | None:
        """读取校历，并计算指定日期所在的教学周。"""

        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM academic_calendars WHERE username = ? AND semester = ?",
                (username, semester),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["special_dates"] = json.loads(result["special_dates"])
        first_day = date.fromisoformat(result["start_date"])
        target = on_date or date.today()
        offset = (target - first_day).days
        week_number = offset // 7 + 1
        if offset < 0:
            status = "not_started"
            current_week = None
        elif week_number > result["total_weeks"]:
            status = "ended"
            current_week = None
        else:
            status = "active"
            current_week = week_number
        result.update(
            {
                "status": status,
                "current_week": current_week,
                "week_start": (
                    first_day + timedelta(days=(week_number - 1) * 7)
                ).isoformat() if current_week else None,
                "week_end": (
                    first_day + timedelta(days=(week_number - 1) * 7 + 6)
                ).isoformat() if current_week else None,
                "today_special_dates": [
                    item for item in result["special_dates"] if item.get("date") == target.isoformat()
                ],
            }
        )
        return result

    def get_course_reminders(self, username: str, on_date: date | None = None) -> dict:
        """按当前学期校历生成今天和明天的实际课程提醒。"""

        target = on_date or date.today()
        semester = current_semester(datetime(target.year, target.month, target.day))
        courses = self.list(username, semester)["courses"]

        def reminder_for(day: date) -> dict:
            calendar = self.get_calendar(username, semester, day)
            if calendar is None:
                return {"date": day.isoformat(), "week": None, "courses": [], "special_dates": []}
            specials = calendar["today_special_dates"]
            week = calendar["current_week"]
            suspended = any(item.get("kind") in {"holiday", "no_class"} for item in specials)
            makeup = next(
                (item for item in specials if item.get("kind") == "makeup" and item.get("course_weekday")),
                None,
            )
            weekday = makeup["course_weekday"] if makeup else day.weekday() + 1
            day_courses = [] if not week or suspended else [
                row for row in courses
                if row.get("weekday") == weekday
                and (not row.get("weeks") or week in row["weeks"])
            ]
            return {
                "date": day.isoformat(),
                "week": week,
                "courses": day_courses,
                "special_dates": specials,
            }

        return {
            "semester": semester,
            "calendar_configured": self.get_calendar(username, semester, target) is not None,
            "today": reminder_for(target),
            "tomorrow": reminder_for(target + timedelta(days=1)),
        }


_service: ScheduleService | None = None


def get_schedule_service() -> ScheduleService:
    global _service
    if _service is None:
        _service = ScheduleService()
    return _service
