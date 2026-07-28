import aiosqlite
import logging
from dataclasses import dataclass
from pathlib import Path
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from tools.search import fetch_text_from_url
from campus_rag import search_notices_answer, search_user_data_answer, add_user_data
from llama_index.core import Document
import model.config as config

@dataclass
class AgentContext:
    agent: object
    conn: object
    username: str = ""


logger = logging.getLogger("agent")

_CHECKPOINT_DB = Path(__file__).resolve().parent / "data" / "agent_checkpoints.db"
_MAX_CHECKPOINTS_PER_THREAD = 50
_MAX_CHECKPOINT_DB_MB = 200

TOOL_METADATA = [
    {"name": "web_search", "label": "网络搜索", "description": "从URL获取网页文档内容"},
    {"name": "search_campus_notices", "label": "校园通知", "description": "搜索校园官方通知、活动、比赛、讲座等信息"},
    {"name": "search_my_data", "label": "个人数据", "description": "搜索用户个人上传的课表、成绩等私有信息"},
    {"name": "add_personal_data", "label": "添加个人数据", "description": "将文本内容添加到个人知识库，用于后续检索"},
]

SYSTEM_PROMPT = """你是中国科学技术大学的校园信息助手。

## 工具使用
- 校园活动、比赛、课程、讲座、报名 → search_campus_notices
- 用户个人课表、成绩、教务信息 → search_my_data
- 添加个人数据到知识库 → add_personal_data
- 网页文档内容获取 → web_search

## 重要规则
- 用户要求写文章时直接在对话中回复

## 回答规范
1. 先在心里梳理检索到的信息要点，再用自己的话组织成自然的回答
2. 严禁输出任何来源标记，包括但不限于：文件名（xxx.txt）、编号（[1]）、URL、分隔符
3. 严禁使用"根据搜索结果""根据上下文""检索结果显示"等措辞
4. 如果多条信息相关，直接综合叙述，不要逐条罗列
5. 如果检索结果为空或完全无关，直接说"未找到相关信息"
"""


# ── Shared (non-user-specific) tools ──────────────────────────────

@tool
def search_campus_notices(query: str) -> str:
    """搜索校园官方通知，获取活动、比赛、课程、讲座、报名等公共信息。"""
    try:
        return search_notices_answer(query)
    except Exception as e:
        logger.error("search_campus_notices failed: %s", e, exc_info=True)
        return f"搜索校园通知时出错: {e}"


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
    "web_search": fetch_text_from_url,
    "search_campus_notices": search_campus_notices,
}


def _build_tool_list(username: str, enabled_tool_names: list[str] | None = None):
    """Build the list of tools for a given user, filtering by enabled_tool_names."""
    user_tools = {
        "search_my_data": _make_search_my_data(username),
        "add_personal_data": _make_add_personal_data(username),
    }
    all_tools = {**_shared_tools, **user_tools}

    if enabled_tool_names is None:
        names = list(all_tools.keys())
    else:
        names = [n for n in enabled_tool_names if n in all_tools]

    if not names:
        logger.warning("No tools enabled, using all tools")
        names = list(all_tools.keys())

    return [all_tools[n] for n in names]


async def build_agent(username: str = "", enabled_tool_names: list[str] | None = None) -> AgentContext:
    """Create an Agent instance. Tools requiring user context are created via closure
    when *username* is provided."""
    global _SINGLETON_CONN
    _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(_CHECKPOINT_DB))
    await _prune_checkpoints(conn)
    checkpointer = AsyncSqliteSaver(conn)

    tools = _build_tool_list(username, enabled_tool_names)

    agent = create_agent(
        model=config.init_chat(),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    ctx = AgentContext(agent=agent, conn=conn, username=username)

    if not username and enabled_tool_names is None:
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
    ctx = await build_agent()
    result = await ctx.agent.ainvoke(
        {"messages": [{"role": "user", "content": content}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content


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
            raw_messages = channel_values.get("messages", [])
            result = []
            for m in raw_messages:
                if hasattr(m, 'type') and hasattr(m, 'content'):
                    if m.type in ('human', 'ai'):
                        result.append({
                            "role": "user" if m.type == "human" else "assistant",
                            "content": m.content if isinstance(m.content, str) else str(m.content),
                        })
            return result
    finally:
        if own_conn:
            await conn.close()
    return []


if __name__ == "__main__":
    import asyncio
    request = "今年暑假有什么活动？"
    print(asyncio.run(run_agent(request, thread_id="campus-query")))
