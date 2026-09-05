import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from server.services.schedule_service import ScheduleService


class ScheduleServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = ScheduleService(Path(self.temp_dir.name) / "schedule.db")

    def tearDown(self):
        self.temp_dir.cleanup()

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
        client = TestClient(app)
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


if __name__ == "__main__":
    unittest.main()
