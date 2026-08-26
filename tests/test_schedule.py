import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
