"""对话预算耗尽时必须关闭流并保留历史，不调用实际模型。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessageChunk
from langgraph.errors import GraphRecursionError

from server.services import chat_service


def test_timeout_preserves_partial_output_and_allows_next_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务超时不是正常完成，流必须收尾且不删除历史或自动重发。"""
    async def run() -> None:
        service = chat_service.ChatService()
        closed = []
        calls = []

        async def slow_stream(*args: object):
            calls.append(args)
            try:
                yield ("token", "已生成部分")
                await asyncio.Event().wait()
            finally:
                closed.append(True)

        monkeypatch.setattr(chat_service, "CHAT_TIMEOUT_SECONDS", 0.03)
        monkeypatch.setattr(service, "stream_chat_events", slow_stream)
        delete = AsyncMock()
        monkeypatch.setattr(service, "delete_thread", delete)
        events = [json.loads(chunk.removeprefix("data: ")) async for chunk in service.sse_generator("u", "q", "t")]
        assert [event["type"] for event in events] == ["token", "error"]
        assert events[0]["content"] == "已生成部分"
        assert "超时" in events[-1]["content"] and "核对实际结果" in events[-1]["content"]
        assert len(calls) == 1 and closed == [True]
        assert not service._active_threads
        delete.assert_not_called()

        async def successful_stream(*args: object):
            yield ("token", "后续回答")

        monkeypatch.setattr(service, "stream_chat_events", successful_stream)
        next_events = [json.loads(chunk.removeprefix("data: ")) async for chunk in service.sse_generator("u", "q2", "t")]
        assert [event["type"] for event in next_events] == ["token", "done"]

    asyncio.run(run())


@pytest.mark.parametrize("error", [GraphRecursionError("private provider detail"), ModelCallLimitExceededError(6, 6, None, 6)])
def test_call_budget_failure_is_explicit_and_keeps_history(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """图与模型调用上限只影响当前请求，不泄露异常细节。"""
    async def run() -> None:
        service = chat_service.ChatService()

        async def limited_stream(*args: object):
            yield ("thinking", "")
            raise error

        monkeypatch.setattr(service, "stream_chat_events", limited_stream)
        events = [json.loads(chunk.removeprefix("data: ")) async for chunk in service.sse_generator("u", "q", "t")]
        assert [event["type"] for event in events] == ["thinking", "error"]
        assert "调用上限" in events[-1]["content"]
        assert "private provider detail" not in events[-1]["content"]
        assert not service._active_threads

    asyncio.run(run())


def test_graph_budget_is_passed_to_each_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实流入口传递有限的图预算并释放活动上下文。"""
    async def run() -> None:
        service = chat_service.ChatService()
        configs = []

        async def stream(inputs: dict, config: dict, **kwargs: object):
            configs.append(config)
            yield AIMessageChunk(content="回答"), {}

        ctx = SimpleNamespace(agent=SimpleNamespace(astream=stream))
        monkeypatch.setattr(service, "get_agent", AsyncMock(return_value=ctx))
        events = [event async for event in service.stream_chat_events("u", "q", "t")]
        assert configs[0]["recursion_limit"] == chat_service.CHAT_RECURSION_LIMIT
        assert events[-1] == ("token", "回答")
        assert not service._active_contexts

    asyncio.run(run())


def test_model_timeout_and_retry_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """只验证初始化参数，不连接模型或读取用户配置。"""
    from model import config

    monkeypatch.setattr(config, "read_json", lambda: {"api_key": "test-placeholder"})
    init = Mock()
    monkeypatch.setattr(config, "init_chat_model", init)
    config.init_chat()
    assert init.call_args.kwargs["timeout"] == 45.0
    assert init.call_args.kwargs["max_retries"] == 1


def test_real_middleware_blocks_excess_tools_and_resets_each_run() -> None:
    """使用内存 checkpoint 验证超额工具不执行，下轮预算重置而历史保留。"""
    from langchain.agents import create_agent
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.memory import InMemorySaver

    class LoopModel(FakeMessagesListChatModel):
        def bind_tools(self, tools: list, **kwargs: object) -> "LoopModel":
            return self

    calls = []

    @tool
    def lookup() -> str:
        """返回测试资料。"""
        calls.append(True)
        return "测试资料"

    model = LoopModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "lookup", "args": {}, "id": f"call-{index}", "type": "tool_call",
    }]) for index in range(4)])
    agent = create_agent(model, tools=[lookup], checkpointer=InMemorySaver(), middleware=[
        ModelCallLimitMiddleware(run_limit=2, exit_behavior="error"),
        ToolCallLimitMiddleware(run_limit=1, exit_behavior="continue"),
    ])
    config = {"configurable": {"thread_id": "budget-test"}}
    for index in range(2):
        with pytest.raises(ModelCallLimitExceededError):
            agent.invoke({"messages": [HumanMessage(content=f"问题{index}")]}, config)
        assert len(calls) == index + 1
    messages = agent.get_state(config).values["messages"]
    assert sum(isinstance(message, HumanMessage) for message in messages) == 2
    assert any(isinstance(message, ToolMessage) and message.status == "error" for message in messages)
