"""检索指标及生产 BM25 复用回归，不调用模型或读取真实数据库。"""

import json
from pathlib import Path
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


def test_corpus_audit_detects_missing_sources_and_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "first.txt"
    source.write_text("original", encoding="utf-8")
    truth = [{"query": "multi", "expect": ["first", "second"]}]
    before = eval_retrieval.audit_corpus(truth, tmp_path)
    assert before["missing_sources"] == ["second"]
    assert before["complete"] is False
    source.write_text("updated", encoding="utf-8")
    assert eval_retrieval.audit_corpus(truth, tmp_path)["sha256"] != before["sha256"]
    (tmp_path / "second.txt").write_text("second", encoding="utf-8")
    assert eval_retrieval.audit_corpus(truth, tmp_path)["complete"] is True
    (tmp_path / "second.txt").write_text("  \n", encoding="utf-8")
    assert eval_retrieval.audit_corpus(truth, tmp_path)["missing_sources"] == ["second"]


@pytest.mark.parametrize("missing, expected_code", [(False, 0), (True, 2)])
def test_audit_only_selects_holdout_without_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool, expected_code: int,
) -> None:
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps([
        {"query": "development", "expect": ["unavailable"]},
        {"query": "holdout", "expect": ["first"], "split": "holdout"},
    ]), encoding="utf-8")
    if not missing:
        (tmp_path / "first.txt").write_text("evidence", encoding="utf-8")
    monkeypatch.setattr(eval_retrieval, "TRUTH_PATH", truth_path)
    monkeypatch.setattr(eval_retrieval, "DATA_DIR", tmp_path)
    retrieve = Mock(side_effect=AssertionError("must not retrieve"))
    monkeypatch.setattr(eval_retrieval, "_ranked_sources", retrieve)
    output = tmp_path / "report.json"
    assert eval_retrieval.main(["--audit-only", "--split", "holdout", "--output", str(output)]) == expected_code
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["selected_count"] == 1
    assert report["split"] == "holdout"
    assert report["corpus"]["complete"] is not missing
    retrieve.assert_not_called()


def test_json_baseline_preserves_results_and_existing_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import campus_rag

    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps([{"query": "test", "expect": ["first"]}]), encoding="utf-8")
    (tmp_path / "first.txt").write_text("evidence", encoding="utf-8")
    monkeypatch.setattr(eval_retrieval, "TRUTH_PATH", truth_path)
    monkeypatch.setattr(eval_retrieval, "DATA_DIR", tmp_path)
    monkeypatch.setattr(campus_rag, "create_keyword_search", Mock(return_value=Mock()))
    monkeypatch.setattr(eval_retrieval, "_ranked_sources", Mock(return_value=["first.txt"]))
    output = tmp_path / "report.json"
    assert eval_retrieval.main(["--output", str(output)]) == 0
    saved = output.read_text(encoding="utf-8")
    report = json.loads(saved)
    assert report["status"] == "completed"
    assert report["summary"]["recall"]["10"] == 1.0
    assert report["rows"][0]["sources"] == ["first.txt"]
    assert report["index_seconds"] >= 0
    with pytest.raises(SystemExit):
        eval_retrieval.main(["--output", str(output)])
    assert output.read_text(encoding="utf-8") == saved


def test_missing_corpus_blocks_index_initialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import campus_rag

    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps([{"query": "test", "expect": ["absent"]}]), encoding="utf-8")
    monkeypatch.setattr(eval_retrieval, "TRUTH_PATH", truth_path)
    monkeypatch.setattr(eval_retrieval, "DATA_DIR", tmp_path)
    build = Mock(side_effect=AssertionError("must not initialize"))
    monkeypatch.setattr(campus_rag, "create_keyword_search", build)
    assert eval_retrieval.main([]) == 2
    build.assert_not_called()
