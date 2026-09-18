"""事件评测的覆盖审计与质量门槛回归，仅覆盖守护读取仓库语料。"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def evaluator() -> ModuleType:
    """直接加载独立脚本，避免初始化 RAG 依赖。"""
    path = Path(__file__).resolve().parents[1] / "scripts" / "eval_events.py"
    spec = importlib.util.spec_from_file_location("event_evaluation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(tmp_path: Path, evaluator: ModuleType, sources: list[str]) -> list[str]:
    data = tmp_path / "corpus"
    data.mkdir()
    truth = {source: dict.fromkeys(evaluator.FIELDS) for source in sources}
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    return ["--truth", str(truth_path), "--data-dir", str(data)]


def test_missing_and_blank_sources_fail_coverage(
    tmp_path: Path, evaluator: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """缺失与空白真值文档都必须阻止不完整基线成功。"""
    args = _inputs(tmp_path, evaluator, ["found.txt", "missing.txt", "blank.txt"])
    (tmp_path / "corpus" / "found.txt").write_text("通知", encoding="utf-8")
    (tmp_path / "corpus" / "blank.txt").write_text("  ", encoding="utf-8")
    (tmp_path / "corpus" / "extra.txt").write_text("未标注", encoding="utf-8")
    monkeypatch.setattr(evaluator, "parse_notice", lambda *a, **kw: {})
    assert evaluator.main(args) == 1
    output = capsys.readouterr().out
    assert "预期 3 篇，实际 1 篇，缺失或空白 2 篇" in output
    assert "[missing] missing.txt" in output
    assert "[missing] blank.txt" in output
    assert "无真值 1 篇" in output


@pytest.mark.parametrize("threshold", ["--min-precision", "--min-recall"])
def test_mismatched_value_counts_against_both_metrics(
    tmp_path: Path, evaluator: ModuleType, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], threshold: str,
) -> None:
    """MM 同时降低精度和召回，质量门槛使用未舍入指标。"""
    args = _inputs(tmp_path, evaluator, ["a.txt", "b.txt"])
    truth_path = Path(args[1])
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    for source in truth:
        truth[source]["deadline"] = "2026-09-01"
        (tmp_path / "corpus" / source).write_text("通知", encoding="utf-8")
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    monkeypatch.setattr(evaluator, "parse_notice", lambda content, source, **kw: {
        "deadline": "2026-09-01" if source == "a.txt" else "2026-09-02",
    })
    assert evaluator.main(args + [threshold, "0.5"]) == 0
    assert evaluator.main(args + [threshold, "0.51"]) == 1
    assert "precision=0.5000, recall=0.5000" in capsys.readouterr().out


def test_empty_corpus_is_not_success(
    tmp_path: Path, evaluator: ModuleType, capsys: pytest.CaptureFixture[str],
) -> None:
    """零样本不能显示全部命中或返回成功。"""
    assert evaluator.main(_inputs(tmp_path, evaluator, ["missing.txt"])) == 1
    output = capsys.readouterr().out
    assert "没有可评测样本" in output
    assert "全部命中" not in output


@pytest.mark.parametrize("truth", [{}, [], {"a.txt": {}}, {"a.txt": None}])
def test_invalid_truth_returns_input_error(
    tmp_path: Path, evaluator: ModuleType, truth: object,
) -> None:
    """空真值或字段缺失不能被解释为全空字段正确。"""
    args = _inputs(tmp_path, evaluator, ["a.txt"])
    Path(args[1]).write_text(json.dumps(truth), encoding="utf-8")
    assert evaluator.main(args) == 2


@pytest.mark.parametrize("value", ["-0.1", "1.1", "nan"])
def test_invalid_threshold_is_rejected(evaluator: ModuleType, value: str) -> None:
    """阈值越界和非数字值不能绕过质量门槛。"""
    with pytest.raises(SystemExit) as exc:
        evaluator.main(["--min-recall", value])
    assert exc.value.code == 2


def test_repository_truth_sources_are_present(evaluator: ModuleType) -> None:
    """语料重命名必须同步真值键，避免真实基线悄悄丢失样本。"""
    truth = json.loads(evaluator.TRUTH_PATH.read_text(encoding="utf-8"))
    assert truth, "事件评测真值不能为空"
    for source in truth:
        path = evaluator.DATA_DIR / source
        assert path.is_file(), f"真值语料缺失：{source}"
        assert path.read_text(encoding="utf-8").strip(), f"真值语料为空：{source}"
