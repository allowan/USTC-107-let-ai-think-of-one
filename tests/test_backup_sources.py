"""备份数据源隔离测试；只使用临时数据库与存储替身。"""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

# 导入包的现有入口会加载 .env，测试不读取真实配置。
with patch("dotenv.load_dotenv"):
    from campus_rag import index_manager, read_user_data_for_backup
    from server.services.conversation_archive import ConversationArchive


def test_history_is_latest_visible_text_and_source_is_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.db"
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        for thread_id, checkpoint_id, messages in [
            ("selected", "001", [HumanMessage(content="旧状态")]),
            ("other", "002", [HumanMessage(content="其他用户")]),
            ("selected", "003", [
                SystemMessage(content="内部提示"),
                HumanMessage(content=[{"type": "text", "text": "问题"},
                                      {"type": "image_url", "image_url": {"url": "private"}}]),
                AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
                ToolMessage(content="工具私有内容", tool_call_id="1"),
                AIMessage(content=[{"type": "reasoning", "reasoning": "隐藏"},
                                   {"type": "text", "text": "答案"}],
                          additional_kwargs={"secret": "内部元数据"}),
            ]),
        ]:
            checkpoint = empty_checkpoint()
            checkpoint["id"] = checkpoint_id
            checkpoint["channel_values"] = {"messages": messages}
            saver.put({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, {}, {})
    original = db_path.read_bytes()
    assert ConversationArchive(db_path).read_histories(["selected", "missing"]) == {
        "selected": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}],
        "missing": [],
    }
    assert db_path.read_bytes() == original


def test_missing_checkpoint_does_not_create_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "checkpoints.db"
    assert ConversationArchive(db_path).read_histories(["x"]) == {"x": []}
    assert not db_path.parent.exists()


def test_live_wal_checkpoint_is_included(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"messages": [HumanMessage(content="已提交的 WAL 对话")]}
        saver.put({"configurable": {"thread_id": "live", "checkpoint_ns": ""}}, checkpoint, {}, {})
        assert Path(str(db_path) + "-wal").exists()
        assert ConversationArchive(db_path).read_histories(["live"]) == {
            "live": [{"role": "user", "content": "已提交的 WAL 对话"}],
        }


def test_invalid_checkpoint_database_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db_path = tmp_path / "broken.db"
    db_path.write_bytes(b"invalid sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        ConversationArchive(db_path).read_histories(["x"])
    assert "读取对话备份失败" in caplog.text


def test_missing_checkpoint_table_is_not_silently_created(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    connection = sqlite3.connect(db_path)
    connection.close()
    with pytest.raises(ValueError, match="checkpoint"):
        ConversationArchive(db_path).read_histories(["x"])
    assert db_path.read_bytes() == b""


def test_personal_chunks_do_not_initialize_rag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(index_manager, "_DEFAULT_PERSIST_DIR", str(tmp_path))
    client = Mock()
    client.get_collection.return_value.get.return_value = {
        "ids": ["chunk"], "documents": ["正文"], "metadatas": [{"source": "笔记"}],
        "embeddings": ["must not export"],
    }
    monkeypatch.setattr(index_manager, "_get_chroma_client", lambda: client)
    monkeypatch.setattr(index_manager.config, "init_embed", Mock(side_effect=AssertionError("no embedding")))
    assert read_user_data_for_backup("alice") == {
        "ids": ["chunk"], "documents": ["正文"], "metadatas": [{"source": "笔记"}],
    }
    client.get_collection.assert_called_once_with("user_alice", embedding_function=None)
    client.get_collection.return_value.get.assert_called_once_with(include=["metadatas", "documents"])


def test_personal_collection_not_found_differs_from_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(index_manager, "_DEFAULT_PERSIST_DIR", str(tmp_path))
    client = Mock()
    monkeypatch.setattr(index_manager, "_get_chroma_client", lambda: client)
    client.get_collection.side_effect = index_manager.NotFoundError("missing")
    assert read_user_data_for_backup("alice") == {"ids": [], "documents": [], "metadatas": []}
    client.get_collection.side_effect = RuntimeError("storage unavailable")
    with pytest.raises(RuntimeError):
        read_user_data_for_backup("alice")


def test_missing_chroma_directory_is_not_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "absent"
    monkeypatch.setattr(index_manager, "_DEFAULT_PERSIST_DIR", str(directory))
    monkeypatch.setattr(index_manager, "_get_chroma_client", Mock(side_effect=AssertionError("must not create")))
    assert read_user_data_for_backup("alice") == {"ids": [], "documents": [], "metadatas": []}
    assert not directory.exists()
