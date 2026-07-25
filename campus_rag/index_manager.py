#index_manager.py
import hashlib
import os
import threading
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from .data_loader import load_documents_from_files, split_documents
from . import config

_chroma_client = None
_lock = threading.Lock()


def _get_chroma_client(persist_dir: str = "./chroma_db") -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        with _lock:
            if _chroma_client is None:
                _chroma_client = chromadb.PersistentClient(path=persist_dir)
    return _chroma_client


def _user_collection_name(user_id: str) -> str:
    return f"user_{user_id}"


class RAGSystem:
    def __init__(self, persist_dir="./chroma_db"):
        self.chroma_client = _get_chroma_client(persist_dir)

    # ── 公共数据（官方通知）──────────────────────────────────────
    def create_public_index(self, data_dir="./data"):
        collection = self.chroma_client.get_or_create_collection("public")
        vector_store = ChromaVectorStore(chroma_collection=collection)
        docs = load_documents_from_files(data_dir)
        nodes = split_documents(docs)
        index = VectorStoreIndex.from_vector_store(vector_store)
        index.insert_nodes(nodes)
        return index

    def create_public_index_via_docs(self, documents: list):
        """从 Document 列表创建公共索引（用于全量同步）。"""
        collection = self.chroma_client.get_or_create_collection("public")
        vector_store = ChromaVectorStore(chroma_collection=collection)
        nodes = split_documents(documents)
        return VectorStoreIndex(nodes, vector_store=vector_store)

    def get_or_create_public_index(self, data_dir="./data"):
        try:
            collection = self.chroma_client.get_collection("public")
            if collection.count() > 0:
                vector_store = ChromaVectorStore(chroma_collection=collection)
                return VectorStoreIndex.from_vector_store(vector_store)
        except Exception:
            pass
        return self.create_public_index(data_dir)

    def get_public_index(self):
        try:
            collection = self.chroma_client.get_collection("public")
            vector_store = ChromaVectorStore(chroma_collection=collection)
            return VectorStoreIndex.from_vector_store(vector_store)
        except Exception:
            return self.create_public_index()

    def add_documents_to_public(self, documents: list):
        """增量添加文档到公共集合（仅管理员），自动跳过重复内容。"""
        collection = self.chroma_client.get_or_create_collection("public")
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
            if collection.count() > 0:
                vector_store = ChromaVectorStore(chroma_collection=collection)
                return VectorStoreIndex.from_vector_store(vector_store)
        except Exception:
            pass

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
        vector_store = ChromaVectorStore(chroma_collection=collection)
        return VectorStoreIndex.from_vector_store(vector_store)

    def add_user_documents(self, user_id: str, documents: list):
        """向用户的私有索引中追加文档，自动跳过重复内容。"""
        coll_name = _user_collection_name(user_id)
        collection = self.chroma_client.get_or_create_collection(coll_name)
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
        except Exception:
            pass

    def list_user_documents(self, user_id: str) -> dict:
        """列出用户私有集合中的所有文档，返回 {ids, metadatas, documents, previews}。"""
        try:
            collection = self.chroma_client.get_collection(_user_collection_name(user_id))
            result = collection.get(include=["metadatas", "documents"])
        except Exception:
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
        except Exception:
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
        except Exception:
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
        except Exception:
            return set()

    def get_combined_query_engine(self, user_id: str):
        """返回 (public_index, user_index) 元组，user_index 可能为 None。"""
        pub_idx = self.get_public_index()
        user_idx = None
        try:
            user_idx = self.get_user_index(user_id)
        except Exception:
            pass
        return pub_idx, user_idx
