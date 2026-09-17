"""
Chat service: agent lifecycle, SSE streaming, checkpoint management.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langgraph.errors import GraphRecursionError

if TYPE_CHECKING:
    from fastapi import Request
    from main import AgentContext

logger = logging.getLogger("server")

ROOT = Path(__file__).resolve().parent.parent.parent
CHAT_TIMEOUT_SECONDS = 180.0
CHAT_RECURSION_LIMIT = 40


def merge_evidence(existing: dict, artifact: object) -> dict:
    """合并工具证据的可展示白名单；不把任意工具正文当作证据。"""
    items: dict[str, dict] = {}
    warnings: list[str] = []
    for payload in (existing, artifact):
        if not isinstance(payload, dict):
            continue
        raw_items = payload.get("evidence", [])
        for item in raw_items[:40] if isinstance(raw_items, list) else []:
            if not isinstance(item, dict) or item.get("kind") not in {"official", "personal", "web", "course_review"}:
                continue
            fields = ("id", "source", "title", "url", "published_at", "excerpt")
            if not all(isinstance(item.get(key), str) for key in fields) or not item["id"]:
                continue
            clean = {key: item[key][:2000 if key == "excerpt" else 512] for key in fields}
            try:
                parsed = urlsplit(clean["url"])
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    clean["url"] = ""
            except ValueError:
                logger.warning("证据链接格式无效，隐藏链接")
                clean["url"] = ""
            clean["kind"] = item["kind"]
            if clean["id"] in items or len(items) < 40:
                items[clean["id"]] = clean
        raw_warnings = payload.get("warnings", [])
        for warning in raw_warnings[:10] if isinstance(raw_warnings, list) else []:
            if isinstance(warning, str) and warning and warning[:512] not in warnings and len(warnings) < 10:
                warnings.append(warning[:512])
    return {"evidence": list(items.values()), "warnings": warnings}


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

    def __init__(self) -> None:
        self._default_agent = None  # AgentContext
        self._user_agents: dict[str, AgentContext] = {}  # username -> AgentContext
        self._pending_closes: set[asyncio.Task] = set()
        self._initialization_error: str | None = None
        # 构建去重锁：并发请求同一缓存未命中的 agent 时，无锁会重复 build，
        # 先建出的 checkpoint 连接被覆盖后永不关闭（句柄泄漏）。
        self._cache_version = 0
        self._active_contexts: dict[int, int] = {}
        self._retired_contexts: dict[int, AgentContext] = {}
        self._active_threads: set[str] = set()
        self._default_lock = asyncio.Lock()
        self._user_locks: dict[str, asyncio.Lock] = {}

    async def initialize(self) -> None:
        if not _llm_credentials_configured():
            self._initialization_error = (
                "未配置 LLM API Key。请在环境变量 LLM_API_KEY 中设置，"
                "或复制 settings.example.json 为 settings.json 并填入 api_key。"
            )
            logger.warning("ChatService is unavailable: %s", self._initialization_error)
            return

        try:
            self._default_agent = await self.get_agent()
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

    async def shutdown(self) -> None:
        self.clear_agent_cache()
        # Wait for all pending connection closes
        if self._pending_closes:
            await asyncio.gather(*self._pending_closes, return_exceptions=True)
        logger.info("ChatService shut down")

    async def get_agent(self, username: str = "") -> AgentContext:
        if self._initialization_error and not _llm_credentials_configured():
            raise RuntimeError(self._initialization_error)

        lock = self._user_locks.setdefault(username, asyncio.Lock()) if username else self._default_lock
        async with lock:
            while True:
                cached = self._user_agents.get(username) if username else self._default_agent
                if cached is not None and not _agent_date_is_stale(cached):
                    return cached
                if cached is not None:
                    if username:
                        self.invalidate_user_agent(username)
                    else:
                        self._default_agent = None
                        self._schedule_close(cached)
                from campus_rag import get_user_tool_prefs
                from main import build_agent
                version = self._cache_version
                prefs = await asyncio.to_thread(get_user_tool_prefs, username) if username else None
                ctx = await build_agent(username=username, tool_prefs=prefs)
                if version != self._cache_version:
                    await self._close_ctx(ctx)
                    continue
                if username:
                    self._user_agents[username] = ctx
                else:
                    self._default_agent = ctx
                self._initialization_error = None
                return ctx

    def invalidate_user_agent(self, username: str) -> None:
        self._cache_version += 1
        old = self._user_agents.pop(username, None)
        if old is not None and old.conn is not None:
            self._schedule_close(old)

    def clear_agent_cache(self) -> None:
        self._cache_version += 1
        for username in list(self._user_agents.keys()):
            self.invalidate_user_agent(username)
        # 默认 agent 也持有旧的 LLM 配置，设置/模型变更后必须一并失效；
        # 其连接必须一并关闭——仅置 None 会让 main._SINGLETON_CONN 被下次
        # build 覆盖，旧连接再无引用可达，每次改配置泄漏一个句柄。
        old = self._default_agent
        self._default_agent = None
        if old is not None and old.conn is not None:
            self._schedule_close(old)

    def _schedule_close(self, ctx: AgentContext) -> None:
        if self._active_contexts.get(id(ctx), 0):
            self._retired_contexts[id(ctx)] = ctx
            return
        task = asyncio.create_task(self._close_ctx(ctx))
        self._pending_closes.add(task)
        task.add_done_callback(self._pending_closes.discard)

    async def _close_ctx(self, ctx: AgentContext) -> None:
        try:
            from main import close_agent
            await close_agent(ctx)
        except Exception as e:
            # 关闭失败不阻断失效流程，但静默吞掉会掩盖 checkpoint 连接泄漏
            logger.warning("关闭 agent checkpoint 连接失败: %s", e)

    @staticmethod
    def _thread_id(username: str, topic_id: str) -> str:
        return f"user-{username}-topic-{topic_id}" if topic_id else f"user-{username}"

    async def delete_thread(self, thread_id: str) -> None:
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
            raise
        finally:
            if own:
                await conn.close()

    async def get_history(self, username: str, topic_id: str) -> list:
        from main import get_history
        thread_id = self._thread_id(username, topic_id)
        return await get_history(thread_id)

    async def stream_chat_events(
        self, username: str, content: str, topic_id: str,
    ) -> AsyncIterator[tuple[str, str | dict]]:
        """Async generator yielding SSE-style (event_type, data) tuples."""
        from langchain_core.messages import AIMessageChunk, ToolMessage

        ctx = await self.get_agent(username)
        thread_id = self._thread_id(username, topic_id)

        context_id = id(ctx)
        self._active_contexts[context_id] = self._active_contexts.get(context_id, 0) + 1
        try:
            seen_tool_names: set[str] = set()
            yield ("thinking", "")

            async with aclosing(ctx.agent.astream(
                {"messages": [{"role": "user", "content": content}]},
                {"configurable": {"thread_id": thread_id}, "recursion_limit": CHAT_RECURSION_LIMIT},
                stream_mode="messages",
            )) as messages:
                async for msg_chunk, _metadata in messages:
                    if isinstance(msg_chunk, ToolMessage):
                        if msg_chunk.status != "error":
                            evidence = merge_evidence({}, msg_chunk.artifact)
                            if evidence["evidence"] or evidence["warnings"]:
                                yield ("evidence", evidence)
                    elif isinstance(msg_chunk, AIMessageChunk):
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
        finally:
            remaining = self._active_contexts[context_id] - 1
            if remaining:
                self._active_contexts[context_id] = remaining
            else:
                self._active_contexts.pop(context_id)
                retired = self._retired_contexts.pop(context_id, None)
                if retired is not None:
                    self._schedule_close(retired)

    async def sse_generator(
        self, username: str, content: str, topic_id: str, request: Request | None = None,
    ) -> AsyncIterator[str]:
        """Stream SSE events while preserving history when checkpoint validation fails."""
        thread_id = self._thread_id(username, topic_id)

        async def _stream() -> AsyncIterator[str]:
            # The browser's AbortController closes the HTTP connection. Check
            # it between events so a disconnected client cannot keep draining
            # the model stream or trigger the checkpoint-retry path.
            if request is not None and await request.is_disconnected():
                logger.info("SSE client disconnected before streaming thread %s", thread_id)
                return
            async with aclosing(self.stream_chat_events(username, content, topic_id)) as stream:
                async for event_type, data in stream:
                    if request is not None and await request.is_disconnected():
                        logger.info("SSE client disconnected during thread %s", thread_id)
                        return
                    yield f"data: {json.dumps({'type': event_type, 'content': data})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        if thread_id in self._active_threads:
            yield f"data: {json.dumps({'type': 'error', 'content': '该话题正在生成，请等待完成或停止后重试'})}\n\n"
            return
        self._active_threads.add(thread_id)
        try:
            deadline = asyncio.get_running_loop().time() + CHAT_TIMEOUT_SECONDS
            async with aclosing(_stream()) as stream:
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError
                    try:
                        chunk = await asyncio.wait_for(anext(stream), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    yield chunk
        except asyncio.CancelledError:
            # A disconnected StreamingResponse is cancelled by ASGI. It is a
            # normal user interruption, not a model/checkpoint failure.
            logger.info("SSE stream cancelled for thread %s", thread_id)
            raise
        except (TimeoutError, ModelCallLimitExceededError, GraphRecursionError) as exc:
            logger.warning("SSE execution budget reached for thread %s (%s)", thread_id, type(exc).__name__)
            reason = "本次处理超时" if isinstance(exc, TimeoutError) else "本次处理已达到调用上限"
            error_content = f"{reason}，生成已停止，已有历史已保留。请缩小问题范围后重试；如涉及保存或导入，请先核对实际结果，避免重复操作。"
            yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"
        except Exception as exc:
            err_msg = str(exc)
            if "tool_calls" in err_msg and "tool messages" in err_msg:
                # 工具调用失配不代表整段历史无效，不能以删除历史换取重试成功。
                logger.warning("Checkpoint tool-message mismatch for thread %s; history preserved", thread_id)
                error_content = "对话中的工具调用记录不完整，本次生成已停止，已有历史已保留。请先备份该话题，可新建话题继续对话。"
                yield f"data: {json.dumps({'type': 'error', 'content': error_content})}\n\n"
            else:
                # 供应商异常可能携带请求正文、地址或认证信息；只记录类型，
                # 用户侧返回稳定文案，不能把未知异常当作安全文本透传。
                logger.error("SSE failed for thread %s (%s)", thread_id, type(exc).__name__)
                yield f"data: {json.dumps({'type': 'error', 'content': '处理失败，请检查模型连接后重试。已有对话历史已保留。'})}\n\n"
        finally:
            self._active_threads.discard(thread_id)


# ── Singleton ─────────────────────────────────────────────────────

_chat_service: ChatService | None = None


async def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
        await _chat_service.initialize()
    return _chat_service
