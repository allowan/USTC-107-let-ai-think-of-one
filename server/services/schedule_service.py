"""Local structured schedule storage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
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
        query = "SELECT * FROM schedule_courses WHERE username = ?"
        params: list = [username]
        if semester:
            query += " AND semester = ?"
            params.append(semester)
        query += " ORDER BY semester DESC, weekday, start_section, name"
        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute(query, params).fetchall()]
        for row in rows:
            row["teachers"] = json.loads(row["teachers"])
            row["weeks"] = json.loads(row["weeks"])
            if not row.get("start_time") and row.get("start_section") and row.get("end_section"):
                start, end = SECTION_TIME_RANGES.get(
                    (row["start_section"], row["end_section"]), (None, None)
                )
                row["start_time"], row["end_time"] = start, end
        semesters = list(dict.fromkeys(row["semester"] for row in rows))
        return {"semester": semester or (semesters[0] if semesters else None), "semesters": semesters, "courses": rows}


_service: ScheduleService | None = None


def get_schedule_service() -> ScheduleService:
    global _service
    if _service is None:
        _service = ScheduleService()
    return _service
