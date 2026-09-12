"""文字备份恢复回归测试；业务数据均注入内存替身。"""

import hashlib
import json
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv"):
    from server.deps import get_user
    from server.routes.backup import router
    from server.services.backup_service import BackupError, BackupService, get_backup_service


class MemoryData:
    """模拟现有数据和恢复写入，记录每次成功写入。"""

    def __init__(self) -> None:
        self.topics = {"original": {"id": "original", "thread_id": "original", "name": "原话题"}}
        self.histories = {"original": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}]}
        self.documents = {"笔记": "资料正文"}
        self.writes: list[str] = []
        self.fail_documents = False

    def list_topics(self, username: str) -> list[dict]:
        return list(self.topics.values())

    def read_histories(self, thread_ids: list[str]) -> dict:
        return {key: self.histories[key] for key in thread_ids}

    def create_restored_topic(self, username: str, name: str, backup_id: str, index: int) -> dict:
        key = f"{username}-{backup_id}-{index}"
        if key not in self.topics:
            self.topics[key] = {"id": key, "thread_id": key, "name": name + "（恢复）"}
            self.writes.append("topic")
        return self.topics[key]

    def write_history_if_empty(self, thread_id: str, messages: list[dict]) -> bool:
        if thread_id in self.histories:
            return False
        self.histories[thread_id] = messages
        self.writes.append("history")
        return True

    def read_documents(self, username: str) -> dict:
        return {"metadatas": [{"source": key} for key in self.documents], "documents": list(self.documents.values())}

    def write_document(self, username: str, source: str, content: str) -> None:
        if self.fail_documents:
            raise OSError("fictional-private-internal-error")
        self.documents[source] = content
        self.writes.append("document")


@pytest.fixture
def setup() -> tuple[MemoryData, BackupService, bytes]:
    """导出同一组替身数据，供往返测试使用。"""
    memory = MemoryData()
    service = BackupService(auth=memory, archive=memory, document_reader=memory.read_documents,
                            document_writer=memory.write_document, secret_reader=lambda: set())
    content = service.export("alice", ["original"], [hashlib.sha256("笔记".encode()).hexdigest()])
    return memory, service, content


def encode_signed(payload: dict) -> bytes:
    """为格式边界测试构造校验正确的输入，避免只测到 checksum 错误。"""
    unsigned = {key: value for key, value in payload.items() if key != "checksum"}
    payload["checksum"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                                                     separators=(",", ":")).encode()).hexdigest()
    return json.dumps(payload, ensure_ascii=False).encode()


def test_export_preview_restore_preserves_originals_and_is_idempotent(setup: tuple) -> None:
    memory, service, content = setup
    preview = service.preview_restore(content)
    assert preview["topics"] == [{"name": "原话题", "message_count": 2}]
    assert memory.writes == []
    first = service.restore("alice", content, preview["checksum"])
    assert (first["restored"], first["failed"]) == (2, 0)
    assert memory.histories["original"] == json.loads(content)["data"]["topics"][0]["messages"]
    assert memory.documents["笔记"] == "资料正文"
    assert len(memory.topics) == len(memory.documents) == 2
    before = list(memory.writes)
    second = service.restore("alice", content, preview["checksum"])
    assert (second["restored"], second["skipped"]) == (0, 2)
    assert memory.writes == before


@pytest.mark.parametrize("invalid", ["checksum", "version", "config", "system", "tool"])
def test_invalid_backup_is_rejected_without_writes(setup: tuple, invalid: str) -> None:
    memory, service, content = setup
    payload = json.loads(content)
    if invalid == "version":
        payload["version"] = 2
    elif invalid == "config":
        payload["data"]["settings"] = {"api_key": "fictional-only"}
    elif invalid in ("system", "tool"):
        payload["data"]["topics"][0]["messages"][0]["role"] = invalid
    modified = encode_signed(payload)
    if invalid == "checksum":
        payload["checksum"] = "0" * 64
        modified = json.dumps(payload).encode()
    for operation in (lambda: service.preview_restore(modified),
                      lambda: service.restore("alice", modified, payload["checksum"])):
        with pytest.raises(BackupError):
            operation()
    assert memory.writes == []


def test_changed_confirmation_is_rejected_without_writes(setup: tuple) -> None:
    memory, service, content = setup
    with pytest.raises(BackupError, match="预览"):
        service.restore("alice", content, "0" * 64)
    assert memory.writes == []


def test_existing_document_read_failure_prevents_all_writes(setup: tuple) -> None:
    memory, service, content = setup
    checksum = service.preview_restore(content)["checksum"]
    service.document_reader = Mock(side_effect=OSError("fictional storage failure"))
    with pytest.raises(OSError):
        service.restore("alice", content, checksum)
    assert memory.writes == []


def test_partial_failure_retry_only_writes_failed_document(setup: tuple, caplog: pytest.LogCaptureFixture) -> None:
    memory, service, content = setup
    checksum = service.preview_restore(content)["checksum"]
    memory.fail_documents = True
    first = service.restore("alice", content, checksum)
    assert (first["restored"], first["failed"]) == (1, 1)
    assert "fictional-private-internal-error" not in caplog.text + json.dumps(first)
    before = list(memory.writes)
    memory.fail_documents = False
    retry = service.restore("alice", content, checksum)
    assert (retry["restored"], retry["skipped"], retry["failed"]) == (1, 1, 0)
    assert memory.writes == before + ["document"]


def test_restore_redacts_newly_configured_credentials(setup: tuple) -> None:
    memory, service, content = setup
    payload = json.loads(content)
    marker = "fictional-configured-value"
    payload["data"]["topics"][0]["name"] = marker
    payload["data"]["topics"][0]["messages"][0]["content"] = marker
    payload["data"]["documents"][0] = {"source": marker, "content": marker}
    content = encode_signed(payload)
    service.secret_reader = lambda: {marker}
    preview = service.preview_restore(content)
    result = service.restore("alice", content, preview["checksum"])
    assert result["restored"] == 2
    assert marker not in json.dumps([preview, result, memory.topics, memory.histories, memory.documents])


def test_restore_api_requires_confirmation_and_preview_does_not_write(setup: tuple) -> None:
    memory, service, content = setup
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_backup_service] = lambda: service
    app.dependency_overrides[get_user] = lambda: "alice"
    with TestClient(app) as client:
        files = {"file": ("backup.json", content, "application/json")}
        preview = client.post("/api/backup/preview", files=files)
        assert preview.status_code == 200
        assert memory.writes == []
        assert client.post("/api/backup/restore", files=files).status_code == 422
        assert memory.writes == []
        restored = client.post("/api/backup/restore", files=files, data={"confirmed_checksum": preview.json()["checksum"]})
        assert restored.status_code == 200
        assert restored.json()["restored"] == 2


def test_preview_api_failure_does_not_expose_internal_error(setup: tuple, caplog: pytest.LogCaptureFixture) -> None:
    memory, service, content = setup
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_backup_service] = lambda: service
    service.secret_reader = Mock(side_effect=OSError("fictional-private-internal-error"))
    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.post("/api/backup/preview", files={"file": ("backup.json", content, "application/json")})
    assert result.status_code == 503
    assert "fictional-private-internal-error" not in result.text + caplog.text
    assert memory.writes == []


def test_partial_or_edited_document_is_not_reported_as_restored(setup: tuple) -> None:
    memory, service, content = setup
    checksum = service.preview_restore(content)["checksum"]

    def partial_write(username: str, source: str, text: str) -> None:
        memory.documents[source] = text[:1]
        raise OSError("simulated interrupted write")

    service.document_writer = partial_write
    assert service.restore("alice", content, checksum)["failed"] == 1
    service.document_writer = memory.write_document
    before = dict(memory.documents)
    result = service.restore("alice", content, checksum)
    assert result["failed"] == 1
    assert result["results"][-1]["status"] == "failed"
    assert memory.documents == before
