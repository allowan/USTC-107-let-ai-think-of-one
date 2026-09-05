"""检索召回率评测：对比 query 真值与检索结果 top-k 命中情况。

用法：
    python scripts/eval_retrieval.py              # BM25 模式（离线，默认）
    python scripts/eval_retrieval.py --vector     # 向量检索模式（需嵌入服务可用）

输出逐条命中明细 + Recall@1/3/5/10 与 MRR@10 汇总。真值见
tests/retrieval_ground_truth.json（expect 为命中即算对的来源文件名子串列表）。

该脚本是迭代检索参数（chunk、top_k、重排序）的靶子，不是 pytest 单测——
语料或真值变化后直接重跑。BM25 模式不经过嵌入/LLM，随时可跑；向量模式
走与生产一致的 campus_rag.search_notices 公开接口（解析其"来源"标注），
不触碰模块内部实现。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH_PATH = ROOT / "tests" / "retrieval_ground_truth.json"
DATA_DIR = ROOT / "campus_rag" / "data"

K_VALUES = (1, 3, 5, 10)
TOP_K = max(K_VALUES)


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


def _vector_ranked_sources(query: str) -> list[str]:
    """走向量检索公开接口，从格式化结果的 [来源: ...] 标注解析来源序列。"""
    sys.path.insert(0, str(ROOT))
    from campus_rag import search_notices

    text = search_notices(query)
    return re.findall(r"\[来源: ([^\]]+)\]", text)


def _first_hit_rank(ranked_sources: list[str], expect: list[str]) -> int | None:
    """返回首个命中块的名次（1 起），未命中返回 None。"""
    for rank, source in enumerate(ranked_sources, start=1):
        if any(e in source for e in expect):
            return rank
    return None


def main() -> int:
    use_vector = "--vector" in sys.argv
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    corpus = _load_corpus(DATA_DIR)

    if use_vector:
        print("模式：向量检索（campus_rag.search_notices，需嵌入服务）")

        def ranked_sources(query: str) -> list[str]:
            return _vector_ranked_sources(query)
    else:
        if not corpus:
            print("语料为空：campus_rag/data 下没有 .txt 文件，无法评测")
            return 1
        print(f"模式：BM25（离线，语料 {len(corpus)} 篇）")
        # 语料只建一次索引：先一次性完成分词与 BM25 构建。
        # 不用 keyword_retriever.BM25Retriever：其检索结果丢弃来源元数据，
        # 无法满足评测的来源归因需求；此处用生产同款参数（1024/50 切块 +
        # jieba 分词）自建带 source 的索引。
        from rank_bm25 import BM25Okapi
        from llama_index.core import Document
        from llama_index.core.node_parser import SentenceSplitter

        splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
        chunks: list[str] = []
        chunk_sources: list[str] = []
        for source, content in corpus:
            nodes = splitter.get_nodes_from_documents(
                [Document(text=content, metadata={"source": source})]
            )
            for node in nodes:
                text = node.get_content()
                if text.strip():
                    chunks.append(text)
                    chunk_sources.append(source)
        try:
            import jieba
            tokenize = lambda t: list(jieba.cut(t.lower()))
        except ImportError:
            tokenize = lambda t: re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", t.lower())
        bm25 = BM25Okapi([tokenize(c) for c in chunks])
        print(f"索引：{len(chunks)} 个块")

        def ranked_sources(query: str) -> list[str]:
            scores = bm25.get_scores(tokenize(query))
            top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:TOP_K]
            return [chunk_sources[i] for i in top]

    hits_at = {k: 0 for k in K_VALUES}
    rr_sum = 0.0
    misses: list[tuple[str, list[str]]] = []

    for item in truth:
        query, expect = item["query"], item["expect"]
        try:
            sources = ranked_sources(query)
        except Exception as exc:
            print(f"[error] 检索失败：{query} — {exc}")
            misses.append((query, expect))
            continue
        rank = _first_hit_rank(sources, expect)
        if rank is not None:
            for k in K_VALUES:
                if rank <= k:
                    hits_at[k] += 1
            rr_sum += 1.0 / rank
        else:
            misses.append((query, expect))

    n = len(truth)
    print(f"\n=== 检索召回评测（{n} 条 query）===\n")
    for k in K_VALUES:
        print(f"Recall@{k:<3} {hits_at[k]}/{n} = {hits_at[k] / n:.1%}")
    print(f"MRR@{TOP_K:<4} {rr_sum / n:.3f}")

    print("\n=== 未命中明细 ===\n")
    if misses:
        for query, expect in misses:
            print(f"  {query}  →  期望 {expect}")
    else:
        print("（全部命中）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
