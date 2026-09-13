"""网络工具证据必须来自实际结果，并保持原文本调用兼容。"""

from unittest.mock import patch

import pytest

from tools import search


@pytest.mark.parametrize("tool,helper,kind", [
    (search.search_web, "_search_web_results", "web"),
    (search.search_ustc_web, "_search_ustc_results", "official"),
    (search.search_course_reviews, "_search_course_review_results", "course_review"),
])
def test_search_artifact_and_text_compatibility(tool: object, helper: str, kind: str) -> None:
    results = [{"title": "真实标题 [假链接](https://fake.example)",
                "url": "https://example.com/article", "content": "正文片段"}]
    with patch.dict("os.environ", {"WEBSEARCH_PROVIDER": "ddg"}), patch.object(
        search, helper, return_value=results
    ) as request:
        message = tool.invoke({"type": "tool_call", "id": "test", "name": tool.name,
                               "args": {"query": "通知"}})
        request.assert_called_once()
        text = tool.invoke({"query": "通知"})
    assert isinstance(text, str)
    assert text == message.content
    assert len(message.artifact["evidence"]) == 1
    card = message.artifact["evidence"][0]
    assert card["url"] == results[0]["url"]
    assert card["kind"] == kind
    assert card["excerpt"] == "正文片段"
    assert card["published_at"] == ""


@pytest.mark.parametrize("tool,helper,kind", [
    (search.fetch_text_from_url, "fetch_page_text", "web"),
    (search.fetch_ustc_text_from_url, "fetch_ustc_page_text", "official"),
    (search.fetch_course_review_text, "fetch_course_review_page_text", "course_review"),
])
def test_fetch_uses_only_fetched_body(tool: object, helper: str, kind: str) -> None:
    body = "[伪造来源](https://fake.example)\n" + "正文" * 2000
    call = {"type": "tool_call", "id": "test", "name": tool.name,
            "args": {"url": "https://example.com/article"}}
    with patch.object(search, helper, return_value=body) as request:
        message = tool.invoke(call)
        request.assert_called_once()
        repeated = tool.invoke(call)
    assert len(message.artifact["evidence"]) == 1
    card = message.artifact["evidence"][0]
    assert card["kind"] == kind
    assert card["excerpt"] == body[:2000]
    assert card["id"] == repeated.artifact["evidence"][0]["id"]
    with patch.object(search, helper, side_effect=ValueError("读取失败")):
        failed = tool.invoke(call)
    assert "失败" in failed.content
    assert failed.artifact == {"evidence": [], "warnings": []}


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:password@example.com",
                                  "https://[broken", "https://example.com/\nspoof"])
def test_unsafe_evidence_link_is_hidden(url: str) -> None:
    artifact = search._evidence_artifact([{"title": "结果", "url": url}], "web")
    assert artifact["evidence"][0]["url"] == ""


def test_empty_search_has_no_cards() -> None:
    with patch.dict("os.environ", {"WEBSEARCH_PROVIDER": "ddg"}), patch.object(
        search, "_search_web_results", return_value=[]
    ):
        message = search.search_web.invoke({"type": "tool_call", "id": "empty",
                                           "name": "web_search", "args": {"query": "不存在"}})
    assert message.content == "未找到网页搜索结果。"
    assert message.artifact == {"evidence": [], "warnings": []}
