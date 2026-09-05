# keyword_retriever.py
import re
from typing import List, Optional
from rank_bm25 import BM25Okapi
from llama_index.core.schema import BaseNode, NodeWithScore
from .data_loader import load_documents_from_files, split_documents


def _tokenize(text: str) -> list[str]:
    try:
        import jieba
        return [token for token in jieba.cut(text.lower()) if any(c.isalnum() for c in token)]
    except ImportError:
        return re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower())


def extract_keywords(query: str, top_k: int = 6) -> str:
    """用 jieba 抽取查询的核心关键词并重组为重试查询（检索自愈用）。

    首次检索为空时，常见原因是查询带过多修饰词；去掉修饰保留核心名词
    再试一次往往能命中。jieba 不可用时返回空串，调用方跳过重试。
    """
    try:
        import jieba.analyse
    except ImportError:
        return ""
    return " ".join(jieba.analyse.extract_tags(query, topK=top_k))


class BM25Retriever:
    """保留分块身份和来源的关键词检索器。"""

    def __init__(self, data_dir: str | None = None, nodes: Optional[List[BaseNode]] = None) -> None:
        source_nodes = nodes if nodes is not None else (
            split_documents(load_documents_from_files(data_dir)) if data_dir else []
        )
        self.nodes: list[BaseNode] = []
        self.corpus: list[list[str]] = []
        for node in source_nodes:
            tokens = _tokenize(node.get_content())
            if tokens:
                self.nodes.append(node)
                self.corpus.append(tokens)
        self.documents = [node.get_content() for node in self.nodes]
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def retrieve(self, query: str, top_k: int = 10) -> List[NodeWithScore]:
        """只返回有词项交集的分块；小语料中的负 IDF 仍可能是有效匹配。"""
        tokenized = _tokenize(query)
        if self.bm25 is None or not tokenized or top_k <= 0:
            return []
        scores = self.bm25.get_scores(tokenized)
        matches = [i for i, frequencies in enumerate(self.bm25.doc_freqs)
                   if any(token in frequencies for token in tokenized)]
        matches.sort(key=lambda i: scores[i], reverse=True)
        return [NodeWithScore(node=self.nodes[i], score=float(scores[i]))
                for i in matches[:top_k]]
