import logging
from pathlib import Path
from llama_index.core import Document

_base = Path(__file__).resolve().parent

from . import config
from .index_manager import RAGSystem

logger = logging.getLogger("campus_rag.query")

_rag = None
_public_retriever = None
_user_retrievers: dict[str, object] = {}


def reset_caches() -> None:
    """重置所有缓存状态，下次调用时自动重建。"""
    global _rag, _public_retriever, _user_retrievers
    _rag = None
    _public_retriever = None
    _user_retrievers = {}


def _ensure_init():
    """确保 RAG 已初始化。ChromaDB 恢复由 get_or_create_public_index 内部处理。"""
    global _rag, _public_retriever
    if _rag is None:
        _rag = RAGSystem()
        index = _rag.get_or_create_public_index(str(_base / "data"))
        _public_retriever = index.as_retriever(similarity_top_k=10)
    return True


def _get_user_retriever(user_id: str):
    if user_id not in _user_retrievers:
        index = _rag.get_or_create_user_index(user_id)
        _user_retrievers[user_id] = index.as_retriever(similarity_top_k=10)
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


def search_notices(query: str) -> str:
    """只在官方通知（公共数据）中搜索。"""
    _ensure_init()
    return _format_nodes(_public_retriever.retrieve(query),
                         "未在通知中找到相关信息。")


def search_user_data(query: str, user_id: str) -> str:
    """只在用户个人数据中搜索。"""
    _ensure_init()
    retriever = _get_user_retriever(user_id)
    return _format_nodes(retriever.retrieve(query),
                         "未在个人数据中找到相关信息。")


def search_notices_answer(query: str) -> str:
    """搜索官方通知，经 LLM 总结后返回回答。"""
    _ensure_init()
    pub_idx = _rag.get_public_index()
    from .query_engine import get_rag_response
    return get_rag_response(query, public_index=pub_idx, data_dir=str(_base / "data"))


def search_user_data_answer(query: str, user_id: str) -> str:
    """搜索用户个人数据，经 LLM 总结后返回回答。"""
    _ensure_init()
    user_idx = _rag.get_or_create_user_index(user_id)
    from .query_engine import get_rag_response
    return get_rag_response(query, user_index=user_idx)


def _enrich_url_metadata(documents: list) -> None:
    """为缺失源链接的公共文档补全 url 元数据（同步与本地文件共用入口）。"""
    from .data_loader import extract_source_url
    for doc in documents:
        if not doc.metadata.get("url"):
            url = extract_source_url(doc.metadata.get("source", ""), doc.text)
            if url:
                doc.metadata["url"] = url


def add_public_documents(documents: list) -> None:
    """增量添加带 source 元数据的公共文档（同步服务用），自动去重。"""
    _enrich_url_metadata(documents)
    _ensure_init()
    _rag.add_documents_to_public(documents)
    global _public_retriever
    _public_retriever = None


def delete_public_data(source: str) -> int:
    """按来源删除公共集合中的文档块，返回删除数量（同步服务增量更新用）。"""
    _ensure_init()
    count = _rag.delete_public_documents_by_source(source)
    global _public_retriever
    _public_retriever = None
    return count


def replace_public_documents(documents: list) -> None:
    """全量替换公共集合（同步服务全量同步用）。

    先探测嵌入可用性再清空重建：避免嵌入不可用时先删后建失败，
    导致公共集合被清空（虽可从 campus_rag/data 自愈，但不应发生）。
    """
    if not config.init_embed():
        raise RuntimeError(
            "嵌入服务不可用，已拒绝全量替换公共集合（避免清空后重建失败）。"
        )
    _ensure_init()
    try:
        _rag.chroma_client.delete_collection("public")
    except Exception:
        logger.warning("删除旧 public 集合失败（可能不存在），继续重建", exc_info=True)
    if documents:
        _enrich_url_metadata(documents)
        _rag.create_public_index_via_docs(documents)
    reset_caches()


def update_user_data(user_id: str, source: str, content: str) -> None:
    """更新个人数据：先探测嵌入可用性，再删除旧数据并写入新数据。

    若先删后写且写入时嵌入不可用（fail-fast 拒绝入库），用户数据将永久丢失；
    故必须在删除前确认嵌入服务可用。
    """
    if not config.init_embed():
        raise RuntimeError(
            "嵌入服务不可用，已拒绝更新个人数据（避免删除旧数据后写入失败）。"
            "请检查校园网/VPN 连接后重试，原数据未受影响。"
        )
    delete_user_data(user_id, source)
    doc = Document(text=content, metadata={"source": source})
    add_user_data(user_id, [doc])


def add_user_data(user_id: str, documents: list):
    """向用户个人索引添加文档（llama_index Document 列表）。"""
    _ensure_init()
    _rag.add_user_documents(user_id, documents)
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
    _ensure_init()
    return _rag.list_user_documents(user_id)


def delete_user_data(user_id: str, source: str) -> int:
    """删除用户个人知识库中指定来源的所有文档块。"""
    _ensure_init()
    count = _rag.delete_user_documents_by_source(user_id, source)
    _user_retrievers.pop(user_id, None)
    return count
