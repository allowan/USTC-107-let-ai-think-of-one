"""校园通知的结构化事件抽取与时间索引。

第一性原理：Agent 之所以无法回答"最近有什么要截止的报名"，是因为截止时间
以自由文本形式埋在 RAG 分块里，检索按语义相似度排序而非按时间排序，且 LLM
无法对"今天/未来 N 天"做确定性日期运算。本模块把通知里的关键时间字段抽取
成结构化记录存入 SQLite，使"未来 N 天内截止的事件"成为一个确定性的数据库
查询（日期运算在代码里完成，不交给 LLM）。

抽取采用确定性正则而非 LLM：
- 离线可用（不依赖嵌入/LLM 网关，测试与无网环境都能跑）
- 非阻塞（毫秒级，可安全挂在入库路径与进程启动路径上）
- 可复现（同样输入永远同样输出，便于守护测试）
代价是无法解析"开学三周内"这类相对表述，这类通知 deadline 记为 None（仍可按
类别检索），留待后续用 LLM 兜底增强。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("campus_rag.events")

# 锚定项目根绝对路径：与 schedule.db / users.db 一致，相对路径会依赖启动 CWD。
DB_PATH = Path(__file__).resolve().parent.parent / "events.db"

# 日期匹配：中文 [YYYY年]M月D日（年可缺省）或数字 YYYY.M.D / YYYY-M-D / YYYY/M/D。
# 中文分支要求"月…日"成对出现，数字分支用 (?<!\d)/(?!\d) 防止在长数字或 URL
# 路径中误匹配（如 "20406.html"、"2026.9-2027.1" 不会被当成日期）。
_DATE_RE = re.compile(
    r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"|(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)"
)

# 动作词 + 时间/日期/截止 的紧邻组合（如“申请时间”“报名截止”“选课时间”）。
# 要求动词与“时间/截止”相邻，既能抓到“助教申请时间：7月13日-9月4日”这类
# 无“截止”二字的报名窗口，又因“紧邻”而不会误中“水上报告厅”（上报+厅）。
_ACTION_TIME_RE = re.compile(
    r"(申请|报名|提交|上报|报送|上传|填报|缴纳|交费|录入|扫码|扫描|招募|招新|"
    r"答辩|开题|结题|评审|评选|评奖|选课|退课|补选|重修|考核|材料|系统开放)"
    r"(时间|日期|截止|止|前)"
)

# 截止标记：出现在子句内即认为该子句在描述截止时间。这些词几乎不会作为
# 其他词的子串出现（ unlike “上报”会误中“水上报告厅”），故精度高。
_DEADLINE_MARKERS = (
    "截止", "截至", "受理", "逾期", "前完成", "之前完成",
    "前提交", "之前提交", "前上报", "前报送", "前缴纳", "前上传", "前填报",
)
# 日期后置标记：紧跟在日期之后表示“在该日之前”（如“9月4日前”）。
# lstrip 容忍网页正文在日期与“前”之间插入的空格。
_AFTER_RE = re.compile(r"^(之前|以前|截止|止|前)")
# 日期前置动词：紧邻日期之前表示该动作的时间点（如“报名9月4日”“即日起至10月20日”）。
# 用 $ 锚定“紧邻”，避免子串误中（“水上报告”不会匹配“上报$”）。
_BEFORE_RE = re.compile(
    r"(截止|截至|报名|申报|申请|提交|上报|报送|上传|填报|缴纳|录入|受理|"
    r"答辩|开题|结题|评审|评选|评奖|招募|招新|扫码|扫描|至)$"
)
# 子句切分：按中文句读与换行切分（保留冒号，使“截止时间为：9月8日”同子句）。
_CLAUSE_SPLIT_RE = re.compile(r"[。，、；！？\n\r]+")

# ── 事件发生型抽取（区别于截止型）─────────────────────────────
# “何时发生”标签行：标签与日期可跨行（网页表格转文本后标签与值常分行）。
_EVENT_LABEL_RE = re.compile(
    r"(停水|停电|停气|封闭|施工|展览|开放|试运行|发车|恢复|开展|活动|上课|开课|通车)(时间|日期)"
)
# 子句级事件动词：与日期同子句时表示“何时发生”（如“自8月27日起试运行”）。
_EVENT_VERB_RE = re.compile(r"(试运行|开幕|举行|举办|通车|开赛|开课|恢复供水|恢复通车|启用)")
# 地点标签的两种形态：
# (a) 带冒号同行取值（“展览地点：东区师生活动中心…”）；
# (b) 纯标签行、值在下一非空行（“二、停电范围”后接内容行）。
# 拆成两个正则是为了根治“地址为/地点是 xxx”这类叙述句被冒号可选误当标签。
_LOCATION_LABELED_RE = re.compile(r"^[^：:]{0,10}(地点|地址|范围)[:：]\s*(.+)$")
_LOCATION_BARE_RE = re.compile(r"^[^：:]{0,10}(地点|地址|范围)\s*$")
# 标题回退：标题形如“关于教五楼北侧道路封闭施工的通知”时取事件主体作地点。
# 不含“道路封闭”分支——它会在“道路”处抢先匹配导致 group 丢掉“道路”二字；
# 用“封闭施工”覆盖即可（“道路封闭施工”与“道路施工”同样以“封闭施工/施工”收尾）。
_LOCATION_TITLE_RE = re.compile(r"关于(.{2,20}?)(封闭施工|停水|停电|停气|道路施工)")
# 地点值中的“详见附件”类占位不算真实地点。
_LOCATION_SKIP_PREFIX = ("详见", "见下", "见附", "另行", "待定")

# 类别分类：按 (类别名, 关键词) 顺序匹配，先命中先归类。
# 业务类在前（选课/考试等），通用后勤类（交通/展览/后勤）居中，
# “报名”的关键词（申请/招募等）过于宽泛，放最后兜底。
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("选课", ("选课", "退课", "补选", "重修", "置课")),
    ("考试", ("考试", "缓考", "补考", "期末", "考核")),
    ("答辩", ("答辩", "开题", "中期", "结题")),
    ("评奖", ("评奖", "奖学金", "评优", "表彰", "资助", "评审", "评选")),
    ("竞赛", ("竞赛", "比赛", "大赛", "杯")),
    ("讲座", ("讲座", "报告", "论坛", "讲堂", "宣讲")),
    ("实习", ("实习", "实践")),
    ("助教", ("助教",)),
    ("交通", ("班车", "公交", "出行", "乘车")),
    ("展览", ("艺术展", "作品展", "书画展", "档案展", "展览")),
    ("后勤", ("停水", "停电", "停气", "封闭", "施工", "维修", "停运")),
    ("报名", ("报名", "申报", "申请", "招募", "招新")),
)

_SOURCE_URL_RE = re.compile(r"来源[:：]\s*(https?://\S+)", re.IGNORECASE)
_TITLE_RE = re.compile(r"标题[:：]\s*(.+)")
_AUDIENCE_RE = re.compile(r"^(各|各位|全体|全校|全院)[^：:]{0,20}[：:]")


def _make_date(year: int, month: int, day: int) -> date | None:
    """构造日期，非法组合（如 2 月 30 日）返回 None 而非抛异常。"""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_yearless(
    month: int, day: int, ref_year: int, anchor: date | None, allow_bump: bool
) -> date | None:
    """为无年份的“M月D日”推断年份。

    仅当 allow_bump（即已知发布日）且解析结果早于发布日时，才自增一年
    （处理“12 月发布、次年 1 月截止”）。无发布日时绝不跳年：跳年会把
    一个过去的日期捏造成未来截止（如新闻“6月15日举办了”被推成明年），
    宁可让它落在过去、被 query_upcoming 的 deadline>=today 自然过滤掉。
    """
    d = _make_date(ref_year, month, day) or _make_date(ref_year + 1, month, day)
    if d is None:
        return None
    if allow_bump and anchor is not None and d < anchor:
        nxt = _make_date(ref_year + 1, month, day)
        if nxt is not None:
            return nxt
    return d


def _date_from_match(m: re.Match, ref_year: int, anchor: date | None, allow_bump: bool) -> date | None:
    """把 _DATE_RE 的一个匹配转为 date（中文/数字分支、含年/无年）。"""
    if m.group(2) is not None:  # 中文分支 [YYYY年]M月D日
        year_s, month_s, day_s = m.group(1), m.group(2), m.group(3)
        month, day = int(month_s), int(day_s)
        if year_s:
            return _make_date(int(year_s), month, day)
        return _resolve_yearless(month, day, ref_year, anchor, allow_bump)
    # 数字分支 YYYY.M.D
    return _make_date(int(m.group(4)), int(m.group(5)), int(m.group(6)))


def _iter_dates(line: str, ref_year: int, anchor: date | None, allow_bump: bool = False):
    """产出行内所有可解析日期 (date, has_year)。"""
    for m in _DATE_RE.finditer(line):
        d = _date_from_match(m, ref_year, anchor, allow_bump)
        if d is not None:
            yield d, bool(m.group(1) or m.group(4))


def _clause_deadline(
    clause: str, ref_year: int, anchor: date | None, allow_bump: bool
) -> tuple[date, str] | None:
    """从子句中解析出截止日期（高精度邻近匹配）。

    一个日期被视为截止候选，当且仅当它在本子句内满足下列之一：
      (a) 子句含明确截止标记（截止/截至/受理/逾期/前完成…）；
      (b) 日期紧跟“前/之前/止/截止”（如“9月4日前”）；
      (c) 日期紧接在动作动词之后（如“报名9月4日”）。
    三者都不满足时拒绝（如新闻“6月15日下午…水上报告厅”）。
    子句内有多个日期时取最晚者（“报名 7月13日-9月4日”的截止是结束日）。
    """
    has_marker = any(mk in clause for mk in _DEADLINE_MARKERS) or bool(
        _ACTION_TIME_RE.search(clause)
    )
    dates: list[date] = []
    for m in _DATE_RE.finditer(clause):
        d = _date_from_match(m, ref_year, anchor, allow_bump)
        if d is None:
            continue
        start, end = m.span()
        # 网页正文常在日期与“前”之间插空格（“10 月 10 日 前反馈”），lstrip 后再判
        after = clause[end:end + 3].lstrip()
        before = clause[max(0, start - 4):start]
        if has_marker or _AFTER_RE.match(after) or _BEFORE_RE.search(before):
            dates.append(d)
    if not dates:
        return None
    return max(dates), clause.strip()


def _classify(text: str) -> str:
    for name, keywords in _CATEGORIES:
        if any(kw in text for kw in keywords):
            return name
    return "其他"


def _next_nonempty(lines: list[str], i: int) -> str | None:
    """返回第 i 行之后的首个非空行（最多向下看 2 行），无则 None。"""
    for j in range(i + 1, min(i + 3, len(lines))):
        if lines[j].strip():
            return lines[j]
    return None


def _extract_event_times(
    body_lines: list[str], clauses: list[str],
    ref_year: int, anchor: date, allow_bump: bool,
) -> tuple[date | None, date | None]:
    """抽取事件发生时间（span 或 instant），返回 (start, end)。

    两条路径，标签行优先：
    1. “XX时间/日期”标签行（停水/展览/封闭等发生型动词），日期在本行
       或下一非空行（网页表格转文本后标签与值常跨行）；
    2. 子句内事件动词与日期同现（“自8月27日起试运行”）。
    单日期且紧邻“至/截止”时视为结束日（“即日起至10月20日”）。
    只抽日粒度；月粒度区间（“2026.9-2027.1”）与新闻式时间状语先行
    （“6月15日下午，…”）不在此覆盖，由语义检索兜底。
    """
    dates: list[date] = []
    end_hint = False
    for i, line in enumerate(body_lines):
        if not _EVENT_LABEL_RE.search(line):
            continue
        content = line if _DATE_RE.search(line) else (_next_nonempty(body_lines, i) or "")
        for m in _DATE_RE.finditer(content):
            d = _date_from_match(m, ref_year, anchor, allow_bump)
            if d is None:
                continue
            dates.append(d)
            if _BEFORE_RE.search(content[max(0, m.start() - 4):m.start()]):
                end_hint = True
    if not dates:
        for clause in clauses:
            if not _EVENT_VERB_RE.search(clause):
                continue
            for m in _DATE_RE.finditer(clause):
                d = _date_from_match(m, ref_year, anchor, allow_bump)
                if d is not None:
                    dates.append(d)
    if not dates:
        return None, None
    if len(dates) == 1:
        return (None, dates[0]) if end_hint else (dates[0], None)
    return min(dates), max(dates)


def _extract_location(body_lines: list[str], title: str) -> str | None:
    """抽取地点：优先“XX地点/地址/范围”标签行（值同行或下一行），标题回退兜底。"""
    for i, line in enumerate(body_lines):
        s = line.strip()
        labeled = _LOCATION_LABELED_RE.match(s)
        if labeled:
            value = labeled.group(2).strip()
        elif _LOCATION_BARE_RE.match(s):
            value = (_next_nonempty(body_lines, i) or "").strip()
        else:
            continue
        # 切掉句末说明与分号后的并列项，只留第一段
        value = re.split(r"[。；;]", value)[0].strip(" ，,")
        if not (2 <= len(value) <= 60):
            continue
        if value.startswith(_LOCATION_SKIP_PREFIX):
            continue
        return value
    if title:
        m = _LOCATION_TITLE_RE.search(title)
        if m:
            return m.group(1).strip()
    return None


def parse_notice(text: str, source: str = "", today: date | None = None) -> dict:
    """从单条通知正文抽取结构化事件字段（确定性，无 LLM）。

    返回 dict：title / category / audience / publish_date / deadline /
    deadline_text / event_start / event_end / location / url，
    日期为 ISO 字符串或 None。
    """
    today = today or date.today()
    lines = [ln for ln in (text or "").splitlines()]

    # 标题：优先"标题："行，其次文件名去掉数字 ID 前缀，最后首行非空文本。
    title = ""
    for ln in lines:
        m = _TITLE_RE.match(ln.strip())
        if m:
            title = m.group(1).strip()
            break
    if not title and source:
        title = re.sub(r"^\d+_", "", Path(source).stem)
    if not title:
        title = next((ln.strip() for ln in lines if ln.strip()), "")[:60]

    # 源链接：优先"来源："行。
    url = None
    for ln in lines:
        m = _SOURCE_URL_RE.search(ln)
        if m:
            url = m.group(1).rstrip(".,;)]")
            break

    # 适用对象：首个"各学院："式抬头行。
    audience = ""
    for ln in lines:
        s = ln.strip()
        if _AUDIENCE_RE.match(s):
            audience = s.rstrip("：:")
            break

    # 扫描日期时跳过"来源："行，避免 URL/ID 中的数字被误判为日期。
    body_lines = [ln for ln in lines if not _SOURCE_URL_RE.search(ln)]

    # 发布日期：正文中最后一个带年份的日期（通知通常在落款处写发文日期）。
    publish_date: date | None = None
    for ln in body_lines:
        for d, has_year in _iter_dates(ln, today.year, None):
            if has_year:
                publish_date = d
    # 无年份日期的基准年：发布年 > 正文中任意四位年份 > 今年。
    ref_year = publish_date.year if publish_date else today.year
    if publish_date is None:
        for ln in body_lines:
            m = re.search(r"(20\d{2})", ln)
            if m:
                ref_year = int(m.group(1))
                break
    anchor = publish_date or today
    # 仅在已知发布日时才允许无年份日期跳年（见 _resolve_yearless），避免捏造未来截止。
    allow_bump = publish_date is not None

    # 子句级抽取：把正文按句读切分，只在“关键词与日期同处一个短子句”时
    # 才算截止候选，从根上杜绝“水上报告厅…6月15日”这类跨句子串误命中。
    body_text = "\n".join(body_lines)
    candidates: list[tuple[date, str]] = []
    for clause in _CLAUSE_SPLIT_RE.split(body_text):
        clause = clause.strip()
        if not clause:
            continue
        parsed = _clause_deadline(clause, ref_year, anchor, allow_bump)
        if parsed is not None:
            candidates.append(parsed)

    deadline: date | None = None
    deadline_text: str | None = None
    if candidates:
        # 主截止取“锚点之后最近的一个”（即下一个即将到来的截止）；全部早于
        # 锚点时说明已过期，记为 None（通知仍可被语义检索到）。
        future = [(d, t) for d, t in candidates if d >= anchor]
        if future:
            deadline, deadline_text = min(future, key=lambda x: x[0])

    event_start, event_end = _extract_event_times(
        body_lines, _CLAUSE_SPLIT_RE.split(body_text), ref_year, anchor, allow_bump
    )
    location = _extract_location(body_lines, title)
    category = _classify(f"{title}\n{text[:300] if text else ''}")

    return {
        "title": title,
        "category": category,
        "audience": audience or None,
        "publish_date": publish_date.isoformat() if publish_date else None,
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_text": deadline_text,
        "event_start": event_start.isoformat() if event_start else None,
        "event_end": event_end.isoformat() if event_end else None,
        "location": location,
        "url": url,
    }


# ── SQLite 存储 ────────────────────────────────────────────────────

# 抽取器版本：写入时随记录保存。升级抽取逻辑后递增此值，旧记录因版本
# 不匹配会自动重抽（否则内容哈希未变的新字段永远不会回填）。
EXTRACTOR_VERSION = "regex-v2"


class EventStore:
    """通知事件的结构化存储（每条通知一行，source 为主键，天然幂等）。"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        # closing 必不可少：sqlite3 的 with 只管事务不关连接，未关闭句柄在
        # Windows 上会持续锁住 db 文件（与 schedule_service 同理）。
        with closing(self._connect()) as db, db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS notice_events (
                    source TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    title TEXT,
                    category TEXT,
                    audience TEXT,
                    publish_date TEXT,
                    deadline TEXT,
                    deadline_text TEXT,
                    event_start TEXT,
                    event_end TEXT,
                    location TEXT,
                    url TEXT,
                    extracted_at TEXT NOT NULL,
                    extractor TEXT
                )
                """
            )
            # 旧库迁移：v2 新增 event_start/event_end/location/extractor 四列
            cols = {row[1] for row in db.execute("PRAGMA table_info(notice_events)")}
            for col in ("event_start", "event_end", "location", "extractor"):
                if col not in cols:
                    db.execute(f"ALTER TABLE notice_events ADD COLUMN {col} TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_notice_events_deadline "
                "ON notice_events(deadline)"
            )

    def existing_states(self) -> dict[str, tuple[str, str]]:
        """返回 {source: (source_hash, extractor)}，用于跳过未变化且未换抽取器的通知。"""
        with closing(self._connect()) as db, db:
            rows = db.execute("SELECT source, source_hash, extractor FROM notice_events").fetchall()
        return {r[0]: (r[1], r[2] or "") for r in rows}

    def upsert_events(self, events: list[dict]) -> int:
        """写入/更新事件，返回实际写入条数。source 为主键，重复即覆盖。"""
        if not events:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (
                e["source"], e["source_hash"], e.get("title"), e.get("category"),
                e.get("audience"), e.get("publish_date"), e.get("deadline"),
                e.get("deadline_text"), e.get("event_start"), e.get("event_end"),
                e.get("location"), e.get("url"), now,
                e.get("extractor") or EXTRACTOR_VERSION,
            )
            for e in events
        ]
        with closing(self._connect()) as db, db:
            db.executemany(
                """
                INSERT OR REPLACE INTO notice_events (
                    source, source_hash, title, category, audience,
                    publish_date, deadline, deadline_text, event_start,
                    event_end, location, url, extracted_at, extractor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def delete_by_source(self, source: str) -> int:
        with closing(self._connect()) as db, db:
            cur = db.execute("DELETE FROM notice_events WHERE source = ?", (source,))
            return cur.rowcount

    def clear(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM notice_events")

    def count(self) -> int:
        with closing(self._connect()) as db, db:
            return db.execute("SELECT COUNT(*) FROM notice_events").fetchone()[0]

    def _select_window(
        self, date_col: str, start: date, end: date, category: str | None, order: str
    ) -> list[dict]:
        """按指定日期列取 [start, end] 窗口内的事件。date_col/order 均为内部常量
        （非用户输入），category 走参数化绑定；日期存 ISO 串，字典序即时间序。"""
        sql = (
            "SELECT source, title, category, audience, publish_date, deadline, "
            "deadline_text, event_start, event_end, location, url FROM notice_events "
            f"WHERE {date_col} IS NOT NULL AND {date_col} >= ? AND {date_col} <= ?"
        )
        params: list = [start.isoformat(), end.isoformat()]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += f" ORDER BY {order}"
        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def query_upcoming(
        self, days: int = 30, category: str | None = None, today: date | None = None
    ) -> list[dict]:
        """返回 [today, today+days] 内截止的事件，按截止日期升序。日期运算在代码里完成。"""
        start = today or date.today()
        end = start + timedelta(days=max(0, days))
        return self._select_window("deadline", start, end, category, "deadline ASC, source ASC")

    def query_upcoming_starts(
        self, days: int = 30, category: str | None = None, today: date | None = None
    ) -> list[dict]:
        """返回与 [today, today+days] 有交集的“发生型”事件，按开始日升序。

        用时间窗相交而非“开始日 >= today”：展览/施工/停水这类事件跨度可达
        数月（7月26日—10月26日），只看未来开始日会把所有“正在进行中”的
        事件漏掉，而用户问“现在有什么展览/哪里在施工”恰恰要的就是它们。
        事件区间为 [event_start, COALESCE(event_end, event_start)]。
        """
        start = today or date.today()
        end = start + timedelta(days=max(0, days))
        sql = (
            "SELECT source, title, category, audience, publish_date, deadline, "
            "deadline_text, event_start, event_end, location, url FROM notice_events "
            "WHERE event_start IS NOT NULL AND event_start <= ? "
            "AND COALESCE(event_end, event_start) >= ?"
        )
        params: list = [end.isoformat(), start.isoformat()]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY event_start ASC, source ASC"
        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def query_recent(
        self, days: int = 30, category: str | None = None, today: date | None = None
    ) -> list[dict]:
        """返回 [today-days, today] 内发布的新通知，按发布日降序。"""
        end = today or date.today()
        start = end - timedelta(days=max(0, days))
        return self._select_window(
            "publish_date", start, end, category, "publish_date DESC, source ASC"
        )


# ── 门面（单例 + 抽取编排）─────────────────────────────────────────

_store: EventStore | None = None


def get_event_store() -> EventStore:
    global _store
    if _store is None:
        _store = EventStore()
    return _store


def _event_from_document(doc, today: date | None = None) -> dict | None:
    """把 llama_index Document 转为事件记录；缺正文或来源时返回 None。"""
    text = getattr(doc, "text", "") or ""
    meta = getattr(doc, "metadata", None) or {}
    source = meta.get("source") or ""
    if not text.strip() or not source:
        return None
    event = parse_notice(text, source, today=today)
    event["source"] = source
    event["source_hash"] = hashlib.md5(text.encode("utf-8")).hexdigest()
    # 入库路径可能已补全 url 元数据，优先采用（比正文"来源："行更可靠）。
    if meta.get("url"):
        event["url"] = meta["url"]
    return event


def sync_events_from_documents(documents: list, today: date | None = None) -> int:
    """从 Document 列表抽取并写入事件，返回新写入条数。

    幂等：内容哈希未变的通知直接跳过。单条解析失败只记日志、不中断整批，
    保证事件抽取永远不会拖垮入库主流程。
    """
    if not documents:
        return 0
    store = get_event_store()
    try:
        existing = store.existing_states()
    except Exception:
        logger.warning("读取事件状态失败，本批全量重抽", exc_info=True)
        existing = {}
    events: list[dict] = []
    for doc in documents:
        try:
            event = _event_from_document(doc, today=today)
        except Exception:
            logger.warning("事件抽取失败，跳过该文档", exc_info=True)
            continue
        if event is None:
            continue
        # 内容哈希未变且抽取器版本一致才跳过：升级抽取逻辑（版本递增）
        # 后旧记录会被自动重抽，新字段得以回填。
        if existing.get(event["source"]) == (event["source_hash"], EXTRACTOR_VERSION):
            continue
        events.append(event)
    if not events:
        return 0
    try:
        return store.upsert_events(events)
    except Exception:
        logger.warning("事件写入失败，已跳过（不影响 RAG 入库）", exc_info=True)
        return 0


def sync_events_from_data_dir(data_dir: str, today: date | None = None) -> int:
    """扫描本地通知源目录并同步事件（用于种子语料，进程内幂等）。

    全程 best-effort：任何异常只记日志、返回 0，绝不向上抛——本函数
    挂在 query._ensure_init 上，报错会连带检索初始化一起失败。
    """
    if not os.path.isdir(data_dir):
        return 0
    try:
        from .data_loader import load_documents_from_files
        docs = load_documents_from_files(data_dir)
    except Exception:
        logger.warning("扫描通知源目录失败，跳过事件同步: %s", data_dir, exc_info=True)
        return 0
    return sync_events_from_documents(docs, today=today)


def sync_notice_events(data_dir: str | None = None, today: date | None = None) -> int:
    """把种子通知语料同步进事件时间索引（默认 campus_rag/data）。

    纯确定性正则、不需要嵌入/LLM，故可在应用启动早期安全调用（即使
    嵌入未配置，事件工具仍能工作）；按内容哈希幂等，重复调用只跳过未
    变化的通知。供启动生命周期与 RAG 初始化共用同一入口。
    """
    target = data_dir or str(Path(__file__).resolve().parent / "data")
    return sync_events_from_data_dir(target, today=today)


def delete_events_by_source(source: str) -> int:
    try:
        return get_event_store().delete_by_source(source)
    except Exception:
        logger.warning("删除事件失败 source=%s", source, exc_info=True)
        return 0


def clear_events() -> None:
    try:
        get_event_store().clear()
    except Exception:
        logger.warning("清空事件表失败", exc_info=True)


def get_upcoming_events(
    days: int = 30, category: str | None = None, today: date | None = None
) -> list[dict]:
    """查询未来 N 天内截止的校园事件（确定性日期运算，供 Agent 工具调用）。"""
    try:
        return get_event_store().query_upcoming(days=days, category=category, today=today)
    except Exception:
        logger.warning("查询即将截止事件失败", exc_info=True)
        return []


def get_upcoming_starts(
    days: int = 30, category: str | None = None, today: date | None = None
) -> list[dict]:
    """查询未来 N 天内开始发生的校园事件（展览/施工/班车等）。"""
    try:
        return get_event_store().query_upcoming_starts(days=days, category=category, today=today)
    except Exception:
        logger.warning("查询即将开始事件失败", exc_info=True)
        return []


def get_notice_digest(days: int = 7, today: date | None = None) -> dict:
    """聚合“最近新通知 + 临近事件（截止/开始）”两份数据（供前端今日面板消费）。

    days_left / days_since 等日期差在代码里算好（以服务端本地日期为基准），
    前端与 LLM 不再做日期运算。best-effort：事件库不可用时返回空列表。
    """
    today = today or date.today()
    upcoming: list[dict] = []
    recent: list[dict] = []
    try:
        store = get_event_store()
        deadlines = store.query_upcoming(days=days, today=today)
        for e in deadlines:
            e["kind"] = "deadline"
        starts = store.query_upcoming_starts(days=days, today=today)
        for e in starts:
            e["kind"] = "start"
            # 时间窗相交会把"已开始未结束"的事件一起带出来，前端需要区分
            # "进行中"与"即将开始"，否则会显示成负数剩余天数。
            started = bool(e.get("event_start")) and date.fromisoformat(e["event_start"]) <= today
            e["ongoing"] = started
        # 同一通知既在截止窗口又在开始窗口时以截止为准（罕见，防御性去重）
        seen = {e["source"] for e in deadlines}
        upcoming = deadlines + [e for e in starts if e["source"] not in seen]
        upcoming.sort(key=lambda e: e.get("deadline") or e.get("event_start") or "")
        recent = store.query_recent(days=days, today=today)
    except Exception:
        logger.warning("生成通知摘要失败", exc_info=True)
    for e in upcoming:
        if e.get("kind") == "deadline":
            when = e.get("deadline")
        elif e.get("ongoing"):
            # 进行中：剩余天数按结束日算（无结束日则不给 days_left，由前端显示"进行中"）
            when = e.get("event_end")
        else:
            when = e.get("event_start")
        if when:
            e["days_left"] = (date.fromisoformat(when) - today).days
    for e in recent:
        if e.get("publish_date"):
            e["days_since"] = (today - date.fromisoformat(e["publish_date"])).days
    return {
        "generated_on": today.isoformat(),
        "days": days,
        "upcoming": upcoming,
        "recent": recent,
    }
