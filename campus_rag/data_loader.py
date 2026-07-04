#data_loader.py
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
import os

def load_documents_from_files(directory: str) -> list:
    """读取目录下所有 .txt 文件，每个文件为一个 Document"""
    documents = []
    for filename in os.listdir(directory):
        if filename.endswith(".txt"):
            filepath = os.path.join(directory, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                if content.strip():
                    documents.append(Document(
                        text=content,
                        metadata={"source": filename}
                    ))
    return documents

def split_documents(documents: list) -> list:
    """使用 SentenceSplitter 对文档分块"""
    parser = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
    nodes = parser.get_nodes_from_documents(documents)
    return nodes
