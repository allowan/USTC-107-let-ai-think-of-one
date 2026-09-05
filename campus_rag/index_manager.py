#index_manager.py
import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import chromadb
from chromadb.errors import NotFoundError
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from .data_loader import load_documents_from_files, split_documents
from . import config

logger = logging.getLogger("campus_rag.index_manager")

_chroma_client = None
_chroma_client_path: str | None = None
_lock = threading.Lock()
_write_lock = threading.RLock()


@contextmanager
def _index_write() -> Iterator[None]:
    from .query_engine import invalidate_keyword_cache
    with _write_lock:
        invalidate_keyword_cache()
        try:
            yield
        finally:
            invalidate_keyword_cache()


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
            "锁定）。请恢复建库时的嵌入模型；需切换模型时先备份源文档并"
            "显式重建索引，查询不会自动删除数据。"
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
    def create_public_index(self, data_dir: str = _DEFAULT_DATA_DIR) -> VectorStoreIndex:
        """从本地种子向公共集合插入分块。"""
        with _index_write():
            collection = self.chroma_client.get_or_create_collection("public")
            assert_collection_dim(collection)
            vector_store = ChromaVectorStore(chroma_collection=collection)
            docs = load_documents_from_files(data_dir)
            nodes = split_documents(docs)
            index = VectorStoreIndex.from_vector_store(vector_store)
            index.insert_nodes(nodes)
            return index

    def create_public_index_via_docs(self, documents: list) -> VectorStoreIndex:
        """从 Document 列表创建公共索引（用于全量同步）。"""
        with _index_write():
            collection = self.chroma_client.get_or_create_collection("public")
            assert_collection_dim(collection)
            vector_store = ChromaVectorStore(chroma_collection=collection)
            nodes = split_documents(documents)
            index = VectorStoreIndex.from_vector_store(vector_store)
            index.insert_nodes(nodes)
            return index

    def replace_documents(
        self, collection_name: str, documents: list, *, replace_all: bool = False,
    ) -> None:
        """先写新分块再移除旧 ID，支持全量替换或按来源更新。"""
        sources = {doc.metadata.get("source") for doc in documents}
        if any(not isinstance(source, str) or not source.strip() for source in sources):
            raise ValueError("替换文档必须提供非空 source")
        if not documents and not replace_all:
            return
        with _index_write():
            collection = self.chroma_client.get_or_create_collection(collection_name)
            assert_collection_dim(collection)
            selection = {} if replace_all else {"where": {"source": {"$in": sorted(sources)}}}
            old_ids = collection.get(include=[], **selection)["ids"]
            nodes = split_documents(documents)
            if documents and not nodes:
                raise ValueError("替换内容不能为空")
            new_ids = [node.node_id for node in nodes]
            try:
                if nodes:
                    store = ChromaVectorStore(chroma_collection=collection)
                    index = VectorStoreIndex.from_vector_store(store)
                    index.insert_nodes(nodes)
            except Exception:
                logger.exception("替换集合 %s 失败，清理本次新增分块", collection_name)
                if new_ids:
                    try:
                        collection.delete(ids=new_ids)
                    except Exception:
                        logger.exception("新增分块清理失败，旧数据保留；请重试替换")
                raise
            if old_ids:
                try:
                    collection.delete(ids=old_ids)
                except Exception:
                    # 删除可能已经提交后才报错，不能再清理已成功写入的新数据。
                    logger.exception("移除旧分块失败，新数据已保留；请重试替换")
                    raise

    def get_or_create_public_index(self, data_dir: str = _DEFAULT_DATA_DIR) -> VectorStoreIndex:
        """读取既有公共索引；仅在集合不存在时从本地种子创建。"""
        try:
            collection = self.chroma_client.get_collection("public")
        except NotFoundError:
            with _index_write():
                # 另一个调用方可能已在等待期间建好集合。
                try:
                    collection = self.chroma_client.get_collection("public")
                except NotFoundError:
                    return self.create_public_index(data_dir)
        # 同步专有内容不一定存在于本地目录，维度或元数据异常不能靠删库修复。
        assert_collection_dim(collection)
        return VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))

    def get_public_index(self) -> VectorStoreIndex:
        """获取公共索引；维度不匹配时保留数据并明确报错。"""
        return self.get_or_create_public_index()

    def add_documents_to_public(self, documents: list) -> None:
        """增量添加文档到公共集合（仅管理员），自动跳过重复内容。"""
        with _index_write():
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
    def get_or_create_user_index(self, user_id: str, data_dir: str | None = None) -> VectorStoreIndex:
        """读取个人集合，仅缺失或空集合的显式种子导入执行写入。"""
        coll_name = _user_collection_name(user_id)
        try:
            collection = self.chroma_client.get_collection(coll_name)
        except NotFoundError:
            collection = None
        if collection is not None and (collection.count() > 0 or not data_dir):
            assert_collection_dim(collection)
            return VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
        with _index_write():
            collection = self.chroma_client.get_or_create_collection(coll_name)
            assert_collection_dim(collection)
            index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
            if collection.count() == 0 and data_dir and os.path.isdir(data_dir):
                index.insert_nodes(split_documents(load_documents_from_files(data_dir)))
            return index

    def get_user_index(self, user_id: str):
        """获取用户个人索引（集合需已存在）。"""
        coll_name = _user_collection_name(user_id)
        collection = self.chroma_client.get_collection(coll_name)
        assert_collection_dim(collection)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        return VectorStoreIndex.from_vector_store(vector_store)

    def add_user_documents(self, user_id: str, documents: list) -> VectorStoreIndex:
        """向用户的私有索引中追加文档，自动跳过重复内容。"""
        with _index_write():
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

    def clear_user_index(self, user_id: str) -> None:
        """清空用户分块，保留集合身份供已缓存索引继续使用。"""
        self.replace_documents(_user_collection_name(user_id), [], replace_all=True)

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
        with _index_write():
            try:
                collection = self.chroma_client.get_collection(_user_collection_name(user_id))
                result = collection.get(where={"source": source}, include=[])
                ids = result["ids"]
                if ids:
                    collection.delete(ids=ids)
                return len(ids)
            except NotFoundError:
                return 0
            except Exception as e:
                # 返回 0 会让路由误报 404 "数据不存在"，真实失败原因必须留痕
                logger.warning("delete_user_documents_by_source(%s, %s) 失败: %s",
                               user_id, source, e)
                raise

    def delete_public_documents_by_source(self, source: str) -> int:
        """删除指定来源（文件名）的所有文档块，返回删除数量。"""
        with _index_write():
            try:
                collection = self.chroma_client.get_collection("public")
                result = collection.get(where={"source": source}, include=[])
                ids = result["ids"]
                if ids:
                    collection.delete(ids=ids)
                return len(ids)
            except NotFoundError:
                return 0
            except Exception as e:
                # 返回 0 会掩盖同步增量删除的真实失败，必须留痕
                logger.warning("delete_public_documents_by_source(%s) 失败: %s", source, e)
                raise

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
