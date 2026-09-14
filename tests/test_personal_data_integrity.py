"""资料读取和来源隔离回归，只使用内存替身。"""

from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest
from chromadb.errors import NotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from llama_index.core.schema import TextNode
from sqlalchemy import create_engine

with patch("dotenv.load_dotenv"), patch("sqlalchemy.create_engine", return_value=create_engine("sqlite:///:memory:")):
    from campus_rag import index_manager
    from server.routes.personal_data import router
    from server.services.rag_service import get_rag_service


def test_missing_personal_collection_is_empty() -> None:
    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    rag.chroma_client.get_collection.side_effect = NotFoundError("missing")
    assert rag.list_user_documents("test")["ids"] == []


def test_personal_storage_failure_is_not_empty(caplog: pytest.LogCaptureFixture) -> None:
    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    rag.chroma_client.get_collection.return_value.get.side_effect = OSError("private-storage-detail")
    with pytest.raises(OSError):
        rag.list_user_documents("test")
    assert "private-storage-detail" not in caplog.text


def test_personal_list_failure_returns_safe_retryable_error() -> None:
    app = FastAPI()
    app.include_router(router)
    rag = Mock()
    rag.list_user_data.side_effect = OSError("private-storage-detail")
    app.dependency_overrides[get_rag_service] = lambda: rag
    response = TestClient(app).get("/api/personal-data")
    assert response.status_code == 503
    assert "items" not in response.json()
    assert "private-storage-detail" not in response.text


@pytest.mark.parametrize("source,inserted", [("original", False), ("independent", True)])
def test_personal_deduplication_preserves_independent_sources(source: str, inserted: bool) -> None:
    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    collection = rag.chroma_client.get_or_create_collection.return_value
    collection.get.return_value = {"documents": ["shared text"], "metadatas": [{"source": "original"}]}
    node = TextNode(text="shared text", metadata={"source": source})
    index = Mock()
    with patch.object(index_manager, "_index_write", return_value=nullcontext()), \
         patch.object(index_manager, "assert_collection_dim"), \
         patch.object(index_manager, "split_documents", return_value=[node]), \
         patch.object(index_manager, "ChromaVectorStore"), \
         patch.object(index_manager.VectorStoreIndex, "from_vector_store", return_value=index):
        rag.add_user_documents("test", [node])
    assert index.insert_nodes.called == inserted
    if inserted:
        index.insert_nodes.assert_called_once_with([node])


def test_personal_deduplication_read_failure_prevents_writes() -> None:
    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    rag.chroma_client.get_or_create_collection.return_value.get.side_effect = OSError("read failed")
    with patch.object(index_manager, "_index_write", return_value=nullcontext()), \
         patch.object(index_manager, "assert_collection_dim"), \
         patch.object(index_manager, "split_documents") as split:
        with pytest.raises(OSError):
            rag.add_user_documents("test", [])
        split.assert_not_called()


def test_shared_chunk_does_not_remove_part_of_new_document() -> None:
    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    collection = rag.chroma_client.get_or_create_collection.return_value
    collection.get.return_value = {"documents": ["shared", "old"], "metadatas": [
        {"source": "notes", "ref_doc_id": "original", "chunk_index": 0},
        {"source": "notes", "ref_doc_id": "original", "chunk_index": 1}]}
    nodes = [TextNode(text=text, metadata={"source": "notes", "chunk_index": i})
             for i, text in enumerate(["shared", "new"])]
    index = Mock()
    with patch.object(index_manager, "_index_write", return_value=nullcontext()), \
         patch.object(index_manager, "assert_collection_dim"), \
         patch.object(index_manager, "split_documents", return_value=nodes), \
         patch.object(index_manager, "ChromaVectorStore"), \
         patch.object(index_manager.VectorStoreIndex, "from_vector_store", return_value=index):
        rag.add_user_documents("test", nodes)
    index.insert_nodes.assert_called_once_with(nodes)


def test_identical_documents_in_one_batch_are_inserted_once() -> None:
    from llama_index.core import Document

    rag = object.__new__(index_manager.RAGSystem)
    rag.chroma_client = Mock()
    rag.chroma_client.get_or_create_collection.return_value.get.return_value = {"documents": [], "metadatas": []}
    index = Mock()
    documents = [Document(text="same content", metadata={"source": "notes"}) for _ in range(2)]
    with patch.object(index_manager, "_index_write", return_value=nullcontext()), \
         patch.object(index_manager, "assert_collection_dim"), \
         patch.object(index_manager, "ChromaVectorStore"), \
         patch.object(index_manager.VectorStoreIndex, "from_vector_store", return_value=index):
        rag.add_user_documents("test", documents)
    inserted = index.insert_nodes.call_args.args[0]
    assert len(inserted) == 1
    assert inserted[0].text == "same content"
