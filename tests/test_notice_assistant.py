"""通知办理仅提供查询工具，且专用连接在结束与中断后关闭。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk

import main
import campus_rag
from server.services.chat_service import ChatService


def test_read_only_tools_use_allowlist_and_respect_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    """新增工具不自动获得权限，已禁用查询不会被重新启用。"""
    monkeypatch.setitem(main._shared_tools, "future_writer", SimpleNamespace(name="future_writer"))
    tools = main._build_tool_list("local_user", {"web_search": False, "import_ustc_schedule": True}, read_only=True)
    names = {tool.name for tool in tools}
    assert names
    assert not names & {"web_search", "add_personal_data", "import_ustc_schedule", "future_writer"}
    assert "search_campus_notices" in names
    assert main._build_tool_list("local_user", {}, read_only=True) == []


@pytest.mark.parametrize("stop_early", [False, True])
def test_read_only_context_is_not_cached_and_is_closed(monkeypatch: pytest.MonkeyPatch, stop_early: bool) -> None:
    """专用只读实例复用话题标识，但不能污染普通模式实例或泄漏连接。"""
    async def run() -> None:
        service = ChatService()
        seen = []

        async def stream(inputs: dict, config: dict, **kwargs: object):
            seen.append(config["configurable"]["thread_id"])
            yield AIMessageChunk(content="办理清单"), {}

        ctx = SimpleNamespace(agent=SimpleNamespace(astream=stream), conn=object())
        build = AsyncMock(return_value=ctx)
        close = AsyncMock()
        monkeypatch.setattr(main, "build_agent", build)
        monkeypatch.setattr(campus_rag, "get_user_tool_prefs", lambda username: {"web_search": False})
        monkeypatch.setattr(service, "_close_ctx", close)
        generator = service.stream_chat_events("local_user", "通知", "topic", read_only=True)
        assert await anext(generator) == ("thinking", "")
        if not stop_early:
            assert [item async for item in generator] == [("token", "办理清单")]
            assert seen == ["user-local_user-topic-topic"]
        await generator.aclose()
        await asyncio.gather(*service._pending_closes)
        build.assert_awaited_once_with(username="local_user", tool_prefs={"web_search": False}, read_only=True)
        close.assert_awaited_once_with(ctx)
        assert not service._user_agents and service._default_agent is None
        assert not service._active_contexts and not service._retired_contexts

    asyncio.run(run())


@pytest.mark.parametrize("read_only", [True, False, "false"])
def test_route_validates_and_forwards_read_only_mode(read_only: object) -> None:
    """HTTP 参数不能将字符串误当布尔值，正常请求保留模式。"""
    from fastapi import HTTPException
    from server.routes.chat import chat_stream

    async def run() -> None:
        seen = []

        async def stream(*args: object, **kwargs: object):
            seen.append(kwargs["read_only"])
            yield "data: {}\n\n"

        if not isinstance(read_only, bool):
            with pytest.raises(HTTPException) as error:
                await chat_stream(None, {"content": "通知", "read_only": read_only}, "local_user", SimpleNamespace(sse_generator=stream))
            assert error.value.status_code == 400
            return
        response = await chat_stream(None, {"content": "通知", "read_only": read_only}, "local_user", SimpleNamespace(sse_generator=stream))
        assert [item async for item in response.body_iterator]
        assert seen == [read_only]

    asyncio.run(run())
