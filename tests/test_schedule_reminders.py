"""课程提醒必须以实际校历日期为依据，而不是固定月份。"""

from datetime import date
from pathlib import Path

from server.services.schedule_service import ScheduleService


def test_reminders_use_calendar_before_nominal_semester(tmp_path: Path) -> None:
    service = ScheduleService(tmp_path / "schedule.db")
    service.save_calendar("user", "2026年秋季学期", date(2026, 8, 31), 18, [])
    service.replace("user", "2026年秋季学期", [
        {"name": "周一课", "meetings": [{"weekday": 1, "weeks": [1]}]},
        {"name": "周二课", "meetings": [{"weekday": 2, "weeks": [1]}]},
    ])
    result = service.get_course_reminders("user", date(2026, 8, 31))
    assert result["semester"] == "2026年秋季学期"
    assert result["calendar_configured"] is True
    assert [row["name"] for row in result["today"]["courses"]] == ["周一课"]
    assert [row["name"] for row in result["tomorrow"]["courses"]] == ["周二课"]


def test_tomorrow_resolves_its_own_semester_and_week(tmp_path: Path) -> None:
    service = ScheduleService(tmp_path / "schedule.db")
    service.save_calendar("user", "暑期", date(2026, 8, 24), 1, [])
    service.save_calendar("user", "秋季", date(2026, 8, 31), 18, [])
    service.replace("user", "暑期", [{"name": "暑期课", "meetings": [{"weekday": 7}]}])
    service.replace("user", "秋季", [{"name": "秋季课", "meetings": [{"weekday": 1, "weeks": [1]}]}])
    result = service.get_course_reminders("user", date(2026, 8, 30))
    assert result["semester"] == "暑期"
    assert [row["name"] for row in result["today"]["courses"]] == ["暑期课"]
    assert result["tomorrow"]["week"] == 1
    assert [row["name"] for row in result["tomorrow"]["courses"]] == ["秋季课"]


def test_reminders_ignore_other_users_calendars_and_ended_semesters(tmp_path: Path) -> None:
    service = ScheduleService(tmp_path / "schedule.db")
    service.save_calendar("other", "秋季", date(2026, 8, 31), 18, [])
    service.save_calendar("user", "2026年夏季学期", date(2026, 8, 24), 1, [])
    service.replace("user", "2026年夏季学期", [{"name": "过期课", "meetings": [{"weekday": 1}]}])
    result = service.get_course_reminders("user", date(2026, 8, 31))
    assert result["today"]["courses"] == []
    assert result["tomorrow"]["courses"] == []


def test_overlapping_calendars_prefer_most_recent_start(tmp_path: Path) -> None:
    service = ScheduleService(tmp_path / "schedule.db")
    service.save_calendar("user", "暑期", date(2026, 8, 24), 4, [])
    service.save_calendar("user", "秋季", date(2026, 8, 31), 18, [])
    service.replace("user", "秋季", [{"name": "秋季课", "meetings": [{"weekday": 1}]}])
    result = service.get_course_reminders("user", date(2026, 8, 31))
    assert result["semester"] == "秋季"
    assert [row["name"] for row in result["today"]["courses"]] == ["秋季课"]
