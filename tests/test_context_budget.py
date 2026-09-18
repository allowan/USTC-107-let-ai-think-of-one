"""上下文预算只影响请求，测试不连接实际模型或数据库。"""

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import Mock

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from main import ContextBudgetExceededError, ContextBudgetMiddleware
from server.services.chat_service import ChatService


def request_for(messages: list, **kwargs: object) -> ModelRequest:
    """构造独立模型请求。"""
    return ModelRequest(model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
                        messages=messages, system_message=SystemMessage(content="系统规则"),
                        tools=kwargs.get("tools", []))


def test_trim_whole_turns_and_preserve_parallel_tools() -> None:
    messages = [HumanMessage(content="旧" * 1000), AIMessage(content="旧回答"),
                HumanMessage(content="当前问题"), AIMessage(content="", tool_calls=[
                    {"name": "lookup", "args": {}, "id": "a"},
                    {"name": "lookup", "args": {}, "id": "b"}]),
                ToolMessage(content="资料A", tool_call_id="a"), ToolMessage(content="资料B", tool_call_id="b")]
    request = request_for(messages)
    request = request.override(system_message=SystemMessage(content="系统规则", name="rules", additional_kwargs={"custom": "kept"}))
    prepared = ContextBudgetMiddleware(600).prepare_request(request)
    assert prepared.messages == messages[2:]
    assert "系统规则" in prepared.system_message.content
    assert "较早的对话" in prepared.system_message.content
    assert prepared.system_message.name == "rules"
    assert prepared.system_message.additional_kwargs == {"custom": "kept"}
    assert request.messages == messages and request.system_message.content == "系统规则"


@pytest.mark.parametrize("kind", ["user", "tool", "system", "schema"])
def test_required_context_over_budget_never_calls_model(kind: str) -> None:
    messages = [HumanMessage(content="问题")]
    request = request_for(messages)
    if kind == "user":
        request = request.override(messages=[HumanMessage(content="问" * 2000)])
    elif kind == "tool":
        request = request.override(messages=[*messages, AIMessage(content="", tool_calls=[
            {"name": "lookup", "args": {}, "id": "a"}]), ToolMessage(content="资" * 2000, tool_call_id="a")])
    elif kind == "system":
        request = request.override(system_message=SystemMessage(content="规" * 2000))
    else:
        request = request.override(tools=[{"name": "lookup", "description": "x" * 2000}])
    handler = Mock()
    with pytest.raises(ContextBudgetExceededError):
        ContextBudgetMiddleware(500).wrap_model_call(request, handler)
    handler.assert_not_called()


def test_old_broken_tool_record_is_not_hidden_by_trimming() -> None:
    request = request_for([HumanMessage(content="旧" * 1000), AIMessage(content="", tool_calls=[
        {"name": "lookup", "args": {}, "id": "missing"}]), HumanMessage(content="新问题")])
    with pytest.raises(ValueError, match="tool_calls.*tool messages"):
        ContextBudgetMiddleware(500).prepare_request(request)


def test_sync_and_async_use_same_request() -> None:
    request = request_for([HumanMessage(content="旧" * 1000), AIMessage(content="旧回答"), HumanMessage(content="新问题")])
    middleware = ContextBudgetMiddleware(500)
    sync = middleware.wrap_model_call(request, lambda value: value)

    async def handler(value: ModelRequest) -> ModelRequest:
        return value

    asynchronous = asyncio.run(middleware.awrap_model_call(request, handler))
    assert asynchronous.messages == sync.messages
    assert asynchronous.system_message == sync.system_message


def test_real_agent_preserves_checkpoint_history() -> None:
    seen = []

    class RecordingModel(FakeMessagesListChatModel):
        def _generate(self, messages: list, *args: object, **kwargs: object) -> ChatResult:
            seen.append(messages)
            return super()._generate(messages, *args, **kwargs)

    agent = create_agent(RecordingModel(responses=[AIMessage(content="回答")]),
                         system_prompt="系统", checkpointer=InMemorySaver(),
                         middleware=[ContextBudgetMiddleware(500)])
    config = {"configurable": {"thread_id": "context-test"}}
    old = HumanMessage(content="旧" * 1000)
    agent.update_state(config, {"messages": [old, AIMessage(content="旧回答")]})
    agent.invoke({"messages": [HumanMessage(content="当前问题")]}, config)
    assert all(message.content != old.content for message in seen[-1])
    assert any(message.content == old.content for message in agent.get_state(config).values["messages"])
    with pytest.raises(ContextBudgetExceededError):
        agent.invoke({"messages": [HumanMessage(content="问" * 2000)]}, config)
    agent.invoke({"messages": [HumanMessage(content="后续小问题")]}, config)
    assert seen[-1][-1].content == "后续小问题"


def test_sse_budget_error_preserves_history_and_releases_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        service = ChatService()

        async def limited(*args: object) -> AsyncIterator[tuple[str, str]]:
            yield "thinking", ""
            raise ContextBudgetExceededError("private input")

        monkeypatch.setattr(service, "stream_chat_events", limited)
        deletion = Mock()
        monkeypatch.setattr(service, "delete_thread", deletion)
        events = [json.loads(chunk.removeprefix("data: ")) async for chunk in service.sse_generator("u", "q", "t")]
        assert [event["type"] for event in events] == ["thinking", "error"]
        assert "已有历史已保留" in events[-1]["content"] and "核对实际结果" in events[-1]["content"]
        assert "private input" not in events[-1]["content"]
        assert not service._active_threads
        deletion.assert_not_called()

    asyncio.run(run())
