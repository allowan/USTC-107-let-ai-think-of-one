"""复用生产检索的离线 BM25 / 在线混合检索评测。

expect 中每个子串都是一个必需来源；expect=[] 是库内无答案负例。
来源命中不代表答案、日期或适用人群正确，需另行审查答案。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
TRUTH_PATH = ROOT / "tests" / "retrieval_ground_truth.json"
DATA_DIR = ROOT / "campus_rag" / "data"
K_VALUES = (1, 3, 5, 10)
TOP_K = max(K_VALUES)


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
    args = parser.parse_args(argv)
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    if not truth:
        parser.error("真值集为空")
    if not args.hybrid and not any(DATA_DIR.glob("*.txt")):
        parser.error("离线语料为空")
    print("模式：" + ("生产混合检索" if args.hybrid else "生产 BM25（离线，不调用嵌入/LLM）"))
    keyword_search = None
    if not args.hybrid:
        sys.path.insert(0, str(ROOT))
        from campus_rag import create_keyword_search

        started = perf_counter()
        keyword_search = create_keyword_search(data_dir=str(DATA_DIR))
        print(f"离线索引构建耗时：{perf_counter() - started:.2f}s（不计入查询耗时）")
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
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
