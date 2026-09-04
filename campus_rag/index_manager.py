#index_manager.py
import hashlib
import logging
import os
import threading
from pathlib import Path
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from .data_loader import load_documents_from_files, split_documents
from . import config

logger = logging.getLogger("campus_rag.index_manager")

_chroma_client = None
_chroma_client_path: str | None = None
_lock = threading.Lock()

_embed_dim_cache: int | None = None

# 默认数据目录锚定包内绝对路径：相对路径依赖启动 CWD，从其他目录启动会
# 指向错误目录（如项目根 data/ 的 checkpoint 库）导致静默建出空索引。
_DEFAULT_DATA_DIR = str(Path(__file__).resolve().parent / "data")

# 向量库目录同理锚定项目根绝对路径："./chroma_db" 依赖 CWD，从其他目录
# 启动会在错误位置新建空库并触发公共索引全量重建（或查不到已有数据）。
_DEFAULT_PERSIST_DIR = str(Path(__file__).resolve().parent.parent / "chroma_db")


def _get_live_embed_dim() -> int:
    """探测当前嵌入模型的输出维度（一次真实 API 调用，进程内缓存）。"""
    global _embed_dim_cache
    if _embed_dim_cache is None:
        # 用 require 而非 Settings.embed_model getter：getter 未初始化时会
        # 自动 resolve 出 MockEmbedding（维度 1），is None 判断永远不成立。
        embed_model = config.require_embed_model()
        _embed_dim_cache = len(embed_model.get_text_embedding("dimension probe"))
    return _embed_dim_cache


def _stored_dim(collection) -> int | None:
    """读取集合中已存向量的维度；空集合返回 None。"""
    if collection.count() == 0:
        return None
    # peek 返回 numpy 数组，真值判断有歧义，必须用 is None / len 判空
    embs = collection.peek().get("embeddings")
    if embs is None or len(embs) == 0:
        return None
    return len(embs[0])


def assert_collection_dim(collection) -> None:
    """校验既有集合维度与当前嵌入模型一致，不一致时抛出可操作的错误。

    ChromaDB 集合维度在首次写入后锁定；混用嵌入模型（或嵌入服务不可用时
    llama_index 静默降级出 MockEmbedding，维度 1）会让集合永久不可用：
    查询时只抛晦涩的底层维度异常，故在索引构建前显式拦截。
    """
    stored = _stored_dim(collection)
    if stored is None:
        return
    live = _get_live_embed_dim()
    if stored != live:
        raise RuntimeError(
            f"向量集合 '{collection.name}' 维度({stored})与当前嵌入模型输出"
            f"维度({live})不一致，该集合已不可用（ChromaDB 维度在首次写入后"
            "锁定）。请删除该集合并重建：公共数据可从 campus_rag/data 自动"
            "重建，个人数据需重新导入。"
        )


def _get_chroma_client(persist_dir: str = _DEFAULT_PERSIST_DIR) -> chromadb.PersistentClient:
    global _chroma_client, _chroma_client_path
    resolved = str(Path(persist_dir).resolve())
    if _chroma_client is None:
        with _lock:
            if _chroma_client is None:
                # 先记路径再赋客户端：并发下另一线程看到客户端非空时，
                # 路径必须已就绪，否则会误报绑定路径不一致警告
                _chroma_client_path = resolved
                _chroma_client = chromadb.PersistentClient(path=resolved)
    if _chroma_client_path == resolved:
        return _chroma_client

    # 调用方显式指定其他持久化目录时必须严格隔离。这里不替换默认客户端，
    # 避免测试、迁移或临时索引把生产查询悄悄导向另一套数据。
    return chromadb.PersistentClient(path=resolved)


def _user_collection_name(user_id: str) -> str:
    return f"user_{user_id}"


def _lacks_url_metadata(collection) -> bool:
    """抽样检测集合分块是否缺失源链接元数据（旧版索引迁移用）。"""
    sample = collection.get(include=["metadatas"], limit=1)
    metas = sample.get("metadatas") or []
    return bool(metas) and "url" not in (metas[0] or {})


def _public_sources_match_dir(collection, data_dir: str) -> bool:
    """集合中所有文档的 source 是否都在本地数据目录内。

    只有成立时才可安全从源目录重建（同步服务端独有的文档不能丢）。"""
    if not os.path.isdir(data_dir):
        return False
    local_files = set(os.listdir(data_dir))
    result = collection.get(include=["metadatas"])
    sources = {m.get("source") for m in result.get("metadatas") or []}
    return bool(sources) and sources <= local_files


class RAGSystem:
    def __init__(self, persist_dir: str | None = None):
        from .config import init_embed
        # 嵌入不可用时 llama_index 会静默回退 MockEmbedding（维度 1），
        # 一旦 Mock 向量写入集合，ChromaDB 维度将被永久锁定，后续真实
        # 嵌入（如 4096 维）查询必报维度不匹配。因此必须 fail fast。
        if not init_embed():
            raise RuntimeError(
                "嵌入服务不可用，已阻止向量索引初始化（避免 MockEmbedding "
                "污染向量库）。请检查 campus_rag/.env 的 EMBED_* 配置及"
                "嵌入 API 的网络可达性（校园网关需校园网/VPN）。"
            )
        self.chroma_client = _get_chroma_client(persist_dir or _DEFAULT_PERSIST_DIR)

    # ── 公共数据（官方通知）──────────────────────────────────────
    def create_public_index(self, data_dir=_DEFAULT_DATA_DIR):
        collection = self.chroma_client.get_or_create_collection("public")
        assert_collection_dim(collection)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        docs = load_documents_from_files(data_dir)
        nodes = split_documents(docs)
        index = VectorStoreIndex.from_vector_store(vector_store)
        index.insert_nodes(nodes)
        return index

    def create_public_index_via_docs(self, documents: list):
        """从 Document 列表创建公共索引（用于全量同步）。"""
        collection = self.chroma_client.get_or_create_collection("public")
        assert_collection_dim(collection)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        nodes = split_documents(documents)
        return VectorStoreIndex(nodes, vector_store=vector_store)

    def get_or_create_public_index(self, data_dir=_DEFAULT_DATA_DIR):
        try:
            collection = self.chroma_client.get_collection("public")
        except Exception:
            collection = None
        if collection is not None and collection.count() > 0:
            stored = _stored_dim(collection)
            if stored == _get_live_embed_dim():
                # 旧版索引缺失源链接元数据，且集合内容可从本地源目录全量恢复时，
                # 一次性重建以补全（溯源功能迁移，重建后不再触发）。
                if _lacks_url_metadata(collection) and _public_sources_match_dir(collection, data_dir):
                    logger.info("public 集合缺失源链接元数据，从 %s 重建（一次性迁移）", data_dir)
                    self.chroma_client.delete_collection("public")
                    return self.create_public_index(data_dir)
                vector_store = ChromaVectorStore(chroma_collection=collection)
                return VectorStoreIndex.from_vector_store(vector_store)
            # 维度不匹配：集合由旧嵌入模型（或 MockEmbedding 降级）写入且已
            # 不可查询。公共数据可从源目录全量重建，故自动删除恢复而非报错。
            logger.warning(
                "public 集合维度(%s)与当前嵌入模型(%s)不一致，删除并从 %s 重建",
                stored, _get_live_embed_dim(), data_dir,
            )
            self.chroma_client.delete_collection("public")
        return self.create_public_index(data_dir)

    def get_public_index(self):
        try:
            collection = self.chroma_client.get_collection("public")
            stored = _stored_dim(collection)
            if stored is not None and stored != _get_live_embed_dim():
                logger.warning(
                    "public 集合维度(%s)与当前嵌入模型(%s)不一致，删除并重建",
                    stored, _get_live_embed_dim(),
                )
                self.chroma_client.delete_collection("public")
                return self.create_public_index()
            vector_store = ChromaVectorStore(chroma_collection=collection)
            return VectorStoreIndex.from_vector_store(vector_store)
        except RuntimeError:
            # 嵌入探测失败（网络不可达等）不应触发静默重建，让调用方看到原因
            raise
        except Exception:
            return self.create_public_index()

    def add_documents_to_public(self, documents: list):
        """增量添加文档到公共集合（仅管理员），自动跳过重复内容。"""
        collection = self.chroma_client.get_or_create_collection("public")
        assert_collection_dim(collection)
        existing_hashes = self._get_existing_hashes("public")
        nodes = split_documents(documents)
        new_nodes = [n for n in nodes if hashlib.md5(n.text.encode()).hexdigest() not in existing_hashes]
        if new_nodes:
            vector_store = ChromaVectorStore(chroma_collection=collection)
            index = VectorStoreIndex.from_vector_store(vector_store)
            index.insert_nodes(new_nodes)

    # ── 用户私有数据 ────────────────────────────────────────────
    def get_or_create_user_index(self, user_id: str, data_dir: str = None):
        coll_name = _user_collection_name(user_id)
        try:
            collection = self.chroma_client.get_collection(coll_name)
        except Exception:
            collection = None
        if collection is not None and collection.count() > 0:
            # 个人数据无法自动重建：维度不匹配时显式报错，而不是静默忽略
            assert_collection_dim(collection)
            vector_store = ChromaVectorStore(chroma_collection=collection)
            return VectorStoreIndex.from_vector_store(vector_store)

        collection = self.chroma_client.get_or_create_collection(coll_name)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        if data_dir and os.path.isdir(data_dir):
            docs = load_documents_from_files(data_dir)
            if docs:
                nodes = split_documents(docs)
                return VectorStoreIndex(nodes, vector_store=vector_store)
        return VectorStoreIndex.from_vector_store(vector_store)

    def get_user_index(self, user_id: str):
        """获取用户个人索引（集合需已存在）。"""
        coll_name = _user_collection_name(user_id)
        collection = self.chroma_client.get_collection(coll_name)
        assert_collection_dim(collection)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        return VectorStoreIndex.from_vector_store(vector_store)

    def add_user_documents(self, user_id: str, documents: list):
        """向用户的私有索引中追加文档，自动跳过重复内容。"""
        coll_name = _user_collection_name(user_id)
        collection = self.chroma_client.get_or_create_collection(coll_name)
        assert_collection_dim(collection)
        existing_hashes = self._get_existing_hashes(coll_name)
        nodes = split_documents(documents)
        new_nodes = [n for n in nodes if hashlib.md5(n.text.encode()).hexdigest() not in existing_hashes]
        if new_nodes:
            vector_store = ChromaVectorStore(chroma_collection=collection)
            index = VectorStoreIndex.from_vector_store(vector_store)
            index.insert_nodes(new_nodes)
            return index
        return VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))

    def clear_user_index(self, user_id: str):
        """删除用户全部私有数据。"""
        coll_name = _user_collection_name(user_id)
        try:
            self.chroma_client.delete_collection(coll_name)
        except Exception as e:
            # 集合不存在是正常路径（debug），其他异常必须留痕而非静默吞掉
            logger.debug("clear_user_index(%s) 跳过: %s", user_id, e)

    def list_user_documents(self, user_id: str) -> dict:
        """列出用户私有集合中的所有文档，返回 {ids, metadatas, documents, previews}。"""
        try:
            collection = self.chroma_client.get_collection(_user_collection_name(user_id))
            result = collection.get(include=["metadatas", "documents"])
        except Exception as e:
            # 集合不存在返回空列表是正常语义，但真实异常必须留痕，
            # 否则用户数据"凭空消失"无任何线索可查。
            logger.debug("list_user_documents(%s) 读取失败: %s", user_id, e)
            return {"ids": [], "metadatas": [], "documents": [], "previews": []}
        docs = result.get("documents") or []
        result["previews"] = [d[:200] + "..." if len(d) > 200 else d for d in docs]
        return result

    def delete_user_documents_by_source(self, user_id: str, source: str) -> int:
        """删除用户私有集合中指定来源的所有文档块，返回删除数量。"""
        try:
            collection = self.chroma_client.get_collection(_user_collection_name(user_id))
            result = collection.get(where={"source": source})
            ids = result["ids"]
            if ids:
                collection.delete(ids=ids)
            return len(ids)
        except Exception as e:
            # 返回 0 会让路由误报 404 "数据不存在"，真实失败原因必须留痕
            logger.warning("delete_user_documents_by_source(%s, %s) 失败: %s",
                           user_id, source, e)
            return 0

    def list_public_documents(self) -> dict:
        """列出公共集合中所有文档，返回 {ids, metadatas, documents, previews}。"""
        try:
            collection = self.chroma_client.get_collection("public")
            result = collection.get(include=["metadatas", "documents"])
        except Exception:
            return {"ids": [], "metadatas": [], "documents": [], "previews": []}
        docs = result.get("documents") or []
        result["previews"] = [d[:200] + "..." if len(d) > 200 else d for d in docs]
        return result

    def delete_public_document(self, doc_id: str) -> bool:
        """按 ChromaDB ID 删除公共集合中的单条文档。"""
        try:
            self.chroma_client.get_collection("public").delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def delete_public_documents_by_source(self, source: str) -> int:
        """删除指定来源（文件名）的所有文档块，返回删除数量。"""
        try:
            collection = self.chroma_client.get_collection("public")
            result = collection.get(where={"source": source})
            ids = result["ids"]
            if ids:
                collection.delete(ids=ids)
            return len(ids)
        except Exception as e:
            # 返回 0 会掩盖同步增量删除的真实失败，必须留痕
            logger.warning("delete_public_documents_by_source(%s) 失败: %s", source, e)
            return 0

    def get_public_documents_by_source(self, source: str) -> dict:
        """按 source 获取公共集合中的文档，返回 {ids, metadatas, documents}。"""
        try:
            collection = self.chroma_client.get_collection("public")
            result = collection.get(
                where={"source": source},
                include=["metadatas", "documents"],
            )
            return result
        except Exception:
            return {"ids": [], "metadatas": [], "documents": []}

    def get_collection_stats(self) -> dict:
        """返回各集合的文档计数。"""
        stats = {}
        try:
            stats["public"] = self.chroma_client.get_collection("public").count()
        except Exception:
            stats["public"] = 0
        user_count = 0
        for c in self.chroma_client.list_collections():
            if c.name.startswith("user_"):
                user_count += 1
        stats["user_collections_count"] = user_count
        return stats

    def get_user_collection_size(self, username: str) -> int:
        """返回用户私有集合中的文档数量。"""
        try:
            return self.chroma_client.get_collection(f"user_{username}").count()
        except Exception:
            return 0

    def _get_existing_hashes(self, collection_name: str) -> set:
        """获取集合中已有文档的 MD5 哈希集合，用于去重。"""
        try:
            collection = self.chroma_client.get_collection(collection_name)
            result = collection.get(include=["documents"])
            docs = result.get("documents") or []
            return {hashlib.md5(d.encode()).hexdigest() for d in docs}
        except Exception as e:
            # 返回空集合会退化为"不去重"而非报错，静默时难以察觉重复入库
            logger.debug("_get_existing_hashes(%s) 失败: %s", collection_name, e)
            return set()

    def get_combined_query_engine(self, user_id: str):
        """返回 (public_index, user_index) 元组，user_index 可能为 None。"""
        pub_idx = self.get_public_index()
        user_idx = None
        try:
            user_idx = self.get_user_index(user_id)
        except Exception as e:
            # 个人索引不可用（含维度不匹配）时降级为仅公共检索，但必须留痕
            logger.warning("用户 %s 的个人索引不可用: %s", user_id, e)
        return pub_idx, user_idx
