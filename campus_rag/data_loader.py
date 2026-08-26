#data_loader.py
import re

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
import os

# URL 合法字符白名单匹配：\S+ 会吞掉紧邻的中文标点（如“）”），从源头杜绝尾部粘连
_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")


def extract_source_url(filename: str, content: str) -> str | None:
    """从通知内容中提取源网址。

    文件名前缀即通知 ID（如 20455_选课通知.txt），官方源链接通常包含该 ID，
    仅做 ID 匹配：正文中的报名系统、外部平台等链接不等于来源，宁缺毋错。
    """
    match = re.match(r"(\d+)", filename or "")
    if not match:
        return None
    notice_id = match.group(1)
    for url in _URL_RE.findall(content):
        if notice_id in url:
            return url.rstrip(".,;)]")
    return None


def load_documents_from_files(directory: str) -> list:
    """读取目录下所有 .txt 文件，每个文件为一个 Document（附带来源与源网址元数据）"""
    documents = []
    if not os.path.isdir(directory):
        return documents
    for filename in os.listdir(directory):
        if filename.endswith(".txt"):
            filepath = os.path.join(directory, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                if content.strip():
                    metadata = {"source": filename}
                    url = extract_source_url(filename, content)
                    if url:
                        metadata["url"] = url
                    documents.append(Document(text=content, metadata=metadata))
    return documents

def split_documents(documents: list) -> list:
    """使用 SentenceSplitter 对文档分块，每个分块附带 chunk_index（原文内序号）。

    ChromaDB 的读取顺序无保证，按来源聚合还原原文时必须靠该序号排序；
    同时将其排除在嵌入输入外，避免改变向量内容。
    """
    parser = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
    all_nodes = []
    for doc in documents:
        nodes = parser.get_nodes_from_documents([doc])
        for idx, node in enumerate(nodes):
            node.metadata["chunk_index"] = idx
            node.excluded_embed_metadata_keys = [*node.excluded_embed_metadata_keys, "chunk_index"]
        all_nodes.extend(nodes)
    return all_nodes
