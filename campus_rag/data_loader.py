#data_loader.py
import json
import logging
import os
import re

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

logger = logging.getLogger(__name__)


def group_document_chunks(data: dict) -> dict[str, dict]:
    """按来源聚合文本，只移除同一原文坐标确认的分块重叠。"""
    grouped: dict[str, list] = {}
    for meta, text in zip(data.get("metadatas") or [], data.get("documents") or [], strict=True):
        meta = meta or {}
        source = meta.get("source") or "手动输入"
        if not isinstance(source, str) or not isinstance(text, str):
            raise ValueError("个人资料文本或来源格式异常")
        order = meta.get("chunk_index", 0)
        grouped.setdefault(source, []).append((order if type(order) is int else 0, text, meta))
    result = {}
    for source, chunks in grouped.items():
        ordered = sorted(chunks, key=lambda item: item[0])
        parents: dict[str, list] = {}
        for order, text, meta in ordered:
            span = _chunk_span(meta, text)
            if span is None:
                break
            parent, start, end = span
            parents.setdefault(parent, []).append((start, end, text))
        else:
            result[source] = {"content": "\n".join(_join_chunk_spans(spans) for spans in parents.values()),
                              "chunks": [(order, text) for order, text, _ in ordered]}
            continue
        # 旧数据缺少坐标时保留全部文本，不能把用户有意重复的段落当成重叠。
        result[source] = {"content": "\n".join(text for _, text, _ in ordered),
                          "chunks": [(order, text) for order, text, _ in ordered]}
    return result


def _chunk_span(meta: dict, text: str) -> tuple[str, int, int] | None:
    raw = meta.get("_node_content")
    if not isinstance(raw, str):
        return None
    try:
        node = json.loads(raw)
    except (ValueError, RecursionError):
        logger.warning("资料分块坐标无法解析，保留全部片段文字")
        return None
    if not isinstance(node, dict):
        return None
    parent = meta.get("ref_doc_id")
    start, end = node.get("start_char_idx"), node.get("end_char_idx")
    if not isinstance(parent, str) or not parent or parent == "None":
        return None
    if type(start) is not int or type(end) is not int or start < 0 or end - start != len(text):
        return None
    return parent, start, end


def _join_chunk_spans(spans: list[tuple[int, int, str]]) -> str:
    spans = sorted(spans)
    start, end, content = spans[0]
    parts = []
    for next_start, next_end, text in spans[1:]:
        if next_start > end:
            # 分块器可能丢弃边界空白；没有原始字符证据时保留换行分隔。
            parts.append(content)
            start, end, content = next_start, next_end, text
            continue
        overlap = min(end, next_end) - next_start
        if content[next_start - start:next_start - start + overlap] != text[:overlap]:
            logger.warning("资料分块坐标与正文冲突，保留全部片段文字")
            return "\n".join(text for _, _, text in spans)
        if next_end > end:
            content += text[overlap:]
            end = next_end
    return "\n".join([*parts, content])

# URL 合法字符白名单匹配：\S+ 会吞掉紧邻的中文标点（如"）"），从源头杜绝尾部粘连
_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")

# 爬虫文档的正文首部带有"来源：<URL>"行（见 tools/ustc_crawler.sync_column）。
_SOURCE_LINE_RE = re.compile(r"^来源[:：]\s*(https?://\S+)\s*$", re.MULTILINE | re.IGNORECASE)

# URL 尾部可能粘连的中英文标点，统一剥除
_URL_TRAILING_PUNCT = ".,;)]）。，；、"


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
            return url.rstrip(_URL_TRAILING_PUNCT)
    return None


def extract_source_url_from_text(content: str) -> str | None:
    """从正文的"来源：<URL>"行提取源链接。

    爬虫生成的文档（文件名形如 ustc_teach_notice_20429.txt）没有数字 ID
    前缀，extract_source_url 的 ID 匹配必然落空；其来源只写在正文行里，
    必须按行解析，否则这批文档在检索结果中永远缺失源链接。
    """
    match = _SOURCE_LINE_RE.search(content or "")
    return match.group(1).rstrip(_URL_TRAILING_PUNCT) if match else None


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
                    url = extract_source_url(filename, content) or extract_source_url_from_text(content)
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
