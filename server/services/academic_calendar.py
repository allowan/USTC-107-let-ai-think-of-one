"""解析用户上传的 iCalendar 教学日历。"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta


class AcademicCalendarParseError(ValueError):
    """校历文件无法可靠解析。"""


def _week_number(value: str) -> int:
    if not re.fullmatch(r"(?:[0-9]{1,2}|[一二三四五六七八九]|[一二三]?十[一二三四五六七八九]?)", value):
        raise AcademicCalendarParseError("教学周编号无效")
    if value.isdigit():
        return int(value)
    digits = "零一二三四五六七八九"
    if "十" in value:
        tens, units = value.split("十")
        return (digits.index(tens) if tens else 1) * 10 + (digits.index(units) if units else 0)
    return digits.index(value)


def parse_academic_calendar_ics(filename: str, data: bytes, semester: str) -> list[dict]:
    """读取全天、非重复教学周事件，只导入所选学期，不访问外部链接。"""

    if not filename.lower().endswith((".ics", ".ical")):
        raise AcademicCalendarParseError("请选择 iCalendar 文件（.ics 或 .ical）")
    if not data or len(data) > 10 * 1024 * 1024:
        raise AcademicCalendarParseError("校历文件为空或超过 10 MB")
    target = re.fullmatch(r"(20\d{2})年([春夏秋])季学期", semester)
    if target is None:
        raise AcademicCalendarParseError("请选择规范学期名称，例如 2026年秋季学期")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AcademicCalendarParseError("iCalendar 文件必须使用 UTF-8 编码") from exc
    text = re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").strip()
    if not text.startswith("BEGIN:VCALENDAR\n") or not text.endswith("END:VCALENDAR"):
        raise AcademicCalendarParseError("文件缺少完整的 VCALENDAR 结构")
    events = []
    current = None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise AcademicCalendarParseError("事件结构嵌套错误")
            current = {}
        elif line == "END:VEVENT":
            if current is None:
                raise AcademicCalendarParseError("事件结构不完整")
            events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            name = key.split(";")[0].upper()
            if name in {"SUMMARY", "DTSTART", "DTEND", "STATUS", "RRULE", "RDATE", "EXDATE", "RECURRENCE-ID", "DURATION"}:
                if name in current:
                    raise AcademicCalendarParseError("事件包含重复关键字段")
                current[name] = value
    if current is not None or not events:
        raise AcademicCalendarParseError("文件没有完整的日历事件")
    parsed = []
    for event in events:
        if event.get("STATUS") == "CANCELLED":
            continue
        if any(key in event for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID", "DURATION")):
            raise AcademicCalendarParseError("暂不支持重复规则或持续时间事件，请导出已展开且带结束日期的事件")
        raw_start = event.get("DTSTART", "")
        raw_end = event.get("DTEND", raw_start)
        if not re.fullmatch(r"\d{8}", raw_start) or not re.fullmatch(r"\d{8}", raw_end):
            raise AcademicCalendarParseError("教学日历目前仅支持全天日期事件，不支持带时区的定时事件")
        try:
            start = date.fromisoformat(raw_start)
            end = date.fromisoformat(raw_end) if "DTEND" in event else start + timedelta(days=1)
        except ValueError as exc:
            raise AcademicCalendarParseError("事件日期无效") from exc
        if end <= start or (end - start).days > 366:
            raise AcademicCalendarParseError("事件结束日期必须晚于开始日期，且跨度不能超过一年")
        summary = unicodedata.normalize("NFKC", event.get("SUMMARY", ""))
        summary = re.sub(r"\\([nN,;\\])", lambda m: " " if m[1] in "nN" else m[1], summary).strip()
        parsed.append((start, end, summary))
    groups = {}
    for start, end, summary in parsed:
        match = re.fullmatch(r"([春夏秋])季学期第([一二三四五六七八九十零\d]+)(?:教学)?周", summary)
        if match is None:
            continue
        week = _week_number(match[2])
        if not 1 <= week <= 30 or (end - start).days != 7 or start.weekday() not in (0, 6):
            raise AcademicCalendarParseError("教学周必须为周日或周一开始的连续七天")
        monday = start + timedelta(days=1 if start.weekday() == 6 else 0)
        first = monday - timedelta(weeks=week - 1)
        name = f"{first.year}年{match[1]}季学期"
        if name != semester:
            continue
        groups.setdefault(first, set()).add(week)
    if len(groups) != 1:
        raise AcademicCalendarParseError(f"未找到唯一的{semester}教学周，请检查文件是否包含带学期名称的教学周事件")
    first, weeks = next(iter(groups.items()))
    if weeks != set(range(1, max(weeks) + 1)):
        raise AcademicCalendarParseError("所选学期教学周不连续，无法确定完整校历")
    last = first + timedelta(weeks=max(weeks))
    special = {}
    for start, end, summary in parsed:
        if not summary or re.fullmatch(r".*第[一二三四五六七八九十零\d]+(?:教学)?周", summary):
            continue
        makeup = re.search(r"补(?:周|星期)([一二三四五六日天])课", summary)
        kind = "makeup" if makeup else "holiday" if re.match(r"\*?休(?:$|[ (])", summary) or "停课" in summary else "note"
        weekday = "一二三四五六日".index(makeup[1].replace("天", "日")) + 1 if makeup else None
        for offset in range(max(0, (min(end, last) - max(start, first)).days)):
            day = (max(start, first) + timedelta(days=offset)).isoformat()
            item = special.setdefault(day, {"date": day, "kind": "note", "label": "", "course_weekday": None})
            if item["kind"] != "note" and kind != "note" and (item["kind"], item["course_weekday"]) != (kind, weekday):
                raise AcademicCalendarParseError(f"{day} 同时存在互相冲突的停课或补课安排")
            if kind != "note":
                item.update(kind=kind, course_weekday=weekday)
            if summary not in item["label"].split("；"):
                item["label"] = "；".join(filter(None, [item["label"], summary]))
    if len(special) > 100 or any(len(item["label"]) > 100 for item in special.values()):
        raise AcademicCalendarParseError("特殊日期数量或提醒文字超出限制")
    return [{"semester": semester, "start_date": first, "total_weeks": max(weeks),
             "special_dates": sorted(special.values(), key=lambda item: item["date"]),
             "warnings": ["已按所选学期导入，请核对学校最新调课通知"]}]
