"""原文坐标合并测试：不调用模型、不访问真实数据库。"""

import hashlib
import json
from unittest.mock import Mock, patch

from llama_index.core import Document
from llama_index.core.vector_stores.utils import node_to_metadata_dict
from sqlalchemy import create_engine

with patch("dotenv.load_dotenv"), patch("sqlalchemy.create_engine", return_value=create_engine("sqlite:///:memory:")):
    from campus_rag import group_user_document_chunks
    from campus_rag.data_loader import split_documents
    from server.services.backup_service import BackupService
    from server.services.rag_service import RAGService


def stored(spans: list[tuple[str, int, str]]) -> dict:
    """构造带原文身份和坐标的持久化片段。"""
    return {"documents": [text for _, _, text in spans], "metadatas": [
        {"source": "notes", "chunk_index": i, "ref_doc_id": parent,
         "_node_content": json.dumps({"start_char_idx": start, "end_char_idx": start + len(text)})}
        for i, (parent, start, text) in enumerate(spans)]}


def test_overlap_and_out_of_order_reconstruct_once() -> None:
    data = stored([("a", 4, "efghij"), ("a", 0, "abcdef"), ("a", 2, "cde")])
    assert group_user_document_chunks(data)["notes"]["content"] == "abcdefghij"


def test_repeated_text_at_distinct_positions_is_preserved() -> None:
    data = stored([("a", 0, "abcabc"), ("a", 3, "abcabc")])
    assert group_user_document_chunks(data)["notes"]["content"] == "abcabcabc"


def test_same_source_distinct_documents_are_not_merged_by_coordinates() -> None:
    data = stored([("a", 0, "abcdef"), ("b", 0, "abcdef"), ("a", 4, "efgh"), ("b", 4, "efij")])
    assert group_user_document_chunks(data)["notes"]["content"] == "abcdefgh\nabcdefij"


def test_legacy_and_conflicting_coordinates_preserve_all_text() -> None:
    legacy = {"documents": ["abcabc", "abcabc"], "metadatas": [{"source": "notes"}] * 2}
    assert group_user_document_chunks(legacy)["notes"]["content"] == "abcabc\nabcabc"
    conflict = stored([("a", 0, "abcdef"), ("a", 4, "XYgh")])
    assert group_user_document_chunks(conflict)["notes"]["content"] == "abcdef\nXYgh"


def test_missing_span_keeps_text_separate_without_guessing_gap() -> None:
    data = stored([("a", 0, "abc"), ("a", 20, "defgh"), ("a", 23, "ghij")])
    assert group_user_document_chunks(data)["notes"]["content"] == "abc\ndefghij"


def test_real_splitter_listing_and_backup_share_overlap_removal() -> None:
    original = " ".join(f"Sentence {i} is unique and records an important fact." for i in range(500))
    nodes = split_documents([Document(text=original, metadata={"source": "notes"})])
    assert len(nodes) > 1
    data = {"documents": [n.text for n in reversed(nodes)],
            "metadatas": [node_to_metadata_dict(n, remove_text=True, flat_metadata=True) for n in reversed(nodes)]}
    listing = RAGService.format_user_data(data)[0]["full_content"]
    assert listing == original
    service = BackupService(auth=Mock(), archive=Mock(), document_reader=lambda _: data, secret_reader=lambda: set())
    exported = json.loads(service.export("test", [], [hashlib.sha256(b"notes").hexdigest()]))
    assert exported["data"]["documents"][0]["content"] == original
