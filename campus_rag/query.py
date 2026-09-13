import hashlib
import logging
import re
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.schema import NodeWithScore

_base = Path(__file__).resolve().parent

from . import config
from . import events
from .index_manager import RAGSystem, read_collection_nodes, read_user_collection_for_backup

logger = logging.getLogger("campus_rag.query")

_rag = None
_public_index = None
_user_indexes: dict[str, VectorStoreIndex] = {}
_init_lock = threading.RLock()


def read_user_data_for_backup(user_id: str) -> dict[str, list]:
    """导出个人原始分块供备份使用，不依赖嵌入服务或 LLM。"""
    return read_user_collection_for_backup(user_id)


def group_user_document_chunks(data: dict) -> dict[str, dict]:
    """复用原文坐标合并资料片段，供列表和文字备份使用。"""
    from .data_loader import group_document_chunks

    return group_document_chunks(data)


def backup_document_matches(source: str, content: str, chunks: list[tuple[int, str]]) -> bool:
    """按入库分块规则检查恢复副本完整性，不调用嵌入或 LLM。"""
    from .data_loader import split_documents

    nodes = split_documents([Document(text=content, metadata={"source": source})])
    return sorted(chunks) == [(node.metadata["chunk_index"], node.text) for node in nodes]


def reset_caches() -> None:
    """重置所有缓存状态，下次调用时自动重建。"""
    global _rag, _public_index
    with _init_lock:
        _rag = None
        _public_index = None
        _user_indexes.clear()
        from .query_engine import reset_caches as _reset_engine_caches
        _reset_engine_caches()


def _get_rag() -> RAGSystem:
    global _rag
    with _init_lock:
        if _rag is None:
            _rag = RAGSystem()
        return _rag


def _ensure_init() -> bool:
    """确保 RAG 已初始化。ChromaDB 恢复由 get_or_create_public_index 内部处理。"""
    global _public_index
    with _init_lock:
        rag = _get_rag()
        if _public_index is None:
            _public_index = rag.get_or_create_public_index(str(_base / "data"))
    return True


def _get_user_index(user_id: str) -> VectorStoreIndex:
    with _init_lock:
        if user_id not in _user_indexes:
            _user_indexes[user_id] = _get_rag().get_or_create_user_index(user_id)
        return _user_indexes[user_id]


def _format_nodes(nodes, empty_message: str, warnings: list[str] | None = None) -> str:
    prefix = "\n".join(warnings or [])
    if not nodes:
        return f"{prefix}\n{empty_message}" if prefix else empty_message
    contexts = []
    for node in nodes:
        meta = node.metadata or {}
        header = f"[来源: {meta.get('source', '未知来源')}]"
        if meta.get("url"):
            header += f" [源链接: {meta['url']}]"
        contexts.append(f"{header}\n{node.get_content()}")
    return "\n\n".join(([prefix] if prefix else []) + contexts)


def _get_public_index() -> VectorStoreIndex:
    with _init_lock:
        _ensure_init()
        return _public_index


def retrieve_notice_nodes(
    query: str, *, top_k: int = 10, rerank: bool = True,
    warnings: list[str] | None = None,
) -> list[NodeWithScore]:
    """检索公共节点，warnings 收集单路降级说明，包括无命中情形。"""
    from .query_engine import retrieve_nodes

    return retrieve_nodes(
        query, top_k=top_k, rerank=rerank, warnings=warnings,
        public_index_loader=_get_public_index, public_nodes_loader=read_collection_nodes,
    )


def retrieve_user_nodes(
    query: str, user_id: str, *, top_k: int = 10, rerank: bool = True,
    warnings: list[str] | None = None,
) -> list[NodeWithScore]:
    """仅检索指定用户节点，warnings 收集单路降级说明。"""
    from .query_engine import retrieve_nodes

    return retrieve_nodes(
        query, top_k=top_k, rerank=rerank, warnings=warnings,
        user_index_loader=lambda: _get_user_index(user_id),
        user_nodes_loader=lambda: read_collection_nodes(user_id),
    )


def search_keyword_nodes(
    query: str, *, user_id: str | None = None,
    data_dir: str | None = None, top_k: int = 10,
) -> list[NodeWithScore]:
    """复用生产 BM25；默认只读目标集合，可显式指定离线评测语料目录。"""
    if data_dir is not None and user_id is not None:
        raise ValueError("不能同时指定个人集合和离线语料目录")
    if not query.strip() or top_k <= 0:
        return []
    return create_keyword_search(user_id=user_id, data_dir=data_dir)(query, top_k)


def create_keyword_search(
    *, user_id: str | None = None, data_dir: str | None = None,
) -> Callable[[str, int], list[NodeWithScore]]:
    """构建生产 BM25 的只读快照查询函数，批量评测可复用而不反复建索引。"""
    from .keyword_retriever import BM25Retriever

    if data_dir is not None and user_id is not None:
        raise ValueError("不能同时指定个人集合和离线语料目录")
    retriever = (BM25Retriever(data_dir=data_dir) if data_dir is not None
                 else BM25Retriever(nodes=read_collection_nodes(user_id)))
    return retriever.retrieve


def search_notices(query: str) -> str:
    """混合检索公共通知片段，不调用生成模型。"""
    warnings: list[str] = []
    nodes = retrieve_notice_nodes(query, warnings=warnings)
    return _format_nodes(nodes, "未在通知中找到相关信息。", warnings)


def search_user_data(query: str, user_id: str) -> str:
    """混合检索用户私有片段，不调用生成模型。"""
    warnings: list[str] = []
    nodes = retrieve_user_nodes(query, user_id, warnings=warnings)
    return _format_nodes(nodes, "未在个人数据中找到相关信息。", warnings)


def _evidence_artifact(nodes: list[NodeWithScore], kind: str, warnings: list[str]) -> dict:
    evidence = []
    for node in nodes:
        meta = node.metadata or {}
        text = node.get_content()
        source = str(meta.get("source") or "未知来源")
        title_match = re.search(r"(?m)^标题[：:]\s*(.+)$", text)
        title = str(meta.get("title") or (title_match[1] if title_match else source))
        published = str(meta.get("publish_date") or meta.get("published_at") or "")
        if not published:
            matched = re.search(r"(?m)^(?:发布日期|发布时间)[：:]\s*(\d{4}-\d{2}-\d{2})", text)
            published = matched[1] if matched else ""
        try:
            published = date.fromisoformat(published[:10]).isoformat() if published else ""
        except ValueError:
            logger.warning("证据发布日期无效，保留为未知")
            published = ""
        url = str(meta.get("url") or "")
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                url = ""
        except ValueError:
            logger.warning("证据来源链接无效，隐藏链接")
            url = ""
        evidence.append({
            "id": hashlib.sha256(f"{kind}\0{source}\0{node.node.node_id}".encode()).hexdigest(),
            "source": source, "title": title, "url": url, "published_at": published,
            "excerpt": text[:2000], "kind": kind,
        })
    return {"evidence": evidence, "warnings": warnings}


def search_notices_with_evidence(query: str) -> tuple[str, dict]:
    """从一次通知检索生成正文与真实节点证据，供 Agent 工具使用。"""
    warnings: list[str] = []
    nodes = retrieve_notice_nodes(query, warnings=warnings)
    return _format_nodes(nodes, "未在通知中找到相关信息。", warnings), _evidence_artifact(nodes, "official", warnings)


def search_user_data_with_evidence(query: str, user_id: str) -> tuple[str, dict]:
    """从指定用户的一次检索生成正文与证据，不混入其他用户资料。"""
    warnings: list[str] = []
    nodes = retrieve_user_nodes(query, user_id, warnings=warnings)
    return _format_nodes(nodes, "未在个人数据中找到相关信息。", warnings), _evidence_artifact(nodes, "personal", warnings)


def search_notices_answer(query: str) -> str:
    """搜索官方通知，经 LLM 总结后返回回答。"""
    from .query_engine import get_rag_response
    return get_rag_response(
        query, public_index_loader=_get_public_index,
        public_nodes_loader=read_collection_nodes,
    )


def search_user_data_answer(query: str, user_id: str) -> str:
    """搜索用户个人数据，经 LLM 总结后返回回答。"""
    from .query_engine import get_rag_response
    return get_rag_response(
        query, user_index_loader=lambda: _get_user_index(user_id),
        user_nodes_loader=lambda: read_collection_nodes(user_id),
    )


def _enrich_url_metadata(documents: list) -> None:
    """为缺失源链接的公共文档补全 url 元数据（同步与本地文件共用入口）。"""
    from .data_loader import extract_source_url, extract_source_url_from_text
    for doc in documents:
        if not doc.metadata.get("url"):
            source = doc.metadata.get("source", "")
            # 数字 ID 前缀文件按 ID 匹配；爬虫文档（ustc_* 前缀）回退到正文"来源："行
            url = extract_source_url(source, doc.text) or extract_source_url_from_text(doc.text)
            if url:
                doc.metadata["url"] = url


def add_public_documents(documents: list) -> None:
    """增量添加带 source 元数据的公共文档（同步服务用），自动去重。"""
    _enrich_url_metadata(documents)
    _ensure_init()
    _rag.add_documents_to_public(documents)
    # 同步新通知的事件时间索引（best-effort，内部吞异常）。
    events.sync_events_from_documents(documents)


def upsert_public_documents(documents: list) -> None:
    """按来源替换同步通知，新数据写入成功前保留旧分块。"""
    _enrich_url_metadata(documents)
    _get_rag().replace_documents("public", documents)
    events.sync_events_from_documents(documents)


def delete_public_data(source: str) -> int:
    """按来源删除公共集合中的文档块，返回删除数量（同步服务增量更新用）。"""
    count = _get_rag().delete_public_documents_by_source(source)
    # 通知被删除时同步移除其事件，避免时间索引残留已下线通知。
    events.delete_events_by_source(source)
    return count


def replace_public_documents(documents: list) -> None:
    """全量替换公共文档，先写新分块再移除旧 ID，保留集合身份。"""
    if not config.init_embed():
        raise RuntimeError(
            "嵌入服务不可用，已拒绝全量替换公共集合（避免清空后重建失败）。"
        )
    _enrich_url_metadata(documents)
    _get_rag().replace_documents("public", documents, replace_all=True)
    # 全量替换：事件时间索引同步重建，以 documents 为权威集合（清空后重抽）。
    events.clear_events()
    events.sync_events_from_documents(documents)


def update_user_data(user_id: str, source: str, content: str) -> None:
    """按来源更新个人数据，新分块写入成功后再移除旧 ID。"""
    if not config.init_embed():
        raise RuntimeError(
            "嵌入服务不可用，已拒绝更新个人数据（避免删除旧数据后写入失败）。"
            "请检查校园网/VPN 连接后重试，原数据未受影响。"
        )
    doc = Document(text=content, metadata={"source": source})
    _get_rag().replace_documents(f"user_{user_id}", [doc])


def add_user_data(user_id: str, documents: list) -> None:
    """向用户个人索引添加文档（llama_index Document 列表）。"""
    _get_rag().add_user_documents(user_id, documents)


def add_user_files(user_id: str, path: str):
    """向用户个人索引导入 txt 文件。path 可以是单个 .txt 文件或目录（扫描目录下所有 .txt）。"""
    from .data_loader import load_documents_from_files
    import os

    docs = []
    if os.path.isfile(path):
        if not path.endswith(".txt"):
            raise ValueError("目前只支持 .txt 文件")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if content:
            docs = [Document(text=content, metadata={"source": os.path.basename(path)})]
    elif os.path.isdir(path):
        docs = load_documents_from_files(path)
    else:
        raise FileNotFoundError(f"路径不存在: {path}")

    if docs:
        add_user_data(user_id, docs)
    return len(docs)


def list_user_data(user_id: str) -> dict:
    """列出用户个人知识库中的所有文档。"""
    return _get_rag().list_user_documents(user_id)


def delete_user_data(user_id: str, source: str) -> int:
    """删除用户个人知识库中指定来源的所有文档块。"""
    count = _get_rag().delete_user_documents_by_source(user_id, source)
    return count
