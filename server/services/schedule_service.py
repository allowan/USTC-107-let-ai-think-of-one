"""Local structured schedule storage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "schedule.db"

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
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for course in courses:
            meetings = course.get("meetings") or [{}]
            for meeting in meetings:
                sections = [int(x) for x in meeting.get("sections", []) if str(x).isdigit()]
                rows.append(
                    (
                        username,
                        semester,
                        str(course.get("course_code", "")),
                        str(course.get("name", "")),
                        json.dumps(course.get("teachers", []), ensure_ascii=False),
                        meeting.get("weekday"),
                        min(sections) if sections else None,
                        max(sections) if sections else None,
                        json.dumps(meeting.get("weeks", []), ensure_ascii=False),
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
