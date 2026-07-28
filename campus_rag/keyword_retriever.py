# keyword_retriever.py
import os
import re
from typing import List, Optional
from rank_bm25 import BM25Okapi
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.node_parser import SentenceSplitter


def _tokenize(text: str) -> list[str]:
    try:
        import jieba
        return list(jieba.cut(text.lower()))
    except ImportError:
        return re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower())


_splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=50)


class BM25Retriever:
    def __init__(self, data_dir: str = None, nodes: Optional[List] = None):
        self.documents: list[str] = []
        self.corpus: list[list[str]] = []
        if nodes:
            for node in nodes:
                text = node.get_content() if hasattr(node, 'get_content') else str(node)
                if text.strip():
                    self.documents.append(text)
                    self.corpus.append(_tokenize(text))
        elif data_dir:
            self._load_from_dir(data_dir)
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def _load_from_dir(self, data_dir: str):
        for fname in sorted(os.listdir(data_dir)):
            if fname.endswith(".txt"):
                with open(os.path.join(data_dir, fname), "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        continue
                from llama_index.core import Document
                chunks = _splitter.get_nodes_from_documents(
                    [Document(text=content, metadata={"source": fname})]
                )
                for chunk in chunks:
                    self.documents.append(chunk.get_content())
                    self.corpus.append(_tokenize(chunk.get_content()))

    @classmethod
    def from_nodes(cls, nodes: List) -> "BM25Retriever":
        """Build BM25 index from pre-chunked nodes matching vector index granularity."""
        return cls(nodes=nodes)

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
