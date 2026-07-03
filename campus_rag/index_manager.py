#index_manager.py
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from .data_loader import load_documents_from_files
from . import config

class RAGSystem:
    def __init__(self,persist_dir="./chroma_db"):
        self.chroma_client=chromadb.PersistentClient(path=persist_dir)
    def create_public_index(self, data_dir="./data"):
        collection = self.chroma_client.get_or_create_collection("public")
        vector_store = ChromaVectorStore(chroma_collection=collection)
        docs = load_documents_from_files(data_dir)
        index = VectorStoreIndex.from_documents(
            docs,
            vector_store=vector_store,
            show_progress=True   
        )
        return index
    def get_or_create_public_index(self, data_dir="./data"):
        try:
            collection = self.chroma_client.get_collection("public")
            # 集合存在且有数据，直接加载
            if collection.count() > 0:
                vector_store = ChromaVectorStore(chroma_collection=collection)
                return VectorStoreIndex.from_vector_store(vector_store)
        except Exception:
            pass
        # 集合不存在或为空，新建索引
        return self.create_public_index(data_dir)
