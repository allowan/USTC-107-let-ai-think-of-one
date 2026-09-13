"""检索指标及生产 BM25 复用回归，不调用模型或读取真实数据库。"""

from unittest.mock import Mock

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from campus_rag import query
from scripts import eval_retrieval


def test_hit_and_multi_source_recall_are_distinct() -> None:
    rows = eval_retrieval.evaluate([
        {"query": "multi", "expect": ["first", "second"]},
        {"query": "negative", "expect": []},
    ], lambda text: ["first.txt"])
    summary = eval_retrieval.summarize(rows)
    assert summary["hit"][1] == 1.0
    assert summary["recall"][1] == 0.5
    assert summary["mrr"] == 1.0
    assert summary["false_retrieval"] == 1.0


def test_failed_negative_is_not_counted_as_correct_rejection() -> None:
    rows = eval_retrieval.evaluate([{"query": "failed", "expect": []}], Mock(side_effect=OSError("offline")))
    summary = eval_retrieval.summarize(rows)
    assert summary["negative_count"] == 0
    assert summary["false_retrieval"] is None
    assert summary["errors"] == 1


def test_batch_keyword_search_reuses_production_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_rag import keyword_retriever

    nodes = [TextNode(text="alpha", metadata={"source": "first.txt"})]
    read = Mock(return_value=nodes)
    monkeypatch.setattr(query, "read_collection_nodes", read)
    build = Mock(wraps=keyword_retriever.BM25Retriever)
    monkeypatch.setattr(keyword_retriever, "BM25Retriever", build)
    search = query.create_keyword_search()
    assert search("alpha", 10)[0].node.metadata["source"] == "first.txt"
    assert not search("zxqv9387", 10)
    assert not search("!!!", 10)
    read.assert_called_once_with(None)
    assert build.call_count == 1


def test_ranked_sources_use_given_production_query_function() -> None:
    search = Mock(return_value=[NodeWithScore(node=TextNode(text="a", metadata={"source": "first.txt"}))])
    assert eval_retrieval._ranked_sources("a", keyword_search=search) == ["first.txt"]
    search.assert_called_once_with("a", 10)


def test_hybrid_degradation_is_not_a_successful_hybrid_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    import campus_rag

    def degraded(text: str, **kwargs: object) -> list:
        kwargs["warnings"].append("降级")
        return []

    monkeypatch.setattr(campus_rag, "retrieve_notice_nodes", degraded)
    with pytest.raises(RuntimeError, match="降级"):
        eval_retrieval._ranked_sources("a", hybrid=True)
