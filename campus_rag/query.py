import logging
import threading
from pathlib import Path

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever

_base = Path(__file__).resolve().parent

from . import config
from . import events
from .index_manager import RAGSystem

logger = logging.getLogger("campus_rag.query")

_rag = None
_public_retriever = None
_public_index = None
_user_indexes: dict[str, VectorStoreIndex] = {}
_user_retrievers: dict[str, VectorIndexRetriever] = {}
_init_lock = threading.RLock()


def reset_caches() -> None:
    """重置所有缓存状态，下次调用时自动重建。"""
    global _rag, _public_retriever, _public_index
    with _init_lock:
        _rag = None
        _public_index = None
        _public_retriever = None
        _user_indexes.clear()
        _user_retrievers.clear()
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
    global _public_retriever, _public_index
    with _init_lock:
        rag = _get_rag()
        if _public_index is None:
            _public_index = rag.get_or_create_public_index(str(_base / "data"))
        if _public_retriever is None:
            _public_retriever = _public_index.as_retriever(similarity_top_k=10)
    return True


def _get_user_index(user_id: str) -> VectorStoreIndex:
    with _init_lock:
        if user_id not in _user_indexes:
            _user_indexes[user_id] = _get_rag().get_or_create_user_index(user_id)
        return _user_indexes[user_id]


def _get_user_retriever(user_id: str) -> VectorIndexRetriever:
    with _init_lock:
        if user_id not in _user_retrievers:
            _user_retrievers[user_id] = _get_user_index(user_id).as_retriever(similarity_top_k=10)
        return _user_retrievers[user_id]


def _format_nodes(nodes, empty_message: str) -> str:
    if not nodes:
        return empty_message
    contexts = []
    for node in nodes:
        meta = node.metadata or {}
        header = f"[来源: {meta.get('source', '未知来源')}]"
        if meta.get("url"):
            header += f" [源链接: {meta['url']}]"
        contexts.append(f"{header}\n{node.get_content()}")
    return "\n\n".join(contexts)


def _retrieve_with_fallback(retriever, query: str, empty_message: str) -> str:
    """检索自愈：首次为空时用 jieba 关键词缩减重试一次，仍空再返回未找到。"""
    nodes = retriever.retrieve(query)
    if not nodes:
        from .keyword_retriever import extract_keywords
        retry = extract_keywords(query)
        if retry and retry != query.strip():
            nodes = retriever.retrieve(retry)
    return _format_nodes(nodes, empty_message)


def search_notices(query: str) -> str:
    """只在官方通知（公共数据）中搜索。"""
    with _init_lock:
        _ensure_init()
        retriever = _public_retriever
    return _retrieve_with_fallback(retriever, query, "未在通知中找到相关信息。")


def search_user_data(query: str, user_id: str) -> str:
    """只在用户个人数据中搜索。"""
    retriever = _get_user_retriever(user_id)
    return _retrieve_with_fallback(retriever, query, "未在个人数据中找到相关信息。")


def search_notices_answer(query: str) -> str:
    """搜索官方通知，经 LLM 总结后返回回答。"""
    with _init_lock:
        _ensure_init()
        index = _public_index
    from .query_engine import get_rag_response
    return get_rag_response(query, public_index=index, data_dir=str(_base / "data"))


def search_user_data_answer(query: str, user_id: str) -> str:
    """搜索用户个人数据，经 LLM 总结后返回回答。"""
    user_idx = _get_user_index(user_id)
    from .query_engine import get_rag_response
    return get_rag_response(query, user_index=user_idx)


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
    global _public_retriever
    _public_retriever = None
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
    global _public_retriever
    _public_retriever = None
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
    _user_retrievers.pop(user_id, None)


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
    _user_retrievers.pop(user_id, None)
    return count
