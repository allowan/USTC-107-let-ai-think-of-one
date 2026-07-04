# keyword_retriever.py
import os
import re
from rank_bm25 import BM25Okapi
from typing import List
from llama_index.core.schema import NodeWithScore, TextNode


def _tokenize(text: str) -> list[str]:
    try:
        import jieba
        return list(jieba.cut(text.lower()))
    except ImportError:
        return re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower())


class BM25Retriever:
    def __init__(self, data_dir: str):
        self.documents: list[str] = []
        self.corpus: list[list[str]] = []
        for fname in os.listdir(data_dir):
            if fname.endswith(".txt"):
                with open(os.path.join(data_dir, fname), "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self.documents.append(content)
                        self.corpus.append(_tokenize(content))
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def retrieve(self, query: str, top_k: int = 10) -> List[NodeWithScore]:
        if not self.bm25:
            return []
        tokenized = _tokenize(query)
        scores = self.bm25.get_scores(tokenized)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        nodes = []
        for idx in top_indices:
            node = TextNode(text=self.documents[idx])
            nodes.append(NodeWithScore(node=node, score=float(scores[idx])))
        return nodes
