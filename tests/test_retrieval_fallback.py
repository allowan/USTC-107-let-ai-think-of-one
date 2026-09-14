"""检索故障隔离回归：只用内存替身，不读取真实集合、配置或模型。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from campus_rag import config, index_manager, query, query_engine


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "_rag", None)
    monkeypatch.setattr(query, "_public_index", None)
    monkeypatch.setattr(query, "_user_indexes", {})
    monkeypatch.setattr(query_engine, "_get_reranker", lambda: None)
    monkeypatch.setattr(index_manager, "_embed_dim_cache", None)
    monkeypatch.setattr(index_manager, "_DEFAULT_PERSIST_DIR", str(Path(__file__).parent))
    monkeypatch.setattr(index_manager, "_get_chroma_client", Mock(side_effect=AssertionError("unexpected storage")))
    monkeypatch.setattr(config, "init_embed", Mock(side_effect=AssertionError("unexpected embedding")))
    query_engine.reset_caches()


def _node(source: str = "notice") -> TextNode:
    return TextNode(text="quantum scholarship", metadata={"source": source})


def test_hot_vector_failure_keeps_keyword_and_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    node = _node()
    index = SimpleNamespace(vector_store=SimpleNamespace(get_nodes=lambda **kw: [node]))
    monkeypatch.setattr(query, "_public_index", index)
    monkeypatch.setattr(query, "_rag", object())
    monkeypatch.setattr(query_engine, "_get_cached_retriever", lambda *args: Mock(retrieve=Mock(side_effect=OSError("offline"))))
    result = query.search_notices("quantum")
    assert "降级为关键词检索" in result
    assert "[来源: notice]" in result


def test_keyword_failure_keeps_vector_and_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    node = _node()
    monkeypatch.setattr(query_engine, "_get_cached_retriever", lambda *args: Mock(retrieve=Mock(return_value=[NodeWithScore(node=node, score=0.8)])))
    monkeypatch.setattr(query_engine, "_get_bm25_cached", Mock(side_effect=OSError("read failed")))
    warnings: list[str] = []
    result = query_engine.retrieve_nodes("quantum", public_index=object(), warnings=warnings)
    assert result[0].node is node
    assert "降级为向量检索" in warnings[0]


@pytest.mark.parametrize("failure", ["initialization", "dimension"])
def test_cold_failure_reads_existing_collection_only(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    node = _node()
    collection = SimpleNamespace(count=lambda: 1, peek=lambda: {"embeddings": [[1, 2, 3]]})
    client = Mock(get_collection=Mock(return_value=collection))
    monkeypatch.setattr(index_manager, "_get_chroma_client", lambda: client)
    monkeypatch.setattr(index_manager, "ChromaVectorStore", lambda **kw: SimpleNamespace(get_nodes=lambda **kw: [node]))
    monkeypatch.setattr(config, "init_embed", lambda: failure == "dimension")
    monkeypatch.setattr(config, "require_embed_model", Mock(side_effect=OSError("dimension probe offline")))
    # RAGSystem 传入默认目录；只读函数不传参数。
    monkeypatch.setattr(index_manager, "_get_chroma_client", lambda *args: client)
    result = query.search_notices("quantum")
    assert "降级为关键词检索" in result
    assert "quantum scholarship" in result
    assert query._public_index is None
    client.get_collection.assert_called_with("public", embedding_function=None)
    client.get_or_create_collection.assert_not_called()
    client.delete_collection.assert_not_called()


def test_cold_personal_fallback_is_user_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    selected: list[str] = []

    def get_collection(name: str, **kwargs: object) -> str:
        selected.append(name)
        return name

    monkeypatch.setattr(config, "init_embed", lambda: False)
    monkeypatch.setattr(index_manager, "_get_chroma_client", lambda: SimpleNamespace(get_collection=get_collection))
    monkeypatch.setattr(index_manager, "ChromaVectorStore", lambda chroma_collection: SimpleNamespace(get_nodes=lambda **kw: [_node(chroma_collection)]))
    result = query.search_user_data("quantum", "alice")
    assert selected == ["user_alice"]
    assert "user_alice" in result
    assert "public" not in result and "user_bob" not in result


def test_both_failures_are_not_reported_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "init_embed", lambda: False)
    monkeypatch.setattr(query, "read_collection_nodes", Mock(side_effect=OSError("broken storage")))
    with pytest.raises(RuntimeError, match="均失败"):
        query.search_notices("quantum")


def test_degraded_empty_result_retains_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "init_embed", lambda: False)
    monkeypatch.setattr(query, "read_collection_nodes", lambda: [])
    result = query.search_notices("quantum")
    assert "降级" in result and "未在通知中找到" in result


def test_write_dimension_guard_still_rejects_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = SimpleNamespace(count=lambda: 1, peek=lambda: {"embeddings": [[1, 2, 3]]})
    instance = object.__new__(index_manager.RAGSystem)
    instance.chroma_client = Mock(get_or_create_collection=Mock(return_value=collection))
    monkeypatch.setattr(config, "require_embed_model", Mock(side_effect=OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        instance.add_user_documents("alice", [])


def test_answer_preserves_degradation_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "init_embed", lambda: False)
    monkeypatch.setattr(query, "read_collection_nodes", lambda: [_node()])
    monkeypatch.setattr(config, "require_llm", lambda: SimpleNamespace(chat=lambda messages: SimpleNamespace(message=SimpleNamespace(content="回答"))))
    answer = query.search_notices_answer("quantum")
    assert "降级" in answer and answer.endswith("回答")


def test_hot_both_failures_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_engine, "_get_cached_retriever", Mock(side_effect=OSError("offline")))
    monkeypatch.setattr(query_engine, "_get_bm25_cached", Mock(side_effect=OSError("storage failed")))
    with pytest.raises(RuntimeError, match="均失败"):
        query_engine.retrieve_nodes("quantum", public_index=object())


def test_keyword_public_api_uses_production_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = Mock(return_value=[_node()])
    monkeypatch.setattr(query, "read_collection_nodes", reader)
    assert query.search_keyword_nodes("unrelated") == []
    nodes = query.search_keyword_nodes("quantum", user_id="alice")
    assert nodes[0].metadata["source"] == "notice"
    reader.assert_called_with("alice")
    with pytest.raises(ValueError, match="不能同时指定"):
        query.search_keyword_nodes("quantum", user_id="alice", data_dir="corpus")
