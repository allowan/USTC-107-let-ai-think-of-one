import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from server.services.schedule_service import ScheduleService


class ScheduleServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = ScheduleService(Path(self.temp_dir.name) / "schedule.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_structured_weeks_override_raw_text_after_preview_and_save(self) -> None:
        courses = [{"name": "课程", "raw_schedule": "2-3周 教室：1(1-2)", "meetings": [
            {"weekday": 1, "sections": [1, 2], "weeks": [1]},
            {"weekday": 1, "sections": [1, 2], "weeks": [4, 5]},
        ]}]
        preview = self.service.preview_import("student-a", "秋季", courses)
        self.assertEqual([meeting["weeks"] for meeting in preview["payload"]["courses"][0]["meetings"]], [[1], [4, 5]])
        self.service.replace("student-a", "秋季", preview["payload"]["courses"])
        stored = self.service.list("student-a", "秋季")["courses"]
        self.assertEqual(sorted(row["weeks"] for row in stored), [[1], [4, 5]])
        self.assertTrue(all(row["raw_schedule"] == courses[0]["raw_schedule"] for row in stored))

    def test_preview_default_times_match_list_and_warn(self) -> None:
        from server.services.schedule_service import SECTION_TIME_RANGES

        courses = [{"name": "课程", "meetings": [{"weekday": 1, "sections": [1, 2], "weeks": [1]}]}]
        preview = self.service.preview_import("student-a", "秋季", courses)
        meeting = preview["payload"]["courses"][0]["meetings"][0]
        self.assertEqual((meeting["start_time"], meeting["end_time"]), SECTION_TIME_RANGES[(1, 2)])
        self.assertTrue(any("内置默认表" in warning for warning in preview["warnings"]))
        self.service.replace("student-a", "秋季", preview["payload"]["courses"])
        row = self.service.list("student-a", "秋季")["courses"][0]
        self.assertEqual((row["start_time"], row["end_time"]), (meeting["start_time"], meeting["end_time"]))
        courses[0]["meetings"][0].update(start_time="09:00", end_time="10:00")
        explicit = self.service.preview_import("student-a", "秋季", courses)
        self.assertFalse(any("内置默认表" in warning for warning in explicit["warnings"]))
        self.assertEqual(explicit["payload"]["courses"][0]["meetings"][0]["start_time"], "09:00")

    def test_preview_is_read_only_and_confirmation_matches_payload(self) -> None:
        from server.routes.schedule import ScheduleImport

        self.service.replace("student-a", "秋季", [{"name": "原课程"}])
        self.service.replace("student-a", "春季", [{"name": "其他学期"}])
        self.service.replace("student-b", "秋季", [{"name": "其他用户"}])
        self.service.save_calendar("student-a", "秋季", date(2026, 8, 31), 20, [])
        before_bytes = self.service.db_path.read_bytes()
        source = [{"name": "新课程", "teachers": ["教师甲"], "meetings": [
            {"weekday": "2", "sections": ["6", "10"], "weeks": ["3", "1", "3"]},
        ]}, {"name": "待定课程", "meetings": []}]
        result = self.service.preview_import("student-a", "秋季", source)
        self.assertEqual(self.service.db_path.read_bytes(), before_bytes)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["existing_meeting_count"], 1)
        self.assertEqual((result["course_count"], result["meeting_count"]), (2, 2))
        self.assertTrue(result["warnings"])
        normalized = result["payload"]["courses"][0]["meetings"][0]
        self.assertEqual(normalized["sections"], [6, 7, 8, 9, 10])
        self.assertEqual(normalized["weeks"], [1, 3])
        self.assertEqual(source[0]["meetings"][0]["sections"], ["6", "10"])
        confirmation = ScheduleImport.model_validate(result["payload"])
        self.assertEqual(self.service.replace("student-a", confirmation.semester,
                         [course.model_dump() for course in confirmation.courses]), result["meeting_count"])
        saved = next(row for row in self.service.list("student-a", "秋季")["courses"] if row["name"] == "新课程")
        self.assertEqual((saved["start_section"], saved["end_section"], saved["weeks"]), (6, 10, [1, 3]))
        self.assertEqual(self.service.list("student-b")["courses"][0]["name"], "其他用户")
        self.assertEqual(self.service.list("student-a", "春季")["courses"][0]["name"], "其他学期")
        self.assertEqual(self.service.get_calendar("student-a", "秋季")["total_weeks"], 20)

    def test_preview_errors_are_read_only_and_duplicates_include_teachers(self) -> None:
        from server.services.schedule_service import ScheduleImportValidationError

        self.service.replace("student-a", "秋季", [{"name": "原课程"}])
        before = self.service.db_path.read_bytes()
        invalid = [{"name": "错误课", "meetings": [{"sections": [60]}]}]
        result = self.service.preview_import("student-a", "秋季", invalid)
        self.assertTrue(result["errors"])
        with self.assertRaises(ScheduleImportValidationError):
            self.service.replace("student-a", "秋季", result["payload"]["courses"])
        self.assertEqual(self.service.db_path.read_bytes(), before)
        courses = [{"name": "课程", "teachers": [teacher], "meetings": [
            {"weekday": 1, "sections": [1], "weeks": [1]},
        ]} for teacher in ["甲", "乙", "甲"]]
        warnings = self.service.preview_import("student-a", "秋季", courses)["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("第3门课程", warnings[0])
        self.assertIn("重复", warnings[0])
        self.assertEqual(self.service.preview_import("student-a", "新学期", courses)["existing_meeting_count"], 0)
        malformed = self.service.preview_import("student-a", {"bad": "semester"}, invalid)
        self.assertIsInstance(malformed["payload"]["semester"], str)
        self.assertTrue(malformed["errors"])

    def test_structured_preview_errors_and_origin(self) -> None:
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        app = create_app()
        app.dependency_overrides[get_schedule_service] = lambda: self.service
        before = self.service.db_path.read_bytes()
        client = TestClient(app, base_url="http://localhost")
        try:
            body = {"semester": "秋季", "courses": [{"name": "异常课", "meetings": [{"sections": [60]}]}]}
            response = client.post("/api/schedule/preview", json=body)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["errors"])
            blocked = client.post("/api/schedule/preview", json=body,
                                  headers={"Origin": "https://untrusted.example"})
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(self.service.db_path.read_bytes(), before)
        finally:
            client.close()

    def test_invalid_import_preserves_all_existing_rows(self) -> None:
        from server.services.schedule_service import ScheduleImportValidationError

        self.service.replace("student-a", "秋季", [{"name": "原课程"}])
        self.service.replace("student-a", "春季", [{"name": "其他学期"}])
        before = self.service.list("student-a")
        invalid_meetings = [
            {"sections": [0, 55]}, {"sections": [13, 12]}, {"sections": [1, 1]},
            {"sections": [True]}, {"sections": [1.0]}, {"sections": ["2a"]},
            {"weekday": 8}, {"weekday": False}, {"weekday": 1.5},
            {"weeks": [0]}, {"weeks": [1.5]}, {"weeks": ["bad"]},
            {"start_time": "18:30"}, {"start_time": "24:00", "end_time": "25:00"},
            {"start_time": "19:00", "end_time": "18:00"},
        ]
        for meeting in invalid_meetings:
            with self.subTest(meeting=meeting):
                with self.assertRaises(ScheduleImportValidationError) as caught:
                    self.service.replace("student-a", "秋季", [{"name": "异常课", "meetings": [meeting]}])
                self.assertIn("第1门课程（异常课）第1项安排", caught.exception.errors[0])
                self.assertEqual(self.service.list("student-a"), before)

    def test_import_validation_collects_errors_and_preserves_compatible_data(self) -> None:
        from server.services.schedule_service import validate_schedule_import

        errors = validate_schedule_import(" ", [{"name": " ", "meetings": [
            {"weekday": 0, "sections": [14], "weeks": [-1], "start_time": "wrong"},
        ]}])
        self.assertEqual(len(errors), 6)
        courses = [
            {"name": "全日课程", "meetings": [{"weekday": "7", "sections": [str(x) for x in range(1, 14)], "weeks": ["99"]}]},
            {"name": "钟点课", "meetings": [{"weekday": 1, "start_time": "18:30", "end_time": "21:30"}]},
            {"name": "待安排", "meetings": []},
            {"name": "空节次", "meetings": [{"weekday": 2, "sections": []}]},
        ]
        self.assertEqual(validate_schedule_import("秋季", courses), [])
        self.assertEqual(self.service.replace("student-a", "秋季", courses), 4)
        rows = self.service.list("student-a")["courses"]
        full = next(row for row in rows if row["name"] == "全日课程")
        self.assertEqual((full["start_section"], full["end_section"], full["weekday"], full["weeks"]), (1, 13, 7, [99]))

    def test_api_rejects_invalid_numbers_without_coercion(self) -> None:
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        self.service.replace("local_user", "秋季", [{"name": "原课程"}])
        before = self.service.list("local_user")
        app = create_app()
        app.dependency_overrides[get_schedule_service] = lambda: self.service
        client = TestClient(app, base_url="http://localhost")
        try:
            for meeting in [{"sections": [True]}, {"sections": [1.0]}, {"weeks": [False]}, {"weekday": 1.5}]:
                response = client.post("/api/schedule/import", json={"semester": "秋季", "courses": [{"name": "异常课", "meetings": [meeting]}]})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["detail"]["errors"])
                self.assertEqual(self.service.list("local_user"), before)
        finally:
            client.close()

    def test_replace_and_list_schedule(self):
        count = self.service.replace(
            "student-a",
            "2026年秋季学期",
            [
                {
                    "course_code": "210716.01",
                    "name": "深度学习实践",
                    "teachers": ["教师甲"],
                    "credits": 2,
                    "raw_schedule": "1~10周 教室A :5(8,9)",
                    "meetings": [
                        {
                            "weekday": 5,
                            "sections": [8, 9],
                            "weeks": list(range(1, 11)),
                            "location": "教室A",
                            "start_time": "15:55",
                            "end_time": "17:30",
                        }
                    ],
                }
            ],
        )
        result = self.service.list("student-a")
        self.assertEqual(count, 1)
        self.assertEqual(result["semester"], "2026年秋季学期")
        self.assertEqual(result["courses"][0]["weekday"], 5)
        self.assertEqual(result["courses"][0]["start_section"], 8)
        self.assertEqual(result["courses"][0]["teachers"], ["教师甲"])
        self.assertEqual(result["courses"][0]["start_time"], "15:55")
        self.assertEqual(result["courses"][0]["end_time"], "17:30")

    def test_replace_is_scoped_by_user_and_semester(self):
        course = {"name": "课程A", "meetings": [{"weekday": 1, "sections": [1], "weeks": [1]}]}
        self.service.replace("student-a", "秋季", [course])
        self.service.replace("student-b", "秋季", [{"name": "课程B", "meetings": []}])
        self.service.replace("student-a", "春季", [{"name": "课程C", "meetings": []}])
        self.service.replace("student-a", "秋季", [{"name": "课程D", "meetings": []}])
        self.assertEqual([row["name"] for row in self.service.list("student-a", "秋季")["courses"]], ["课程D"])
        self.assertEqual([row["name"] for row in self.service.list("student-b")["courses"]], ["课程B"])

    def test_semester_list_is_not_collapsed_by_semester_filter(self):
        """按学期过滤后，semesters 必须仍包含所有学期，否则前端下拉框无法切回。"""
        course = {"name": "课程A", "meetings": [{"weekday": 1, "sections": [1], "weeks": [1]}]}
        self.service.replace("student-a", "2026年秋季学期", [course])
        self.service.replace("student-a", "2026年春季学期", [course])
        filtered = self.service.list("student-a", "2026年春季学期")
        self.assertEqual(filtered["semester"], "2026年春季学期")
        self.assertEqual(filtered["semesters"], ["2026年秋季学期", "2026年春季学期"])

    def test_schedule_import_api_rejects_untrusted_web_origin(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        app = create_app()
        app.dependency_overrides[get_schedule_service] = lambda: self.service
        payload = {"semester": "秋季", "courses": [{"name": "课程A", "meetings": []}]}
        client = TestClient(app, base_url="http://localhost")
        try:
            denied = client.post(
                "/api/schedule/import",
                json=payload,
                headers={"Origin": "https://untrusted.example"},
            )
            allowed = client.post(
                "/api/schedule/import",
                json=payload,
                headers={"Origin": "http://127.0.0.1:3000"},
            )
        finally:
            client.close()
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_calendar_computes_week_boundaries_and_special_dates(self):
        self.service.save_calendar(
            "student-a",
            "2026年秋季学期",
            date(2026, 8, 31),
            18,
            [{"date": "2026-09-09", "kind": "no_class", "label": "校庆停课", "course_weekday": None}],
        )
        active = self.service.get_calendar("student-a", "2026年秋季学期", date(2026, 9, 9))
        self.assertIsNotNone(active)
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["current_week"], 2)
        self.assertEqual(active["week_start"], "2026-09-07")
        self.assertEqual(active["week_end"], "2026-09-13")
        self.assertEqual(active["today_special_dates"][0]["label"], "校庆停课")

    def test_calendar_reports_before_and_after_semester(self):
        self.service.save_calendar("student-a", "秋季", date(2026, 8, 31), 2, [])
        before = self.service.get_calendar("student-a", "秋季", date(2026, 8, 30))
        after = self.service.get_calendar("student-a", "秋季", date(2026, 9, 14))
        self.assertEqual(before["status"], "not_started")
        self.assertIsNone(before["current_week"])
        self.assertEqual(after["status"], "ended")
        self.assertIsNone(after["current_week"])

    def test_course_reminders_combine_calendar_schedule_and_makeup(self):
        self.service.replace("student-a", "2026年秋季学期", [
            {"name": "周一课程", "meetings": [{"weekday": 1, "sections": [1, 2], "weeks": [1]}]},
            {"name": "周五课程", "meetings": [{"weekday": 5, "sections": [3, 4], "weeks": [1]}]},
        ])
        self.service.save_calendar("student-a", "2026年秋季学期", date(2026, 8, 31), 20, [
            {"date": "2026-09-01", "kind": "makeup", "label": "补周五课", "course_weekday": 5},
            {"date": "2026-09-02", "kind": "no_class", "label": "停课", "course_weekday": None},
        ])
        makeup = self.service.get_course_reminders("student-a", date(2026, 9, 1))
        suspended = self.service.get_course_reminders("student-a", date(2026, 9, 2))
        self.assertEqual([row["name"] for row in makeup["today"]["courses"]], ["周五课程"])
        self.assertEqual(suspended["today"]["courses"], [])
        self.assertEqual(suspended["today"]["special_dates"][0]["label"], "停课")

    def test_calendar_api_validates_week_start_and_makeup_day(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        app = create_app()
        app.dependency_overrides[get_schedule_service] = lambda: self.service
        client = TestClient(app, base_url="http://localhost")
        try:
            invalid_start = client.put("/api/schedule/calendar", json={
                "semester": "秋季", "start_date": "2026-09-01", "total_weeks": 18,
            })
            invalid_makeup = client.put("/api/schedule/calendar", json={
                "semester": "秋季", "start_date": "2026-08-31", "total_weeks": 18,
                "special_dates": [{"date": "2026-09-05", "kind": "makeup", "label": "补课"}],
            })
            valid = client.put("/api/schedule/calendar", json={
                "semester": "秋季", "start_date": "2026-08-31", "total_weeks": 18,
                "special_dates": [{"date": "2026-09-05", "kind": "makeup", "label": "补周一课程", "course_weekday": 1}],
            })
            loaded = client.get("/api/schedule/calendar", params={"semester": "秋季", "on_date": "2026-09-05"})
        finally:
            client.close()
        self.assertEqual(invalid_start.status_code, 422)
        self.assertEqual(invalid_makeup.status_code, 422)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(loaded.json()["current_week"], 1)

    def test_calendar_update_can_preserve_optional_week_fields(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        self.service.save_calendar("local_user", "2026年秋季学期", date(2026, 8, 31), 20, [])
        app = create_app()
        app.dependency_overrides[get_schedule_service] = lambda: self.service
        client = TestClient(app, base_url="http://localhost")
        try:
            response = client.put("/api/schedule/calendar", json={
                "semester": "2026年秋季学期",
                "special_dates": [],
            })
        finally:
            client.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["calendar"]["start_date"], "2026-08-31")
        self.assertEqual(response.json()["calendar"]["total_weeks"], 20)


class CurrentSemesterTest(unittest.TestCase):
    def test_semester_mapping_by_month(self):
        from server.services.schedule_service import current_semester

        self.assertEqual(current_semester(datetime(2026, 2, 1)), "2026年春季学期")
        self.assertEqual(current_semester(datetime(2026, 3, 1)), "2026年春季学期")
        self.assertEqual(current_semester(datetime(2026, 6, 30)), "2026年春季学期")
        self.assertEqual(current_semester(datetime(2026, 7, 15)), "2026年夏季学期")
        self.assertEqual(current_semester(datetime(2026, 8, 31)), "2026年夏季学期")
        self.assertEqual(current_semester(datetime(2026, 9, 1)), "2026年秋季学期")
        self.assertEqual(current_semester(datetime(2026, 12, 31)), "2026年秋季学期")
        # 秋季学期跨年：1 月仍属于上一年秋季
        self.assertEqual(current_semester(datetime(2027, 1, 5)), "2026年秋季学期")

    def test_get_my_schedule_defaults_to_current_semester(self):
        from main import _make_get_my_schedule
        from server.services import schedule_service as svc

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ScheduleService(Path(temp_dir) / "schedule.db")
            service.replace("u1", "2026年春季学期", [{"name": "春季课", "meetings": []}])
            service.replace("u1", "2026年秋季学期", [{"name": "秋季课", "meetings": []}])
            tool = _make_get_my_schedule("u1")
            with patch.object(svc, "get_schedule_service", return_value=service), patch(
                "main.datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 9, 4)
                result = tool.invoke({"semester": ""})
            self.assertIn("秋季课", result)
            self.assertNotIn("春季课", result)

    def test_get_my_schedule_reports_missing_current_semester(self):
        from main import _make_get_my_schedule
        from server.services import schedule_service as svc

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ScheduleService(Path(temp_dir) / "schedule.db")
            service.replace("u1", "2026年春季学期", [{"name": "春季课", "meetings": []}])
            tool = _make_get_my_schedule("u1")
            with patch.object(svc, "get_schedule_service", return_value=service), patch(
                "main.datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 9, 4)
                result = tool.invoke({"semester": ""})
            self.assertIn("尚未导入", result)
            self.assertIn("2026年春季学期", result)
            self.assertNotIn("春季课", result)

    def test_get_my_schedule_filters_current_calendar_week(self):
        from main import _make_get_my_schedule
        from server.services import schedule_service as svc

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ScheduleService(Path(temp_dir) / "schedule.db")
            service.replace("u1", "2026年秋季学期", [
                {"name": "第一周课程", "meetings": [{"weekday": 1, "sections": [1, 2], "weeks": [1]}]},
                {"name": "第二周课程", "meetings": [{"weekday": 1, "sections": [1, 2], "weeks": [2]}]},
            ])
            service.save_calendar("u1", "2026年秋季学期", date(2026, 8, 31), 18, [])
            tool = _make_get_my_schedule("u1")
            with patch.object(svc, "get_schedule_service", return_value=service), patch(
                "main.datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(2026, 9, 9)
                result = tool.invoke({"semester": "", "week": 0})
            self.assertIn("第2周", result)
            self.assertIn("第二周课程", result)
            self.assertNotIn("第一周课程", result)


class AcademicCalendarImportTest(unittest.TestCase):
    @staticmethod
    def sample() -> bytes:
        from datetime import timedelta

        events = []
        for week in range(1, 21):
            start = date(2026, 8, 30) + timedelta(weeks=week - 1)
            end = start + timedelta(days=7)
            events.append(f"BEGIN:VEVENT\nDTSTART;VALUE=DATE:{start:%Y%m%d}\nDTEND;VALUE=DATE:{end:%Y%m%d}\nSUMMARY:秋季学期第{week}周\nEND:VEVENT")
        events.append("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20261001\nDTEND;VALUE=DATE:20261008\nSUMMARY:休(国庆节)\nEND:VEVENT")
        events.append("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260920\nSUMMARY:补周五课程\nEND:VEVENT")
        events.append("BEGIN:VEVENT\nDTSTART;VALUE=DATE:20260920\nSUMMARY:校\n 庆\nEND:VEVENT")
        return ("BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(reversed(events)) + "\nEND:VCALENDAR").encode()

    def test_ics_dates_folding_and_exclusive_end(self):
        from server.services.academic_calendar import parse_academic_calendar_ics

        result = parse_academic_calendar_ics("download.ics", self.sample(), "2026年秋季学期")[0]
        self.assertEqual(result["start_date"], date(2026, 8, 31))
        self.assertEqual(result["total_weeks"], 20)
        days = {item["date"]: item for item in result["special_dates"]}
        self.assertIn("2026-10-07", days)
        self.assertNotIn("2026-10-08", days)
        self.assertEqual(days["2026-09-20"]["course_weekday"], 5)
        self.assertIn("校庆", days["2026-09-20"]["label"])

    def test_ics_rejects_missing_weeks_wrong_semester_and_pdf(self):
        from server.services.academic_calendar import parse_academic_calendar_ics, AcademicCalendarParseError

        for filename, data, semester in [
            ("calendar.pdf", self.sample(), "2026年秋季学期"),
            ("calendar.ics", b"not a calendar", "2026年秋季学期"),
            ("calendar.ics", self.sample(), "2025年秋季学期"),
            ("calendar.ics", self.sample().replace("秋季学期第2周".encode(), b"unrecognized"), "2026年秋季学期"),
            ("calendar.ics", self.sample().replace(b"SUMMARY:", b"RRULE:FREQ=YEARLY\nSUMMARY:", 1), "2026年秋季学期"),
        ]:
            with self.subTest(filename=filename, semester=semester):
                with self.assertRaises(AcademicCalendarParseError):
                    parse_academic_calendar_ics(filename, data, semester)

    def test_upload_and_duplicate_preserves_corrections(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        with tempfile.TemporaryDirectory() as folder:
            service = ScheduleService(Path(folder) / "schedule.db")
            app = create_app()
            app.dependency_overrides[get_schedule_service] = lambda: service
            client = TestClient(app, base_url="http://localhost", raise_server_exceptions=True)
            try:
                payload = {"semester": "2026年秋季学期"}
                files = {"file": ("arbitrary-name.ics", self.sample(), "text/calendar")}
                first = client.post("/api/schedule/calendar/import-ics", data=payload, files=files)
                self.assertEqual(first.status_code, 200)
                self.assertFalse(first.json()["already_exists"])
                service.save_calendar("local_user", payload["semester"], date(2026, 8, 31), 19, [])
                again = client.post("/api/schedule/calendar/import-ics", data=payload, files=files)
                self.assertTrue(again.json()["already_exists"])
                self.assertEqual(again.json()["calendars"][0]["total_weeks"], 19)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
