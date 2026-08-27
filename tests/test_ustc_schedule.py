import tempfile
import unittest
from pathlib import Path

from server.services.schedule_service import ScheduleService
from server.services.ustc_schedule import parse_ustc_schedule


USTC_COURSE_TABLE_HTML = """
<html><body>
  <div>2026年秋季学期</div>
  <table id="lessons">
    <thead><tr>
      <th>序号</th><th>课堂号</th><th>课程名称</th><th>课程范畴</th>
      <th>课程范畴分类</th><th>学分</th><th>教学班名称</th><th>课程类型</th>
      <th>开课单位</th><th>授课教师</th><th>日期时间地点人员</th>
      <th>已排学时</th><th>已选学生数</th><th>课堂介绍</th>
    </tr></thead>
    <tbody><tr>
      <td>1</td><td>210716.01</td><td>深度学习实践</td><td>本科计划内课程</td>
      <td></td><td>2</td><td>网络空间安全</td><td>理论实验课</td>
      <td>信息科学技术学院</td><td>李志慧(主讲),王敬(主讲)</td>
      <td><span>1~10周 GT-B111 :5(8,9) 王敬<br>1~10周 GT-B111 :5(8,9) 李志慧</span></td>
      <td>20</td><td>44</td><td>查看</td>
    </tr></tbody>
  </table>
  <table class="timetable">
    <tbody>
      <tr class="8"><th class="span" data-start="15:55" data-end="16:40">8</th></tr>
      <tr class="9"><th class="span" data-start="16:45" data-end="17:30">9</th></tr>
    </tbody>
  </table>
</body></html>
"""


class UstcScheduleParserTest(unittest.TestCase):
    def test_parse_real_eams_lessons_and_timetable_shape(self):
        payload = parse_ustc_schedule(USTC_COURSE_TABLE_HTML, "course-table.html")

        self.assertEqual(payload["semester"], "2026年秋季学期")
        self.assertEqual(len(payload["courses"]), 1)
        course = payload["courses"][0]
        self.assertEqual(course["course_code"], "210716.01")
        self.assertEqual(course["teachers"], ["李志慧", "王敬"])
        self.assertEqual(course["credits"], 2.0)
        self.assertEqual(len(course["meetings"]), 1)
        meeting = course["meetings"][0]
        self.assertEqual(meeting["weekday"], 5)
        self.assertEqual(meeting["sections"], [8, 9])
        self.assertEqual(meeting["weeks"], list(range(1, 11)))
        self.assertEqual(meeting["location"], "GT-B111")
        self.assertEqual(meeting["start_time"], "15:55")
        self.assertEqual(meeting["end_time"], "17:30")

    def test_parse_structured_json(self):
        payload = parse_ustc_schedule(
            '{"semester":"春季","courses":[{"name":"课程A","meetings":[{"weekday":1,"sections":[1],"weeks":[1]}]}]}',
            "schedule.json",
        )
        self.assertEqual(payload["semester"], "春季")
        self.assertEqual(payload["courses"][0]["name"], "课程A")

    def test_schedule_import_api_updates_database(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.schedule_service import get_schedule_service

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ScheduleService(Path(temp_dir) / "schedule.db")
            app = create_app()
            app.dependency_overrides[get_schedule_service] = lambda: service
            client = TestClient(app)
            try:
                response = client.post(
                    "/api/schedule/import-ustc",
                    json={"content": USTC_COURSE_TABLE_HTML, "filename": "course-table.html"},
                )
            finally:
                client.close()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["course_count"], 1)
            self.assertEqual(response.json()["meeting_count"], 1)
            stored = service.list("local_user", "2026年秋季学期")["courses"]
            self.assertEqual(stored[0]["location"], "GT-B111")

    def test_personal_data_shortcut_copies_existing_schedule_to_rag(self):
        from fastapi.testclient import TestClient
        from server import create_app
        from server.services.rag_service import get_rag_service
        from server.services.schedule_service import get_schedule_service

        class FakeRag:
            def __init__(self):
                self.updated = []

            def update_user_data(self, username, source, content):
                self.updated.append((username, source, content))

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ScheduleService(Path(temp_dir) / "schedule.db")
            rag = FakeRag()
            service.replace(
                "local_user",
                "2026年秋季学期",
                [
                    {
                        "course_code": "210716.01",
                        "name": "深度学习实践",
                        "teachers": ["李志慧", "王敬"],
                        "credits": 2,
                        "raw_schedule": "1~10周 GT-B111 :5(8,9)",
                        "meetings": [
                            {
                                "weekday": 5,
                                "sections": [8, 9],
                                "weeks": list(range(1, 11)),
                                "location": "GT-B111",
                                "start_time": "15:55",
                                "end_time": "17:30",
                            }
                        ],
                    }
                ],
            )
            app = create_app()
            app.dependency_overrides[get_schedule_service] = lambda: service
            app.dependency_overrides[get_rag_service] = lambda: rag
            client = TestClient(app)
            try:
                response = client.post(
                    "/api/personal-data/import-schedule",
                    json={"semester": "2026年秋季学期"},
                )
                empty_body_response = client.post("/api/personal-data/import-schedule")
            finally:
                client.close()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(empty_body_response.status_code, 200)
            self.assertEqual(response.json()["source"], "课表-2026年秋季学期")
            self.assertEqual(response.json()["course_count"], 1)
            self.assertEqual(response.json()["meeting_count"], 1)
            self.assertEqual(len(rag.updated), 2)
            self.assertIn("深度学习实践", rag.updated[0][2])
            self.assertEqual(
                service.list("local_user", "2026年秋季学期")["courses"][0]["name"],
                "深度学习实践",
            )


if __name__ == "__main__":
    unittest.main()
