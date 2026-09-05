import aiosqlite
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from tools.search import (
    fetch_course_review_text,
    fetch_text_from_url,
    fetch_ustc_text_from_url,
    search_course_reviews,
    search_ustc_web,
    search_web,
)
from campus_rag import search_notices_answer, search_user_data_answer, add_user_data
from llama_index.core import Document
import model.config as config

@dataclass
class AgentContext:
    agent: object
    conn: object
    username: str = ""
    # prompt 中注入的“当前日期”生成于构建当日；缓存跨天后需重建（见 chat_service）
    built_date: date | None = None


logger = logging.getLogger("agent")

_CHECKPOINT_DB = Path(__file__).resolve().parent / "data" / "agent_checkpoints.db"
_MAX_CHECKPOINTS_PER_THREAD = 50
_MAX_CHECKPOINT_DB_MB = 200

TOOL_METADATA = [
    {"name": "web_search", "label": "网络搜索", "description": "按关键词搜索公开网页并返回标题和URL"},
    {"name": "web_fetch", "label": "网页正文", "description": "读取指定公开URL并提取正文"},
    {"name": "ustc_web_search", "label": "科大网站搜索", "description": "只搜索配置白名单中的中国科大官方网站"},
    {"name": "ustc_web_fetch", "label": "科大网页正文", "description": "读取白名单内中国科大官方网页正文"},
    {"name": "course_review_search", "label": "评课社区搜索", "description": "搜索 icourse.club 的公开课程评价和课程详情页"},
    {"name": "course_review_fetch", "label": "评课社区正文", "description": "读取 icourse.club 公开课程详情与学生点评"},
    {"name": "search_campus_notices", "label": "校园通知", "description": "搜索校园官方通知、活动、比赛、讲座等信息（经AI总结）"},
    {"name": "get_upcoming_events", "label": "即将发生事件", "description": "按真实日期查询未来 N 天内截止（报名/选课/评奖）或开始（展览/施工/班车）的校园事件"},
    {"name": "search_notices_raw", "label": "通知原文", "description": "获取校园通知原始文本片段，用于多跳推理时查看原文"},
    {"name": "search_my_data", "label": "个人数据", "description": "搜索用户个人上传的课表、成绩等私有信息（经AI总结）"},
    {"name": "search_user_data_raw", "label": "个人数据原文", "description": "获取个人数据原始文本片段，用于多跳推理时查看原文"},
    {"name": "add_personal_data", "label": "添加个人数据", "description": "将文本内容添加到个人知识库，用于后续检索"},
    {"name": "get_my_schedule", "label": "获取我的课表", "description": "读取本地已导入的结构化课表；不指定学期时按当前日期自动返回当前学期"},
    {"name": "import_ustc_schedule", "label": "导入教务课表", "description": "解析用户提供的中国科大教务课表 HTML/JSON 并更新本地课表数据库"},
]

SYSTEM_PROMPT = """你是中国科学技术大学的校园信息助手。

## 工具使用
- 校园活动、比赛、课程、讲座、报名 → search_campus_notices
- 用户问“最近/本周/本月有什么要截止的报名、选课、提交、答辩”等时间敏感问题 → get_upcoming_events(kind="deadline")（按真实截止日期排序，优先于语义检索）
- 用户问“这周有什么活动/展览/讲座”“哪天停水/停电/施工/通车”等即将发生的事 → get_upcoming_events(kind="start")（按真实开始日期排序）
- 需要查看通知原文或对比多条信息 → search_notices_raw
- 用户个人课表、成绩、教务信息 → search_my_data
- 用户询问已导入的具体课表安排 → get_my_schedule
- 需要查看个人数据原文或对比多条信息 → search_user_data_raw
- 添加个人数据到知识库 → add_personal_data
- 用户提供教务系统课表 HTML/JSON 并要求导入 → import_ustc_schedule
- 用户比较课程、教师、难度、作业量或给分 → course_review_search；拿到课程页后用 course_review_fetch
- 不知道网页地址、需要查找最新公开信息 → web_search
- 已知网页地址、需要读取完整正文 → web_fetch
- 中国科大校内信息优先使用 ustc_web_search；拿到URL后使用 ustc_web_fetch 阅读原文
- 选课建议要把教务系统/课程目录的官方信息与评课社区的学生意见分开标注；评课社区内容仅供参考，不要把主观评价当作官方事实，也不要替用户自动提交选课

## 重要规则
- 用户要求写文章时直接在对话中回复
- 本地检索工具会自动做关键词重试；若检索结果仍为空或完全无关，且问题涉及时效性信息（比赛/讲座/政策/活动），可用 web_search 兜底确认；确认无果再如实说明“未找到相关信息”，不要编造

## 回答规范
1. 先在心里梳理检索到的信息要点，再用自己的话组织成自然的回答
2. 在回答末尾列出信息来源（文件名或出处）；网页来源必须使用 Markdown 链接格式 `[标题](URL)`，不要只输出裸 URL
3. 如果搜索工具已经返回 Markdown 链接，请保留链接格式并在最终来源列表中复用
4. 如果需要在链接外加括号或句号，把这些标点放在 Markdown 链接语法之外
5. 如果检索结果为空或完全无关，直接说"未找到相关信息"

## 多跳推理指南
1. 面对复杂问题时，先用 search_notices_raw 或 search_campus_notices 进行第一次检索
2. 查看检索结果后，判断信息是否完整；如果不完整，从结果中提取关键线索（如具体活动名称、部门名称）进行第二次检索
3. 可能需要多次检索不同关键词才能覆盖问题的所有方面
4. 综合所有检索结果后给出完整回答

## 学期与相对时间
- 中科大三学期制：春季学期约 2-6 月，夏季学期约 7-8 月，秋季学期约 9 月-次年 1 月
- 用户说“这学期/本学期/下学期/上学期”等相对时间时，先根据当前日期换算成具体学期名（如“2026年秋季学期”），再查询或筛选，不得把其他学期的课程混入回答
- 查课表优先用 get_my_schedule：留空学期即自动取当前学期；检索个人数据时，按来源或正文中的学期名只保留所问学期的内容
"""


_WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _system_prompt_with_date() -> str:
    """构建 agent 时注入当天日期：模型知识有截止日，不注入则无法解析“这学期”等相对时间。"""

    today = datetime.now()
    return SYSTEM_PROMPT + (
        f"\n\n## 当前日期\n今天是 {today:%Y-%m-%d}（{_WEEKDAY_NAMES[today.weekday()]}）。"
    )


# ── Shared (non-user-specific) tools ──────────────────────────────

@tool
def search_campus_notices(query: str) -> str:
    """搜索校园官方通知，获取活动、比赛、课程、讲座、报名等公共信息（经AI总结）。"""
    try:
        return search_notices_answer(query)
    except Exception as e:
        logger.error("search_campus_notices failed: %s", e, exc_info=True)
        return f"搜索校园通知时出错: {e}"


@tool
def search_notices_raw(query: str) -> str:
    """获取校园官方通知的原始文本片段。当你需要查看原文或要对比多条信息时使用此工具。"""
    try:
        from campus_rag import search_notices
        return search_notices(query)
    except Exception as e:
        logger.error("search_notices_raw failed: %s", e, exc_info=True)
        return f"搜索通知原文时出错: {e}"


@tool
def get_upcoming_events(days: int = 30, category: str = "", kind: str = "deadline") -> str:
    """按日期查询未来 N 天内的校园事件（确定性时间索引，按真实日期排序）。

    kind="deadline"：即将截止的报名/选课/考试/评奖/竞赛/讲座/实习/答辩等（默认）。
    kind="start"：即将开始的展览/施工/停水停电/班车/活动等。
    用户问"最近有什么要截止的""这周有哪些报名"用 deadline；
    问"这周有什么活动/展览""哪天停水/施工"用 start。
    days 为向后看的天数（默认 30）；category 可选，留空返回全部类别。
    """
    try:
        # 惰性导入并用别名：模块级名 get_upcoming_events 已被 @tool 重绑为
        # StructuredTool，直接同名调用会递归到工具自身（不可调用）。
        from campus_rag import get_upcoming_events as query_upcoming_events
        from campus_rag import get_upcoming_starts as query_upcoming_starts
        today = datetime.now().date()
        if kind == "start":
            rows = query_upcoming_starts(days=days, category=category.strip() or None, today=today)
            when_label = "开始/进行"
        else:
            rows = query_upcoming_events(days=days, category=category.strip() or None, today=today)
            when_label = "截止"
        if not rows:
            scope = f"{category.strip()}类" if category.strip() else ""
            return f"未来 {days} 天内没有{scope}即将{when_label}的校园事件。"
        lines = [f"未来 {days} 天内{when_label}的校园事件（共 {len(rows)} 条，按日期排序）："]
        for row in rows:
            cat = f"[{row['category']}]" if row.get("category") else ""
            aud = f"（面向{row['audience']}）" if row.get("audience") else ""
            loc = f"（地点：{row['location']}）" if row.get("location") else ""
            head = f"- {cat}{row.get('title') or row['source']}{aud}{loc}："
            if kind == "start":
                started = bool(row.get("event_start")) and date.fromisoformat(row["event_start"]) <= today
                if started:
                    # 时间窗相交会把进行中的事件带出来，剩余天数按结束日算
                    if row.get("event_end"):
                        left = (date.fromisoformat(row["event_end"]) - today).days
                        when_text = f"进行中，至 {row['event_end']} 结束（还剩 {left} 天）"
                    else:
                        when_text = f"{row['event_start']} 起进行中（未标注结束日期）"
                else:
                    left = (date.fromisoformat(row["event_start"]) - today).days
                    when_text = f"{row['event_start']} 开始（还剩 {left} 天）"
            else:
                remaining = (date.fromisoformat(row["deadline"]) - today).days
                left_text = "就是今天" if remaining == 0 else f"还剩 {remaining} 天"
                when_text = f"截止 {row['deadline']}（{left_text}）"
            line = f"{head}{when_text}"
            if row.get("deadline_text") and kind == "deadline":
                line += f"\n  原文：{row['deadline_text'][:80]}"
            if row.get("url"):
                line += f"\n  来源：{row['url']}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        logger.error("get_upcoming_events failed: %s", e, exc_info=True)
        return f"查询即将发生的校园事件时出错: {e}"


# ── Per-user tool factories ───────────────────────────────────────

def _make_search_my_data(username: str):
    @tool
    def search_my_data(query: str) -> str:
        """搜索用户个人数据（个人上传或爬取的教务、课表等私有信息）。"""
        try:
            return search_user_data_answer(query, username)
        except Exception as e:
            logger.error("search_my_data failed: %s", e, exc_info=True)
            return f"搜索个人数据时出错: {e}"
    return search_my_data


def _make_add_personal_data(username: str):
    @tool
    def add_personal_data(content: str) -> str:
        """将文本内容添加到用户的个人知识库中。用户说"帮我记录""保存一下""添加到我的数据"时使用此工具。"""
        try:
            doc = Document(text=content, metadata={"source": "手动输入"})
            add_user_data(username, [doc])
            return f"已添加个人数据（{len(content)} 字）"
        except Exception as e:
            logger.error("add_personal_data failed: %s", e, exc_info=True)
            return f"添加个人数据时出错: {e}"
    return add_personal_data


def _make_search_user_data_raw(username: str):
    @tool
    def search_user_data_raw(query: str) -> str:
        """获取用户个人数据的原始文本片段。当你需要查看原文或要对比多条信息时使用此工具。"""
        try:
            from campus_rag import search_user_data
            return search_user_data(query, username)
        except Exception as e:
            logger.error("search_user_data_raw failed: %s", e, exc_info=True)
            return f"搜索个人数据原文时出错: {e}"
    return search_user_data_raw


def _make_get_my_schedule(username: str):
    @tool
    def get_my_schedule(semester: str = "") -> str:
        """读取用户已导入本地数据库的课表。学期名称格式如“2026年秋季学期”；
        留空时按今天日期自动返回当前学期的课表，不要把其他学期的课程混入。"""
        try:
            from server.services.schedule_service import current_semester, get_schedule_service

            service = get_schedule_service()
            requested = semester.strip()
            today = datetime.now()
            if not requested:
                requested = current_semester(today)
                imported = service.list(username).get("semesters") or []
                if requested not in imported:
                    names = "、".join(imported) if imported else "（无）"
                    return (
                        f"今天是 {today:%Y-%m-%d}，当前学期应为 {requested}，但尚未导入该学期的课表。"
                        f"已导入的学期：{names}。请引导用户在‘我的课表’中导入后重试。"
                    )
                data = service.list(username, requested)
            else:
                data = service.list(username, requested)
            courses = data.get("courses") or []
            if not courses:
                return f"没有找到 {requested} 的课表。请在‘我的课表’中导入教务课表 HTML 或结构化 JSON。"
            lines = [f"学期：{data.get('semester') or requested}"]
            weekday_names = ["", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            for row in courses:
                teachers = "、".join(row.get("teachers") or []) or "教师待定"
                code = f"{row.get('course_code')} " if row.get("course_code") else ""
                sections = ""
                if row.get("start_section"):
                    end = row.get("end_section") or row["start_section"]
                    sections = f"第{row['start_section']}-{end}节"
                weekday = row.get("weekday")
                weekday_text = weekday_names[weekday] if weekday in range(1, 8) else "星期待定"
                weeks = row.get("weeks") or []
                week_text = f"第{min(weeks)}-{max(weeks)}周" if weeks else "周次见课表"
                time_text = ""
                if row.get("start_time") and row.get("end_time"):
                    time_text = f" {row['start_time']}-{row['end_time']}"
                lines.append(
                    f"- {code}{row['name']}；{weekday_text} {sections}{time_text}；"
                    f"{week_text}；{row.get('location') or '地点待定'}；教师：{teachers}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.error("get_my_schedule failed: %s", e, exc_info=True)
            return f"获取课表时出错: {e}"

    return get_my_schedule


def _make_import_ustc_schedule(username: str):
    @tool
    def import_ustc_schedule(content: str, filename: str = "") -> str:
        """解析用户提供的 USTC 教务课表 HTML/JSON，并更新本地课表数据库。"""
        try:
            from server.services.schedule_service import get_schedule_service
            from server.services.ustc_schedule import parse_ustc_schedule

            parsed = parse_ustc_schedule(content, filename)
            count = get_schedule_service().replace(username, parsed["semester"], parsed["courses"])
            return (
                f"已解析并更新课表：{parsed['semester']}，"
                f"{len(parsed['courses'])} 门课程，{count} 个上课安排。"
            )
        except Exception as e:
            logger.error("import_ustc_schedule failed: %s", e, exc_info=True)
            return f"导入教务课表时出错: {e}"

    return import_ustc_schedule


_SINGLETON_CONN = None


async def _prune_checkpoints(conn):
    try:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        )
        if not await cur.fetchone():
            return
        cursor = await conn.execute(
            "SELECT thread_id, COUNT(*) as cnt FROM checkpoints GROUP BY thread_id HAVING cnt > ?",
            (_MAX_CHECKPOINTS_PER_THREAD,),
        )
        rows = await cursor.fetchall()
        for thread_id, cnt in rows:
            excess = cnt - _MAX_CHECKPOINTS_PER_THREAD
            if excess > 0:
                await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id IN ("
                    "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? "
                    "ORDER BY checkpoint_id ASC LIMIT ?)",
                    (thread_id, thread_id, excess),
                )
                await conn.execute(
                    "DELETE FROM writes WHERE thread_id = ? AND checkpoint_id NOT IN ("
                    "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ?)",
                    (thread_id, thread_id),
                )
        await conn.commit()
        db_size_mb = _CHECKPOINT_DB.stat().st_size / (1024 * 1024) if _CHECKPOINT_DB.exists() else 0
        if db_size_mb > _MAX_CHECKPOINT_DB_MB:
            await conn.execute("VACUUM")
            logger.info("Checkpoint DB vacuumed (was %.1f MB)", db_size_mb)
    except Exception:
        logger.warning("Checkpoint pruning failed", exc_info=True)


_shared_tools = {
    "web_search": search_web,
    "web_fetch": fetch_text_from_url,
    "ustc_web_search": search_ustc_web,
    "ustc_web_fetch": fetch_ustc_text_from_url,
    "course_review_search": search_course_reviews,
    "course_review_fetch": fetch_course_review_text,
    "search_campus_notices": search_campus_notices,
    "search_notices_raw": search_notices_raw,
    "get_upcoming_events": get_upcoming_events,
}


def _build_tool_list(username: str, tool_prefs: dict[str, bool] | None = None):
    """Build the list of tools for a given user, filtering by tool preferences.

    None 表示用户未设置偏好（默认全部启用）；空字典是用户显式禁用全部工具，
    必须尊重而非回退全启用，否则前端设置被静默忽略。
    偏好字典只反映用户保存时的工具集：不在字典中的工具视为"用户未表态"，
    默认启用，否则之后新增的工具会被旧偏好静默禁用。
    """
    user_tools = {
        "search_my_data": _make_search_my_data(username),
        "add_personal_data": _make_add_personal_data(username),
        "search_user_data_raw": _make_search_user_data_raw(username),
        "get_my_schedule": _make_get_my_schedule(username),
        "import_ustc_schedule": _make_import_ustc_schedule(username),
    }
    all_tools = {**_shared_tools, **user_tools}

    if tool_prefs is None:
        names = list(all_tools.keys())
    elif not tool_prefs:
        # 空字典 = 用户显式禁用了全部工具，与"未表态默认启用"区分开
        names = []
    else:
        names = [n for n in all_tools if tool_prefs.get(n, True)]

    if not names:
        logger.warning("用户 %s 未启用任何工具，agent 将以纯对话模式运行",
                       username or "<default>")

    return [all_tools[n] for n in names]


async def build_agent(username: str = "", tool_prefs: dict[str, bool] | None = None) -> AgentContext:
    """Create an Agent instance. Tools requiring user context are created via closure
    when *username* is provided."""
    global _SINGLETON_CONN
    model = config.init_chat()
    _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(_CHECKPOINT_DB))
    try:
        await _prune_checkpoints(conn)
        checkpointer = AsyncSqliteSaver(conn)

        tools = _build_tool_list(username, tool_prefs)

        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=_system_prompt_with_date(),
            checkpointer=checkpointer,
        )
    except Exception:
        await conn.close()
        raise
    ctx = AgentContext(agent=agent, conn=conn, username=username, built_date=date.today())

    if not username and tool_prefs is None:
        _SINGLETON_CONN = conn
    return ctx


async def close_agent(ctx: AgentContext | None = None):
    """Close an agent's checkpoint connection. Without arguments, closes the singleton."""
    global _SINGLETON_CONN
    if ctx is not None:
        await ctx.conn.close()
        return
    if _SINGLETON_CONN is not None:
        await _SINGLETON_CONN.close()
        _SINGLETON_CONN = None


async def run_agent(content: str, thread_id: str = "default") -> str:
    """Convenience: run a single-turn agent invocation and return the final reply."""
    global _SINGLETON_CONN
    ctx = await build_agent()
    try:
        result = await ctx.agent.ainvoke(
            {"messages": [{"role": "user", "content": content}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return result["messages"][-1].content
    finally:
        # 每次调用都会新建 checkpoint 连接，不关闭会持续泄漏 sqlite 句柄。
        # 注意：无参 build_agent 会同时记录为单例连接，此处一并清理引用，
        # 避免 close_agent() 再次关闭已关连接。
        if _SINGLETON_CONN is ctx.conn:
            _SINGLETON_CONN = None
        await close_agent(ctx)


def _checkpoint_messages_to_history(raw_messages: list) -> list:
    """把 checkpoint 中的 LangChain 消息列表转为前端可渲染的历史。

    规则：跳过非 human/ai 消息（如 tool）；仅带 tool_calls 的 AI 消息
    content 为空，直接发给前端会渲染出空气泡；多跳推理产生的多条连续
    AI 消息合并为一条，与流式渲染时的单气泡视觉一致。
    """
    result = []
    for m in raw_messages:
        if hasattr(m, 'type') and hasattr(m, 'content'):
            if m.type in ('human', 'ai'):
                content = m.content if isinstance(m.content, str) else str(m.content)
                if m.type == 'ai' and not content.strip():
                    continue
                role = "user" if m.type == "human" else "assistant"
                if result and result[-1]["role"] == role == "assistant":
                    result[-1]["content"] += "\n\n" + content
                else:
                    result.append({"role": role, "content": content})
    return result


async def get_history(thread_id: str, conn=None) -> list:
    """Get conversation history for a thread_id. Uses the provided connection or opens one."""
    own_conn = conn is None
    if own_conn:
        conn = await aiosqlite.connect(str(_CHECKPOINT_DB))
    checkpointer = AsyncSqliteSaver(conn)
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = await checkpointer.aget_tuple(config)
        if state and state.checkpoint:
            channel_values = state.checkpoint.get("channel_values", {})
            return _checkpoint_messages_to_history(channel_values.get("messages", []))
    finally:
        if own_conn:
            await conn.close()
    return []


if __name__ == "__main__":
    import asyncio
    request = "今年暑假有什么活动？"
    print(asyncio.run(run_agent(request, thread_id="campus-query")))
