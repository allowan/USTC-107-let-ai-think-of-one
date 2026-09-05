"""
Chat service: agent lifecycle, SSE streaming, checkpoint management.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("server")

ROOT = Path(__file__).resolve().parent.parent.parent


def _llm_credentials_configured() -> bool:
    """Return whether chat-agent construction has the credential it needs.

    Schedule and personal-data APIs do not require an LLM. Keep the chat
    service lazy so a local installation can start those APIs before the user
    configures a model.
    """
    from model.config import read_json

    return bool(os.environ.get("LLM_API_KEY") or read_json().get("api_key"))


def _agent_date_is_stale(ctx) -> bool:
    """Agent prompt 中的“当前日期”生成于构建当日；跨天缓存必须重建，
    否则模型会拿着过期日期解析“这学期”等相对时间（开学日前后尤其致命）。"""

    from datetime import date

    return getattr(ctx, "built_date", None) != date.today()


class ChatService:
    """Manages agent instances and provides streaming chat."""

    def __init__(self):
        self._default_agent = None  # AgentContext
        self._user_agents: dict[str, object] = {}  # username -> AgentContext
        self._pending_closes: set[asyncio.Task] = set()
        self._initialization_error: str | None = None
        # 构建去重锁：并发请求同一缓存未命中的 agent 时，无锁会重复 build，
        # 先建出的 checkpoint 连接被覆盖后永不关闭（句柄泄漏）。
        self._default_lock = asyncio.Lock()
        self._user_locks: dict[str, asyncio.Lock] = {}

    async def initialize(self):
        if not _llm_credentials_configured():
            self._initialization_error = (
                "未配置 LLM API Key。请在环境变量 LLM_API_KEY 中设置，"
                "或复制 settings.example.json 为 settings.json 并填入 api_key。"
            )
            logger.warning("ChatService is unavailable: %s", self._initialization_error)
            return

        from main import build_agent
        try:
            self._default_agent = await build_agent()
            self._initialization_error = None
            logger.info("ChatService initialized")
        except Exception as exc:
            # 启动期构建失败（如 checkpoint DB 异常）不能拖垮整个服务：
            # 记录错误保持降级，首次对话时 get_agent 会走重建重试路径。
            self._initialization_error = f"Agent 初始化失败：{exc}"
            logger.error("ChatService initialization failed", exc_info=True)

    @property
    def is_ready(self) -> bool:
        return self._default_agent is not None

    async def shutdown(self):
        from main import close_agent
        self.clear_agent_cache()
        # Wait for all pending connection closes
        if self._pending_closes:
            await asyncio.gather(*self._pending_closes, return_exceptions=True)
        await close_agent()
        logger.info("ChatService shut down")

    async def get_agent(self, username: str = ""):
        if self._initialization_error and not _llm_credentials_configured():
            raise RuntimeError(self._initialization_error)

        if username:
            lock = self._user_locks.setdefault(username, asyncio.Lock())
            async with lock:
                cached = self._user_agents.get(username)
                if cached is not None:
                    if not _agent_date_is_stale(cached):
                        return cached
                    self.invalidate_user_agent(username)
                from campus_rag import get_user_tool_prefs
                from main import build_agent
                prefs = get_user_tool_prefs(username)
                ctx = await build_agent(username=username, tool_prefs=prefs)
                self._user_agents[username] = ctx
                return ctx
        async with self._default_lock:
            if self._default_agent is not None and _agent_date_is_stale(self._default_agent):
                # 跨天重建：旧 checkpoint 连接异步关闭，避免句柄泄漏
                old = self._default_agent
                self._default_agent = None
                self._schedule_close(old)
            if self._default_agent is None:
                from main import build_agent
                try:
                    self._default_agent = await build_agent()
                    self._initialization_error = None
                except Exception as exc:
                    self._initialization_error = str(exc)
                    raise
            return self._default_agent

    def invalidate_user_agent(self, username: str):
        old = self._user_agents.pop(username, None)
        if old is not None and old.conn is not None:
            self._schedule_close(old)

    def clear_agent_cache(self):
        for username in list(self._user_agents.keys()):
            self.invalidate_user_agent(username)
        # 默认 agent 也持有旧的 LLM 配置，设置/模型变更后必须一并失效；
        # 其连接必须一并关闭——仅置 None 会让 main._SINGLETON_CONN 被下次
        # build 覆盖，旧连接再无引用可达，每次改配置泄漏一个句柄。
        old = self._default_agent
        self._default_agent = None
        if old is not None and old.conn is not None:
            self._schedule_close(old)

    def _schedule_close(self, ctx):
        task = asyncio.create_task(self._close_ctx(ctx))
        self._pending_closes.add(task)
        task.add_done_callback(self._pending_closes.discard)

    async def _close_ctx(self, ctx):
        try:
            from main import close_agent
            await close_agent(ctx)
        except Exception as e:
            # 关闭失败不阻断失效流程，但静默吞掉会掩盖 checkpoint 连接泄漏
            logger.warning("关闭 agent checkpoint 连接失败: %s", e)

    @staticmethod
    def _thread_id(username: str, topic_id: str) -> str:
        return f"user-{username}-topic-{topic_id}" if topic_id else f"user-{username}"

    async def delete_thread(self, thread_id: str):
        """Delete all checkpoints for a thread."""
        import aiosqlite
        # Try to use an existing agent's connection first
        conn = None
        for ctx in [self._default_agent] + list(self._user_agents.values()):
            if ctx is not None and ctx.conn is not None:
                conn = ctx.conn
                break
        own = conn is None
        if own:
            db_path = ROOT / "data" / "agent_checkpoints.db"
            conn = await aiosqlite.connect(str(db_path))
        try:
            await conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
            await conn.commit()
        except Exception:
            logger.warning("Failed to delete checkpoints for thread %s", thread_id, exc_info=True)
        finally:
            if own:
                await conn.close()

    async def get_history(self, username: str, topic_id: str) -> list:
        from main import get_history
        thread_id = self._thread_id(username, topic_id)
        return await get_history(thread_id)

    async def stream_chat_events(self, username: str, content: str, topic_id: str):
        """Async generator yielding SSE-style (event_type, data) tuples."""
        from langchain_core.messages import AIMessageChunk

        ctx = await self.get_agent(username)
        thread_id = self._thread_id(username, topic_id)

        seen_tool_names: set[str] = set()
        yield ("thinking", "")

        async for msg_chunk, _metadata in ctx.agent.astream(
            {"messages": [{"role": "user", "content": content}]},
            {"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if isinstance(msg_chunk, AIMessageChunk):
                emitted_tool = False
                if msg_chunk.tool_call_chunks:
                    for tc in msg_chunk.tool_call_chunks:
                        name = tc.get("name")
                        if name and name not in seen_tool_names:
                            seen_tool_names.add(name)
                            yield ("tool_use", str(name))
                            emitted_tool = True
                if msg_chunk.tool_calls:
                    for tc in msg_chunk.tool_calls:
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                        if name and name not in seen_tool_names:
                            seen_tool_names.add(name)
                            yield ("tool_use", str(name))
                            emitted_tool = True
                if emitted_tool:
                    continue
                if msg_chunk.content:
                    text = msg_chunk.content
                    if not isinstance(text, str):
                        text = str(text)
                    yield ("token", text)

    async def sse_generator(self, username: str, content: str, topic_id: str, request=None):
        """Full SSE response generator with error handling and retry on corrupted checkpoints."""
        thread_id = self._thread_id(username, topic_id)

        async def _stream():
            # The browser's AbortController closes the HTTP connection. Check
            # it between events so a disconnected client cannot keep draining
            # the model stream or trigger the checkpoint-retry path.
            if request is not None and await request.is_disconnected():
                logger.info("SSE client disconnected before streaming thread %s", thread_id)
                return
            async for event_type, data in self.stream_chat_events(username, content, topic_id):
                if request is not None and await request.is_disconnected():
                    logger.info("SSE client disconnected during thread %s", thread_id)
                    return
                yield f"data: {json.dumps({'type': event_type, 'content': data})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        try:
            async for chunk in _stream():
                yield chunk
        except asyncio.CancelledError:
            # A disconnected StreamingResponse is cancelled by ASGI. It is a
            # normal user interruption, not a model/checkpoint failure.
            logger.info("SSE stream cancelled for thread %s", thread_id)
            raise
        except Exception as exc:
            err_msg = str(exc)
            if "tool_calls" in err_msg and "tool messages" in err_msg:
                logger.warning("Checkpoint corrupted for thread %s, retrying", thread_id)
                await self.delete_thread(thread_id)
                from campus_rag import reset_caches
                reset_caches()
                try:
                    async for chunk in _stream():
                        yield chunk
                except Exception as exc2:
                    logger.error("SSE retry failed for thread %s: %s", thread_id, exc2, exc_info=True)
                    yield f"data: {json.dumps({'type': 'error', 'content': f'处理失败: {exc2}'})}\n\n"
            else:
                logger.error("SSE error for thread %s: %s", thread_id, exc, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'content': f'处理失败: {exc}'})}\n\n"


# ── Singleton ─────────────────────────────────────────────────────

_chat_service: ChatService | None = None


async def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
        await _chat_service.initialize()
    return _chat_service
