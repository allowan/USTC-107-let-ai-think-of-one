"""证据贯穿检索、工具、消息流与历史；全部在内存中执行。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from llama_index.core.schema import NodeWithScore, TextNode

import main
from campus_rag import config, query
from server.services.chat_service import ChatService, merge_evidence


def _artifact(identifier: str = "one") -> dict:
    return {"evidence": [{
        "id": identifier, "source": "通知.txt", "title": "奖学金通知",
        "url": "https://example.edu/notice", "published_at": "2026-09-12",
        "excerpt": "申请截止日期为9月20日", "kind": "official",
    }], "warnings": []}


@pytest.mark.parametrize("personal", [False, True])
def test_evidence_uses_one_retrieval_without_llm(
    monkeypatch: pytest.MonkeyPatch, personal: bool,
) -> None:
    node = NodeWithScore(node=TextNode(
        id_="stable-node", text="标题：奖学金通知\n发布日期：2026-09-12\n真实正文",
        metadata={"source": "目录/通知.txt", "url": "https://example.edu/notice",
                  "private_token": "SECRET", "local_path": "PRIVATE-PATH"},
    ), score=0.8)
    retrieve = Mock(return_value=[node])
    monkeypatch.setattr(query, "retrieve_user_nodes" if personal else "retrieve_notice_nodes", retrieve)
    monkeypatch.setattr(config, "require_llm", Mock(side_effect=AssertionError("nested LLM")))
    content, artifact = (query.search_user_data_with_evidence("问题", "alice") if personal
                         else query.search_notices_with_evidence("问题"))
    assert retrieve.call_count == 1
    assert retrieve.call_args.args == (("问题", "alice") if personal else ("问题",))
    item = artifact["evidence"][0]
    assert item["source"] == "目录/通知.txt"
    assert item["title"] == "奖学金通知" and item["published_at"] == "2026-09-12"
    assert item["kind"] == ("personal" if personal else "official")
    assert "真实正文" in content and "真实正文" in item["excerpt"]
    assert f"[证据:{item['id']}]" in content
    assert "SECRET" not in json.dumps(artifact) + content
    assert "PRIVATE-PATH" not in json.dumps(artifact) + content


def test_multiple_fragments_keep_distinct_citation_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一来源的不同片段必须能逐个对应，普通搜索接口保持原格式。"""
    nodes = [NodeWithScore(node=TextNode(id_=str(i), text=f"片段{i}",
             metadata={"source": "通知.txt"})) for i in range(2)]
    monkeypatch.setattr(query, "retrieve_notice_nodes", Mock(return_value=nodes))
    content, artifact = query.search_notices_with_evidence("问题")
    ids = [item["id"] for item in artifact["evidence"]]
    assert len(set(ids)) == 2
    assert content.index(ids[0]) < content.index("片段0") < content.index(ids[1]) < content.index("片段1")
    assert "[证据:" not in query.search_notices("问题")
    assert query.search_notices_with_evidence("问题")[1] == artifact


def test_empty_retrieval_preserves_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def retrieve(text: str, *, warnings: list[str]) -> list:
        warnings.append("向量不可用，已降级")
        return []

    monkeypatch.setattr(query, "retrieve_notice_nodes", retrieve)
    content, artifact = query.search_notices_with_evidence("问题")
    assert "降级" in content
    assert artifact == {"evidence": [], "warnings": ["向量不可用，已降级"]}


def test_tool_call_retains_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _artifact()
    monkeypatch.setattr(main, "search_notices_with_evidence", lambda text: ("正文", artifact))
    message = main.search_campus_notices.invoke({
        "type": "tool_call", "name": main.search_campus_notices.name,
        "id": "call-one", "args": {"query": "问题"},
    })
    assert isinstance(message, ToolMessage)
    assert message.content == "正文" and message.artifact == artifact
    assert message.tool_call_id == "call-one"


def test_merge_filters_metadata_and_unsafe_urls() -> None:
    artifact = _artifact()
    artifact["secret"] = "SECRET"
    artifact["evidence"][0].update(secret="SECRET", url="https://user:password@example.edu")
    merged = merge_evidence(artifact, artifact)
    assert len(merged["evidence"]) == 1
    assert merged["evidence"][0]["url"] == ""
    assert "SECRET" not in json.dumps(merged)


def test_history_groups_evidence_per_turn_and_keeps_old_messages() -> None:
    artifact = _artifact()
    messages = [
        HumanMessage(content="旧问题"), AIMessage(content="旧回答"),
        HumanMessage(content="问题一"), AIMessage(content=""),
        ToolMessage(content="内部正文", tool_call_id="one", artifact=artifact),
        ToolMessage(content="重复工具", tool_call_id="two", artifact=artifact),
        AIMessage(content="第一段"), AIMessage(content="第二段"),
        HumanMessage(content="问题二"),
        ToolMessage(content="失败正文", tool_call_id="bad", status="error", artifact=_artifact("bad")),
        ToolMessage(content="内部正文", tool_call_id="three", artifact=artifact),
        AIMessage(content="第二回合回答"),
    ]
    history = main._checkpoint_messages_to_history(messages)
    assert history[:2] == [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}]
    assert history[3]["content"] == "第一段\n\n第二段"
    assert history[3]["evidence"] == artifact["evidence"]
    assert history[5]["evidence"] == artifact["evidence"]
    assert "内部正文" not in json.dumps(history, ensure_ascii=False)
    assert "bad" not in json.dumps(history)


def test_stream_tool_messages_emit_evidence_and_ignore_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stream(*args: object, **kwargs: object):
        assert kwargs["stream_mode"] == "messages"
        yield ToolMessage(content="内部正文", tool_call_id="one", artifact=_artifact()), {}
        yield ToolMessage(content="失败正文", tool_call_id="bad", status="error", artifact=_artifact("bad")), {}
        yield AIMessageChunk(content="回答"), {}

    service = ChatService()
    monkeypatch.setattr(service, "get_agent", AsyncMock(return_value=SimpleNamespace(agent=SimpleNamespace(astream=stream))))

    async def collect() -> list:
        return [json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in service.sse_generator("alice", "问题", "topic")]

    events = asyncio.run(collect())
    evidence = [event for event in events if event["type"] == "evidence"]
    assert len(evidence) == 1
    assert "bad" not in json.dumps(events)
    assert events[-1]["type"] == "done"
    assert service._active_contexts == {}


def test_real_langgraph_messages_stream_contains_tool_artifact() -> None:
    artifact = _artifact()

    def emit_tool(state: MessagesState) -> dict:
        return {"messages": [ToolMessage(content="正文", tool_call_id="one", artifact=artifact)]}

    builder = StateGraph(MessagesState)
    builder.add_node("tool", emit_tool)
    builder.add_edge(START, "tool")
    builder.add_edge("tool", END)
    graph = builder.compile()

    async def collect() -> list:
        return [message async for message, metadata in graph.astream(
            {"messages": [HumanMessage(content="问题")]}, stream_mode="messages",
        )]

    messages = asyncio.run(collect())
    tools = [message for message in messages if isinstance(message, ToolMessage)]
    assert len(tools) == 1 and tools[0].artifact == artifact
