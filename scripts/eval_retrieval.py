"""复用生产检索的离线 BM25 / 在线混合检索评测。

expect 中每个子串都是一个必需来源；expect=[] 是库内无答案负例。
来源命中不代表答案、日期或适用人群正确，需另行审查答案。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
TRUTH_PATH = ROOT / "tests" / "retrieval_ground_truth.json"
DATA_DIR = ROOT / "campus_rag" / "data"
K_VALUES = (1, 3, 5, 10)
TOP_K = max(K_VALUES)


def audit_corpus(truth: list[dict], data_dir: Path) -> dict:
    """核对必需来源并记录内容指纹，避免把不同语料的结果直接比较。"""
    files = sorted(data_dir.glob("*.txt"), key=lambda path: path.name)
    digest = hashlib.sha256()
    nonempty = []
    for path in files:
        content = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        if content.decode("utf-8-sig").strip():
            nonempty.append(path.name)
    expected = sorted({source for item in truth for source in item["expect"]})
    missing = [source for source in expected if not any(source in name for name in nonempty)]
    return {"file_count": len(files), "sha256": digest.hexdigest(),
            "expected_source_count": len(expected), "missing_sources": missing,
            "complete": bool(nonempty) and not missing,
            "scope": "local_text_files_not_vector_index"}


def write_report(path: Path, report: dict) -> None:
    """保存独立结果；拒绝覆盖已有文件以保留历史基线。"""
    with path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _ranked_sources(
    query: str, *, hybrid: bool = False, rerank: bool = True,
    keyword_search: Callable | None = None,
) -> list[str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if hybrid:
        from campus_rag import retrieve_notice_nodes

        warnings: list[str] = []
        nodes = retrieve_notice_nodes(query, top_k=TOP_K, rerank=rerank, warnings=warnings)
        if warnings:
            raise RuntimeError("混合检索发生降级，不能计入完整混合检索基线")
    else:
        from campus_rag import search_keyword_nodes

        nodes = (keyword_search(query, TOP_K) if keyword_search else
                 search_keyword_nodes(query, data_dir=str(DATA_DIR), top_k=TOP_K))
    return [str(node.node.metadata.get("source", "")) for node in nodes]


def _first_hit_rank(ranked_sources: list[str], expect: list[str]) -> int | None:
    for rank, source in enumerate(ranked_sources, start=1):
        if any(expected in source for expected in expect):
            return rank
    return None


def evaluate(truth: list[dict], retrieve: Callable[[str], list[str]]) -> list[dict]:
    """记录逐条检索结果和耗时，错误单独记录且不视作成功拒答。"""
    rows = []
    for item in truth:
        started = perf_counter()
        error = None
        try:
            sources = retrieve(item["query"])[:TOP_K]
        except Exception as exc:
            # 评测需保留失败样本并继续下一条，避免服务异常导致指标虚高。
            error = type(exc).__name__
            print(f"[error] 检索失败：{item['query']} ({error})")
            sources = []
        rows.append({**item, "category": item.get("category", "general"), "sources": sources,
                     "error": error, "seconds": perf_counter() - started})
    return rows


def summarize(rows: list[dict]) -> dict:
    """计算正例宏平均指标及成功执行的负例误召回率。"""
    positives = [row for row in rows if row["expect"]]
    negatives = [row for row in rows if not row["expect"] and row["error"] is None]
    count = len(positives)
    hits = {}
    recall = {}
    for k in K_VALUES:
        hits[k] = sum(_first_hit_rank(row["sources"][:k], row["expect"]) is not None
                      for row in positives) / count if count else 0.0
        recall[k] = sum(sum(any(expected in source for source in row["sources"][:k])
                                   for expected in row["expect"]) / len(row["expect"])
                        for row in positives) / count if count else 0.0
    rr = sum(1 / rank if (rank := _first_hit_rank(row["sources"], row["expect"])) else 0
             for row in positives)
    elapsed = [row["seconds"] for row in rows]
    return {"positive_count": count, "negative_count": len(negatives),
            "errors": sum(row["error"] is not None for row in rows),
            "hit": hits, "recall": recall, "mrr": rr / count if count else 0.0,
            "false_retrieval": sum(bool(row["sources"]) for row in negatives) / len(negatives) if negatives else None,
            "seconds_total": sum(elapsed), "seconds_mean": sum(elapsed) / len(elapsed) if elapsed else 0.0,
            "seconds_max": max(elapsed, default=0.0)}


def main(argv: list[str] | None = None) -> int:
    """输出总体和分类指标，检索发生错误时返回非零退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hybrid", "--vector", action="store_true", help="混合检索，需要嵌入服务；--vector 为兼容别名")
    parser.add_argument("--no-rerank", action="store_true", help="关闭混合检索重排序")
    parser.add_argument("--split", choices=("all", "development", "holdout"), default="all", help="固定开发集或留出集；未标注样本归开发集")
    parser.add_argument("--audit-only", action="store_true", help="仅核对语料覆盖，不初始化检索或调用服务")
    parser.add_argument("--output", type=Path, help="保存 JSON 基线（必须是尚不存在的文件）")
    args = parser.parse_args(argv)
    truth_bytes = TRUTH_PATH.read_bytes()
    truth = json.loads(truth_bytes)
    if args.split != "all":
        truth = [item for item in truth if item.get("split", "development") == args.split]
    if not truth:
        parser.error("真值集为空")
    if args.output and args.output.exists():
        parser.error("结果文件已存在，请选择新文件以保留历史基线")
    corpus = audit_corpus(truth, DATA_DIR)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "hybrid" if args.hybrid else "bm25", "split": args.split,
              "rerank": args.hybrid and not args.no_rerank, "top_k": TOP_K,
              "python_version": sys.version.split()[0],
              "generation_model": None,
              "model_configuration": "not_recorded" if args.hybrid else "not_used",
              "truth_sha256": hashlib.sha256(truth_bytes).hexdigest(),
              "selected_count": len(truth), "corpus": corpus,
              "status": "audit_only" if corpus["complete"] else "incomplete_corpus"}
    print(f"语料审计：{corpus['file_count']} 篇，必需来源 {corpus['expected_source_count']}，缺失 {len(corpus['missing_sources'])}")
    for source in corpus["missing_sources"]:
        print(f"  缺失来源：{source}")
    if args.audit_only or not corpus["complete"]:
        if args.output:
            write_report(args.output, report)
        return 0 if corpus["complete"] else 2
    print("模式：" + ("生产混合检索" if args.hybrid else "生产 BM25（离线，不调用嵌入/LLM）"))
    keyword_search = None
    index_seconds = None
    if not args.hybrid:
        sys.path.insert(0, str(ROOT))
        from campus_rag import create_keyword_search

        started = perf_counter()
        keyword_search = create_keyword_search(data_dir=str(DATA_DIR))
        index_seconds = perf_counter() - started
        print(f"离线索引构建耗时：{index_seconds:.2f}s（不计入查询耗时）")
    rows = evaluate(truth, lambda query: _ranked_sources(
        query, hybrid=args.hybrid, rerank=not args.no_rerank, keyword_search=keyword_search,
    ))
    result = summarize(rows)
    print(f"\n样本 {len(rows)}；正例 {result['positive_count']}；成功执行负例 {result['negative_count']}；错误 {result['errors']}")
    for k in K_VALUES:
        print(f"Hit@{k:<2} {result['hit'][k]:.1%}  Recall@{k:<2} {result['recall'][k]:.1%}")
    print(f"MRR@10 {result['mrr']:.3f}")
    false_rate = result["false_retrieval"]
    print("无答案误召回率：" + (f"{false_rate:.1%}" if false_rate is not None else "N/A"))
    timing_scope = "混合模式含首次初始化" if args.hybrid else "已复用离线索引"
    print(f"查询耗时（{timing_scope}）：总计 {result['seconds_total']:.2f}s，均值 {result['seconds_mean']:.3f}s，最大 {result['seconds_max']:.3f}s")
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["category"]].append(row)
    for category, members in groups.items():
        group = summarize(members)
        negative_rate = group['false_retrieval']
        negative_text = f"{negative_rate:.1%}" if negative_rate is not None else "N/A"
        print(f"  {category}: n={len(members)} Hit@10={group['hit'][10]:.1%} Recall@10={group['recall'][10]:.1%} MRR={group['mrr']:.3f} 负例误召回={negative_text} 错误={group['errors']}")
    print("\n未完整召回 / 负例误召回：")
    for row in rows:
        missing = [expected for expected in row["expect"] if not any(expected in source for source in row["sources"])]
        if missing or (not row["expect"] and row["sources"]):
            print(f"  {row['query']} → " + (f"缺少 {missing}" if missing else "无答案仍返回候选"))
    print("说明：负例返回候选不等于最终回答幻觉；日期、适用人群、答案正确性须另行审查。")
    report.update({"status": "retrieval_errors" if result["errors"] else "completed",
                   "index_seconds": index_seconds, "summary": result,
                   "categories": {category: summarize(members) for category, members in groups.items()},
                   "rows": rows})
    if args.output:
        write_report(args.output, report)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
