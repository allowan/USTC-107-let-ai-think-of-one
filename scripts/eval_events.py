"""事件抽取质量评测：对比 campus_rag/data 真值与 parse_notice 输出。

用法：python scripts/eval_events.py

输出逐条命中明细 + 各字段 P/R 汇总。真值见 tests/events_ground_truth.json。
该脚本是迭代抽取正则的靶子，不是 pytest 单测——语料或真值变化后直接重跑。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 直接加载 events.py，绕开 campus_rag/__init__（后者会拖入 llama_index），
# 使评测脚本仅依赖标准库，随时可跑。
_spec = importlib.util.spec_from_file_location(
    "campus_rag_events", ROOT / "campus_rag" / "events.py"
)
events = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(events)
parse_notice = events.parse_notice

TRUTH_PATH = ROOT / "tests" / "events_ground_truth.json"
DATA_DIR = ROOT / "campus_rag" / "data"

# 用 today=2026-08-15 评估：选一个多数通知发布日之后的时点，
# 使"未来截止/事件"判定接近真实使用场景（开学季前夕）。
EVAL_TODAY = date(2026, 8, 15)

FIELDS = ("category", "publish_date", "deadline", "event_start", "event_end", "location")


def _load_corpus(data_dir: Path) -> list[tuple[str, str]]:
    """读 data 目录下所有 .txt，返回 [(source, content), ...]。"""
    out = []
    for fname in sorted(os.listdir(str(data_dir))):
        if not fname.endswith(".txt"):
            continue
        with open(data_dir / fname, encoding="utf-8") as f:
            content = f.read()
        if content.strip():
            out.append((fname, content))
    return out


def _norm(s: str | None) -> str | None:
    """空白归一化：评测时忽略全半角空格差异。"""
    if s is None:
        return None
    return "".join(s.split()) or None


def _eval_field(name: str, got: str | None, truth: str | None) -> str:
    """返回 'TP'/'FP'/'FN'/'OK'(均空)。"""
    g, t = _norm(got), _norm(truth)
    if t is None and g is None:
        return "OK"
    if t is None and g is not None:
        return "FP"   # 抽出了不该有的（假阳性）
    if t is not None and g is None:
        return "FN"   # 该抽没抽（假阴性）
    return "TP" if g == t else "MM"   # 抽了但值不对


def _ratio(value: str) -> float:
    ratio = float(value)
    if not 0 <= ratio <= 1:
        raise argparse.ArgumentTypeError("阈值必须在 0 到 1 之间")
    return ratio


def main(argv: list[str] | None = None) -> int:
    """运行只读评测；覆盖或质量失败返回 1，输入无效返回 2。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, default=TRUTH_PATH)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--today", type=date.fromisoformat, default=EVAL_TODAY)
    parser.add_argument("--min-precision", type=_ratio, default=0.0)
    parser.add_argument("--min-recall", type=_ratio, default=0.0)
    args = parser.parse_args(argv)
    print(f"配置：truth={args.truth.resolve()}, data_dir={args.data_dir.resolve()}, "
          f"today={args.today}, min_precision={args.min_precision}, min_recall={args.min_recall}")
    try:
        truth = json.loads(args.truth.read_text(encoding="utf-8"))
        if not isinstance(truth, dict) or not truth:
            raise ValueError("真值必须是非空的来源到字段对象映射")
        for source, fields in truth.items():
            if not isinstance(fields, dict) or any(
                field not in fields or (fields[field] is not None and not isinstance(fields[field], str))
                for field in FIELDS
            ):
                raise ValueError(f"真值字段缺失或类型无效：{source}")
        corpus = _load_corpus(args.data_dir)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[error] 无法运行评测：{exc}", file=sys.stderr)
        return 2

    sources = {source for source, _ in corpus}
    missing = sorted(set(truth) - sources)
    matched = set(truth) & sources
    print(f"覆盖：预期 {len(truth)} 篇，实际 {len(matched)} 篇，"
          f"缺失或空白 {len(missing)} 篇，覆盖率 {len(matched) / len(truth):.1%}；"
          f"无真值 {len(sources - set(truth))} 篇")
    for source in missing:
        print(f"[missing] {source}")
    failures = []
    if missing or not matched:
        failures.append("真值语料覆盖不完整；以下指标仅代表已匹配样本，不能作为完整基线")

    # 逐字段统计
    stats = {f: {"TP": 0, "FP": 0, "FN": 0, "MM": 0, "OK": 0} for f in FIELDS}
    per_doc: list[dict] = []

    for src, content in corpus:
        t = truth.get(src)
        if t is None:
            print(f"[warn] 无真值，跳过：{src}")
            continue
        got = parse_notice(content, src, today=args.today)
        row = {"source": src, "fields": {}}
        for f in FIELDS:
            verdict = _eval_field(f, got.get(f), t.get(f))
            row["fields"][f] = (got.get(f), t.get(f), verdict)
            if verdict in stats[f]:
                stats[f][verdict] += 1
        per_doc.append(row)

    # 汇总
    print(f"\n=== 事件抽取评测（today={args.today}, 语料 {len(per_doc)} 篇）===\n")
    print(f"{'字段':<14}{'TP':>5}{'FP':>5}{'FN':>5}{'MM':>5}{'精度':>8}{'召回':>8}")
    for f in FIELDS:
        s = stats[f]
        tp, fp, fn, mm = s["TP"], s["FP"], s["FN"], s["MM"]
        prec = tp / (tp + fp + mm) if (tp + fp + mm) else 1.0
        rec = tp / (tp + fn + mm) if (tp + fn + mm) else 1.0
        print(f"{f:<14}{tp:>5}{fp:>5}{fn:>5}{mm:>5}{prec:>8.1%}{rec:>8.1%}")
        if prec < args.min_precision or rec < args.min_recall:
            failures.append(f"{f} 未达到质量门槛：precision={prec:.4f}, recall={rec:.4f}")

    # 明细：只列有偏差的字段
    print("\n=== 偏差明细（仅 FN/FP/MM）===\n")
    any_diff = False
    for row in per_doc:
        diffs = {f: v for f, v in row["fields"].items() if v[2] in ("FN", "FP", "MM")}
        if not diffs:
            continue
        any_diff = True
        print(f"[{row['source'][:60]}]")
        for f, (g, t, v) in diffs.items():
            print(f"  {f:<12} {v:<3} got={g!r} truth={t!r}")
    if not per_doc:
        print("（没有可评测样本）")
    elif not any_diff:
        print("（无偏差，全部命中）")

    for failure in failures:
        print(f"[fail] {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
