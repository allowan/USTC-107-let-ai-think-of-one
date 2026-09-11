"""Parse the authenticated USTC JW course-table page.

The USTC unified-auth documentation describes authentication endpoints, but it
does not expose a personal course-table API. The student course table is
therefore imported from the runtime DOM of ``jw.ustc.edu.cn/for-std/course-table``
copied by the user, or from HTML/JSON the user explicitly provides. This keeps
the local app from handling passwords or browser cookies while still parsing
the real EAMS page.
"""

from __future__ import annotations

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Iterable

from server.services.schedule_service import SECTION_TIME_RANGES


MAX_IMPORT_SIZE = 5_000_000
logger = logging.getLogger(__name__)
_SEMESTER_RE = re.compile(r"\d{4}年(?:春|夏|秋|冬)季学期")
_WEEK_PART = r"\d+\s*(?:[~～—-]\s*\d+)?\s*(?:[(（][单双][)）])?"
_WEEK_TOKEN_RE = re.compile(rf"(?:{_WEEK_PART}(?:\s*[,，、]\s*{_WEEK_PART})*|[单双全])\s*周")
_SCHEDULE_BODY_RE = re.compile(
    r"^(?P<location>.*?)\s*[:：]\s*(?P<weekday>[^\s(]+)\s*"
    r"\((?P<sections>[^)]*)\)\s*(?P<teacher>.*)$",
    re.DOTALL,
)


class UstcScheduleParseError(ValueError):
    """Raised when an exported USTC course-table page cannot be recognized."""


class _Node:
    def __init__(self, tag: str, attrs: list[tuple[str, str | None]] | None = None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children: list[_Node | str] = []

    def iter(self, tag: str | None = None) -> Iterable["_Node"]:
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.iter(tag)

    def direct_elements(self, *tags: str) -> list["_Node"]:
        wanted = set(tags)
        return [
            child
            for child in self.children
            if isinstance(child, _Node) and child.tag in wanted
        ]

    def text(self) -> str:
        if self.tag in {"script", "style"}:
            return ""
        if self.tag == "br":
            return "\n"
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), attrs)
        self._stack[-1].children.append(node)
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(_Node(tag.lower(), attrs))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _clean_text(value: str) -> str:
    value = value.replace("\xa0", " ").replace("\r", "")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n\s*", "\n", value)
    return value.strip()


def _find_lessons_table(root: _Node) -> _Node | None:
    for table in root.iter("table"):
        if table.attrs.get("id") == "lessons":
            return table
    for table in root.iter("table"):
        header_rows = [row for row in table.iter("tr") if row.direct_elements("th")]
        if not header_rows:
            continue
        headers = {_clean_text(cell.text()) for cell in header_rows[0].direct_elements("th")}
        if {"课堂号", "课程名称", "日期时间地点人员"}.issubset(headers):
            return table
    return None


def _find_timetable(root: _Node) -> _Node | None:
    for table in root.iter("table"):
        classes = set((table.attrs.get("class") or "").split())
        if "timetable" in classes:
            return table
    return None


def _parse_number(value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _parse_teachers(value: str) -> list[str]:
    result: list[str] = []
    for item in re.split(r"[,，、;；]", value):
        item = re.sub(r"\s*[(（].*?[)）]", "", item).strip()
        if item and item not in result:
            result.append(item)
    return result


def _parse_week_values(value: str) -> list[int]:
    value = value.replace("周", "").replace(" ", "")
    if value in {"单", "双"}:
        raise UstcScheduleParseError("单双周缺少起止周数，请提供完整的教务课表明细")
    if not value or value == "全":
        return []
    if not re.fullmatch(rf"{_WEEK_PART}(?:[,，、]{_WEEK_PART})*", value):
        raise UstcScheduleParseError("课表周次包含非法字符")
    weeks: list[int] = []
    for part in re.split(r"[,，、]", value):
        numbers = [int(number) for number in re.findall(r"\d+", part)]
        if len(numbers) >= 2 and re.search(r"[~～—-]", part):
            start, end = numbers[0], numbers[1]
            if start <= end:
                values = list(range(start, end + 1))
            else:
                raise UstcScheduleParseError("课表周次范围不能倒序")
        else:
            values = numbers
        weeks.extend(number for number in values if
                     ("单" not in part or number % 2 == 1) and
                     ("双" not in part or number % 2 == 0))
    if not weeks or min(weeks) < 1:
        raise UstcScheduleParseError("课表周次范围无效")
    return sorted(set(weeks))


def _parse_sections(value: str) -> list[int]:
    if ":" in value or "：" in value:
        return []
    value = value.strip()
    if not value:
        return []
    if not re.fullmatch(r"[0-9]+(?:\s*[,，、~～—-]\s*[0-9]+)*", value):
        raise UstcScheduleParseError("节次包含非法字符，必须填写1–13的整数")
    # 保留输入顺序和重复项，让统一校验报告倒序或重复节次。
    return [int(number) for number in re.findall(r"[0-9]+", value)]


def _parse_schedule_entries(raw: str) -> list[dict[str, Any]]:
    raw = _clean_text(raw)
    matches = list(_WEEK_TOKEN_RE.finditer(raw))
    meetings: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        if match.start() and re.match(r"[0-9A-Za-z.+~～—,，、-]", raw[match.start() - 1]):
            raise UstcScheduleParseError("课表周次包含非法字符")
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = raw[match.end():body_end].strip(" \t\n")
        parsed = _SCHEDULE_BODY_RE.match(body)
        if not parsed:
            raise UstcScheduleParseError("无法识别日期时间地点安排，请核对原课表")
        sections = _parse_sections(parsed.group("sections"))
        time_range = re.fullmatch(
            r"\s*([0-2]?\d[:：][0-5]\d)\s*[~～—-]\s*([0-2]?\d[:：][0-5]\d)\s*",
            parsed.group("sections"),
        )
        start_time = end_time = None
        if time_range:
            start_time, end_time = (value.replace("：", ":").zfill(5) for value in time_range.groups())
            if not (start_time < end_time < "24:00"):
                raise UstcScheduleParseError("课表上课时间范围无效")
        weekday_text = parsed.group("weekday")
        if not re.fullmatch(r"[1-7]", weekday_text):
            raise UstcScheduleParseError("星期必须是1–7的整数")
        weekday = int(weekday_text)
        if (":" in parsed.group("sections") or "：" in parsed.group("sections")) and not time_range:
            raise UstcScheduleParseError("课表钟点时间格式无效")
        meetings.append(
            {
                "weekday": weekday,
                "sections": sections,
                "weeks": _parse_week_values(match.group(0)),
                "location": _clean_text(parsed.group("location")),
                "start_time": start_time,
                "end_time": end_time,
            }
        )

    # Some exports omit the line break between the schedule text and its
    # teacher.  The entry regex above still handles those; this fallback keeps
    # older EAMS variants useful when their week token is not followed by a
    # normal body boundary.
    if not meetings:
        fallback = re.search(
            r"(?P<weeks>[^\s]+周)\s*(?P<location>.*?)\s*[:：]\s*"
            r"(?P<weekday>[1-7])\s*\((?P<sections>[^)]*)\)",
            raw,
        )
        if fallback:
            sections = _parse_sections(fallback.group("sections"))
            if sections:
                meetings.append(
                    {
                        "weekday": int(fallback.group("weekday")),
                        "sections": sections,
                        "weeks": _parse_week_values(fallback.group("weeks")),
                        "location": _clean_text(fallback.group("location")),
                        "start_time": None,
                        "end_time": None,
                    }
                )

    if not meetings and "周" in raw and "(" in raw:
        raise UstcScheduleParseError("无法识别日期时间地点安排，请核对原课表")
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for meeting in meetings:
        key = (
            meeting["weekday"],
            tuple(meeting["sections"]),
            tuple(meeting["weeks"]),
            meeting["location"],
            meeting["start_time"],
            meeting["end_time"],
        )
        if key not in seen:
            seen.add(key)
            unique.append(meeting)
    return unique


def parse_schedule_entries(raw: str) -> list[dict[str, Any]]:
    """解析一段教务课表安排，供存储层校正历史记录使用。"""
    try:
        return _parse_schedule_entries(raw)
    except UstcScheduleParseError:
        # 旧记录可能包含已不允许导入的错误；读取仍保留它们供界面核对。
        logger.warning("历史课表安排无法重新解析，保留已存储记录")
        return []


def _section_times(root: _Node) -> dict[int, tuple[str, str]]:
    timetable = _find_timetable(root)
    result: dict[int, tuple[str, str]] = {}
    if timetable is None:
        return result
    for node in timetable.iter("th"):
        classes = set((node.attrs.get("class") or "").split())
        if "span" not in classes:
            continue
        section_match = re.search(r"\d+", _clean_text(node.text()))
        start = node.attrs.get("data-start")
        end = node.attrs.get("data-end")
        if section_match and start and end:
            result[int(section_match.group(0))] = (start, end)
    return result


def _fill_meeting_times(meetings: list[dict[str, Any]], section_times: dict[int, tuple[str, str]]) -> None:
    for meeting in meetings:
        sections = meeting.get("sections") or []
        if not sections:
            continue
        first = section_times.get(min(sections))
        last = section_times.get(max(sections))
        if first:
            meeting["start_time"] = meeting.get("start_time") or first[0]
        if last:
            meeting["end_time"] = meeting.get("end_time") or last[1]
        if not meeting.get("start_time") or not meeting.get("end_time"):
            fallback = SECTION_TIME_RANGES.get((min(sections), max(sections)))
            if fallback:
                meeting["start_time"] = meeting.get("start_time") or fallback[0]
                meeting["end_time"] = meeting.get("end_time") or fallback[1]


def _normalise_course(course: Any) -> dict[str, Any]:
    if not isinstance(course, dict):
        raise UstcScheduleParseError("课程数据格式错误")
    name = str(course.get("name") or course.get("course_name") or "").strip()
    # 保留原始安排值，统一由写入前校验报告问题，不能将错误值静默丢弃。
    meetings = course.get("meetings", [])
    credits = course.get("credits")
    if credits is not None:
        try:
            credits = float(credits)
        except (TypeError, ValueError):
            credits = None
    return {
        "course_code": str(course.get("course_code") or "").strip(),
        "name": name,
        "teachers": _parse_teachers(",".join(str(value) for value in course.get("teachers", []) if value))
        if isinstance(course.get("teachers"), list)
        else _parse_teachers(str(course.get("teachers") or "")),
        "credits": credits,
        "raw_schedule": str(course.get("raw_schedule") or "").strip(),
        "meetings": meetings,
    }


def _parse_structured_json(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("courses"), list):
        raise UstcScheduleParseError("JSON 需要包含 courses 数组")
    courses = [_normalise_course(course) for course in payload["courses"]]
    if not courses:
        raise UstcScheduleParseError("JSON 中没有课程")
    semester = payload.get("semester", "导入课表")
    return {"semester": semester, "courses": courses}


def _parse_html(content: str, filename: str = "") -> dict[str, Any]:
    parser = _DocumentParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:  # HTMLParser is permissive, but expose a stable error.
        logger.warning("课表 HTML 解析失败：%s", type(exc).__name__)
        raise UstcScheduleParseError(f"课表 HTML 解析失败: {exc}") from exc

    lessons_table = _find_lessons_table(parser.root)
    if lessons_table is None:
        raise UstcScheduleParseError(
            "未找到 USTC 课表明细表，请粘贴教务系统加载完成后的运行时 HTML，或导入结构化 JSON"
        )
    header_row = next((row for row in lessons_table.iter("tr") if row.direct_elements("th")), None)
    if header_row is None:
        raise UstcScheduleParseError("课表明细表缺少表头")
    headers = [_clean_text(cell.text()) for cell in header_row.direct_elements("th")]
    header_index = {header: index for index, header in enumerate(headers)}

    required = {"课堂号", "课程名称", "授课教师", "日期时间地点人员"}
    if not required.issubset(header_index):
        raise UstcScheduleParseError("课表明细表字段不完整")

    section_times = _section_times(parser.root)
    courses: list[dict[str, Any]] = []
    for row in lessons_table.iter("tr"):
        cells = row.direct_elements("td")
        if not cells:
            continue
        values = [_clean_text(cell.text()) for cell in cells]
        if len(values) <= max(header_index.values()):
            continue
        course_code = values[header_index["课堂号"]]
        name = values[header_index["课程名称"]]
        raw_schedule = values[header_index["日期时间地点人员"]]
        try:
            meetings = _parse_schedule_entries(raw_schedule)
        except UstcScheduleParseError as exc:
            logger.warning("课表课程安排解析失败")
            raise UstcScheduleParseError(f"第{len(courses) + 1}门课程（{name}）：{exc}") from exc
        _fill_meeting_times(meetings, section_times)
        courses.append(
            {
                "course_code": course_code,
                "name": name,
                "teachers": _parse_teachers(values[header_index["授课教师"]]),
                "credits": _parse_number(values[header_index.get("学分", -1)]) if "学分" in header_index else None,
                "raw_schedule": raw_schedule,
                "meetings": meetings,
            }
        )

    if not courses:
        raise UstcScheduleParseError("课表明细表中没有课程")

    semester_match = _SEMESTER_RE.search(_clean_text(parser.root.text())) or _SEMESTER_RE.search(content)
    semester = semester_match.group(0) if semester_match else "导入课表"
    if semester == "导入课表" and filename:
        filename_match = re.search(r"\d{4}年(?:春|夏|秋|冬)季学期", filename)
        if filename_match:
            semester = filename_match.group(0)
    return {"semester": semester, "courses": courses}


def parse_ustc_schedule(content: str, filename: str = "") -> dict[str, Any]:
    """Parse a USTC course-table HTML export or the app's structured JSON."""

    if not isinstance(content, str) or not content.strip():
        raise UstcScheduleParseError("课表内容不能为空")
    if len(content) > MAX_IMPORT_SIZE:
        raise UstcScheduleParseError("课表文件过大，最多支持 5 MB")
    stripped = content.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{") or stripped.startswith("[") or filename.lower().endswith(".json"):
        structured = _parse_structured_json(stripped)
        if structured is not None:
            return structured
    return _parse_html(content, filename)


def format_schedule_for_personal_data(payload: dict[str, Any]) -> str:
    """Render structured courses into searchable plain text for the personal RAG index."""

    lines = [f"课表学期：{payload['semester']}"]
    weekday_names = ["", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    for course in payload["courses"]:
        credits = f"，{course['credits']} 学分" if course.get("credits") is not None else ""
        teachers = "、".join(course.get("teachers") or []) or "教师待定"
        code = f"{course.get('course_code')} " if course.get("course_code") else ""
        lines.append(f"- {code}{course['name']}{credits}；教师：{teachers}")
        for meeting in course.get("meetings") or []:
            weekday = weekday_names[meeting["weekday"]] if meeting.get("weekday") in range(1, 8) else "星期待定"
            sections = meeting.get("sections") or []
            section_text = f"第{min(sections)}-{max(sections)}节" if sections else "节次待定"
            weeks = meeting.get("weeks") or []
            week_text = f"第{min(weeks)}-{max(weeks)}周" if weeks else "周次见原课表"
            time_text = ""
            if meeting.get("start_time") and meeting.get("end_time"):
                time_text = f" {meeting['start_time']}-{meeting['end_time']}"
            location = meeting.get("location") or "地点待定"
            lines.append(f"  - {weekday} {section_text}{time_text}，{week_text}，{location}")
    return "\n".join(lines)


def schedule_data_to_payload(schedule_data: dict[str, Any]) -> dict[str, Any]:
    """Convert rows already stored in ``schedule.db`` to the formatter shape."""

    courses_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    courses: list[dict[str, Any]] = []
    for row in schedule_data.get("courses") or []:
        key = (str(row.get("course_code") or ""), str(row.get("name") or ""))
        course = courses_by_key.get(key)
        if course is None:
            course = {
                "course_code": key[0],
                "name": key[1],
                "teachers": list(row.get("teachers") or []),
                "credits": row.get("credits"),
                "raw_schedule": str(row.get("raw_schedule") or ""),
                "meetings": [],
            }
            courses_by_key[key] = course
            courses.append(course)

        start_section = row.get("start_section")
        end_section = row.get("end_section") or start_section
        sections = []
        if start_section is not None and end_section is not None:
            sections = list(range(int(start_section), int(end_section) + 1))
        course["meetings"].append(
            {
                "weekday": row.get("weekday"),
                "sections": sections,
                "weeks": list(row.get("weeks") or []),
                "location": str(row.get("location") or ""),
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
            }
        )

    return {
        "semester": str(schedule_data.get("semester") or "导入课表"),
        "courses": courses,
    }


__all__ = [
    "MAX_IMPORT_SIZE",
    "UstcScheduleParseError",
    "format_schedule_for_personal_data",
    "parse_ustc_schedule",
    "schedule_data_to_payload",
]
