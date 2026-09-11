"""导出白名单、脱敏及 API 边界测试，不读取真实数据或凭据。"""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv"):
    from server.deps import get_user
    from server.routes.backup import router
    from server.services.backup_service import (
        BackupError, BackupService, configured_secret_values, get_backup_service, redact_text,
    )


FICTIONAL_SECRET = "fictional-credential-for-tests-only"
SOURCE = f"笔记 {FICTIONAL_SECRET}"
DOCUMENT_ID = hashlib.sha256(SOURCE.encode()).hexdigest()


class FakeAuth:
    """提供包含不应导出的额外字段的话题。"""

    def list_topics(self, username: str) -> list[dict]:
        assert username == "test_user"
        return [
            {"id": "selected", "thread_id": "thread-selected", "name": f"讨论 {FICTIONAL_SECRET}",
             "metadata": {"secret": "internal"}, "config": "internal"},
            {"id": "other", "thread_id": "thread-other", "name": "未选择的话题"},
        ]


class FakeArchive:
    """提供不同角色与内部消息字段。"""

    def read_histories(self, thread_ids: list[str]) -> dict[str, list[dict]]:
        assert thread_ids == ["thread-selected"]
        return {"thread-selected": [
            {"role": "system", "content": "隐藏系统提示"},
            {"role": "user", "content": f"问题 {FICTIONAL_SECRET}", "metadata": "内部字段"},
            {"role": "tool", "content": "隐藏工具输出"},
            {"role": "assistant", "content": "回答", "tool_calls": ["内部调用"]},
        ]}


def read_documents(username: str) -> dict:
    """乱序提供分块以验证导出时重组。"""
    assert username == "test_user"
    return {
        "ids": ["internal-2", "internal-1", "internal-other"],
        "metadatas": [{"source": SOURCE, "chunk_index": 1, "private": "hidden"},
                      {"source": SOURCE, "chunk_index": 0}, {"source": "未选择的资料"}],
        "documents": [f"第二块 {FICTIONAL_SECRET}", "第一块", "不得导出"],
        "embeddings": ["不得导出"],
    }


@pytest.fixture
def service() -> BackupService:
    """所有数据源均为替身。"""
    return BackupService(auth=FakeAuth(), archive=FakeArchive(), document_reader=read_documents,
                         secret_reader=lambda: {FICTIONAL_SECRET})


@pytest.fixture
def client(service: BackupService) -> TestClient:
    """只启动备份路由，不运行完整应用 lifespan。"""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_backup_service] = lambda: service
    app.dependency_overrides[get_user] = lambda: "test_user"
    return TestClient(app)


def test_export_whitelist_redaction_order_and_checksum(service: BackupService) -> None:
    exported = service.export("test_user", ["selected", "selected"], [DOCUMENT_ID, DOCUMENT_ID])
    payload = json.loads(exported)
    assert set(payload) == {"format", "version", "created_at", "data", "checksum"}
    assert payload["format"] == "campus-personal-text-backup"
    assert payload["version"] == 1
    assert payload["data"] == {
        "topics": [{"name": "讨论 [已脱敏]", "messages": [
            {"role": "user", "content": "问题 [已脱敏]"},
            {"role": "assistant", "content": "回答"},
        ]}],
        "documents": [{"source": "笔记 [已脱敏]", "content": "第一块\n第二块 [已脱敏]"}],
    }
    assert FICTIONAL_SECRET not in exported.decode()
    checksum = payload.pop("checksum")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode()
    assert checksum == hashlib.sha256(canonical).hexdigest()


def test_catalog_redacts_names(service: BackupService) -> None:
    catalog = service.catalog("test_user")
    assert catalog["errors"] == []
    assert catalog["topics"][0] == {"id": "selected", "name": "讨论 [已脱敏]"}
    assert catalog["documents"][0]["name"] == "笔记 [已脱敏]"
    assert FICTIONAL_SECRET not in json.dumps(catalog)


@pytest.mark.parametrize("topic_ids,document_ids", [([], []), (["unknown"], []), ([], ["unknown"])])
def test_invalid_selection_fails(service: BackupService, topic_ids: list[str], document_ids: list[str]) -> None:
    with pytest.raises(BackupError):
        service.export("test_user", topic_ids, document_ids)


def test_topic_only_never_reads_documents(service: BackupService) -> None:
    service.document_reader = Mock(side_effect=AssertionError("must not read documents"))
    assert json.loads(service.export("test_user", ["selected"], []))["data"]["documents"] == []
    service.document_reader.assert_not_called()


def test_document_only_never_reads_conversations(service: BackupService) -> None:
    service.archive = Mock()
    service.auth = Mock()
    assert json.loads(service.export("test_user", [], [DOCUMENT_ID]))["data"]["topics"] == []
    service.archive.read_histories.assert_not_called()
    service.auth.list_topics.assert_not_called()


@pytest.mark.parametrize("source", ["documents", "archive", "secrets"])
def test_read_failure_does_not_return_partial_export(service: BackupService, source: str) -> None:
    failure = Mock(side_effect=OSError("fictional internal error"))
    if source == "documents":
        service.document_reader = failure
    elif source == "archive":
        service.archive.read_histories = failure
    else:
        service.secret_reader = failure
    with pytest.raises(OSError):
        service.export("test_user", ["selected"], [DOCUMENT_ID])


def test_common_credential_patterns_are_redacted() -> None:
    text = ("-----BEGIN PRIVATE KEY-----\nFICTIONAL PRIVATE MATERIAL\n-----END PRIVATE KEY-----\n"
            "Bearer fictional-bearer-for-testing\napi_key=fictional-api-value\n"
            "password: fictional-password\nsk-fictionalonly123456789")
    result = redact_text(text, set())
    for value in ["FICTIONAL PRIVATE MATERIAL", "fictional-bearer-for-testing", "fictional-api-value",
                  "fictional-password", "sk-fictionalonly123456789"]:
        assert value not in result
    assert "已脱敏" in result


def test_config_secret_collection_is_isolated() -> None:
    fictional_config = {"api_key": FICTIONAL_SECRET, "model": "ordinary-model",
                        "nested": {"password": "fictional-nested-password"}}
    with patch.dict("os.environ", {"ACCESS_TOKEN": "fictional-env-token"}, clear=True), \
            patch.object(Path, "exists", return_value=True), \
            patch.object(Path, "read_text", return_value=json.dumps(fictional_config)), \
            patch("server.services.backup_service.dotenv_values", return_value={"API_KEY": "fictional-env-file-key"}):
        assert configured_secret_values(Path("fictional-config-root")) == {
            FICTIONAL_SECRET, "fictional-nested-password", "fictional-env-token", "fictional-env-file-key",
        }


def test_unreadable_config_cancels_redaction_check() -> None:
    with patch.dict("os.environ", {}, clear=True), patch.object(Path, "exists", return_value=True), \
            patch.object(Path, "read_text", side_effect=OSError("fictional-sensitive-error")):
        with pytest.raises(BackupError, match="密钥脱敏检查") as error:
            configured_secret_values(Path("fictional-config-root"))
    assert "fictional-sensitive-error" not in str(error.value)


@pytest.mark.parametrize("origin", ["https://localhost.evil", "https://evil.example", "null",
                                     "https://localhost@evil.example", "ftp://localhost"])
def test_external_origin_rejected(client: TestClient, origin: str) -> None:
    assert client.get("/api/backup/catalog", headers={"Origin": origin}).status_code == 403
    assert client.post("/api/backup/export", headers={"Origin": origin},
                       json={"topic_ids": ["selected"]}).status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:5173"])
def test_local_export_download(client: TestClient, origin: str) -> None:
    response = client.post("/api/backup/export", headers={"Origin": origin},
                           json={"topic_ids": ["selected"]})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert response.json()["data"]["documents"] == []


def test_api_failure_is_safe_and_has_no_partial_content(client: TestClient, service: BackupService) -> None:
    service.archive.read_histories = Mock(side_effect=RuntimeError("fictional-private-internal-error"))
    response = client.post("/api/backup/export", json={"topic_ids": ["selected"]})
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "未生成部分备份" in response.json()["detail"]
    assert "fictional-private-internal-error" not in response.text
    assert "content-disposition" not in response.headers


def test_api_rejects_extra_fields_and_empty_selection(client: TestClient) -> None:
    assert client.post("/api/backup/export", json={"include_keys": True}).status_code == 422
    assert client.post("/api/backup/export", json={}).status_code == 400


@pytest.mark.parametrize("documents,metadatas", [(["正文"], []), ([], [{"source": SOURCE}])])
def test_misaligned_chunks_fail_instead_of_exporting_partial_data(
    service: BackupService, documents: list[str], metadatas: list[dict],
) -> None:
    service.document_reader = lambda _: {"documents": documents, "metadatas": metadatas}
    with pytest.raises(ValueError):
        service.export("test_user", ["selected"], [DOCUMENT_ID])


def test_secret_reader_error_is_not_exposed(client: TestClient, service: BackupService) -> None:
    service.secret_reader = Mock(side_effect=OSError("fictional-private-config-value"))
    response = client.post("/api/backup/export", json={"topic_ids": ["selected"]})
    assert response.status_code == 503
    assert "fictional-private-config-value" not in response.text
    assert "data" not in response.json()
