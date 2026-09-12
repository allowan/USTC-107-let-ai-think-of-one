"""按字段白名单导出个人文字数据，绝不打包配置或原始数据库。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.services.auth_service import AuthService
from server.services.conversation_archive import ConversationArchive

logger = logging.getLogger(__name__)
MAX_BACKUP_BYTES = 20 * 1024 * 1024
BACKUP_FORMAT = "campus-personal-text-backup"
ROOT = Path(__file__).resolve().parents[2]
_RESTORE_LOCK = threading.Lock()
_SECRET_FIELD = re.compile(r"(?:api.?key|(?:^|[_-])key$|token|secret|password|passwd|credential|private.?key)", re.I)


class BackupError(ValueError):
    """可向用户展示的备份操作错误，不包含内部凭据。"""


class VisibleMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_BACKUP_BYTES)


class ArchivedTopic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=10000)
    messages: list[VisibleMessage] = Field(max_length=20000)


class ArchivedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=10000)
    content: str = Field(max_length=MAX_BACKUP_BYTES)


class ArchivedData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topics: list[ArchivedTopic] = Field(max_length=200)
    documents: list[ArchivedDocument] = Field(max_length=500)


class BackupEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["campus-personal-text-backup"]
    version: int
    created_at: str
    data: ArchivedData
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


def parse_backup(content: bytes) -> dict:
    """严格验证版本、字段与完整性，不加载任意对象或写入数据。"""
    if len(content) > MAX_BACKUP_BYTES:
        raise BackupError("备份文件不能超过20 MB")

    def unique_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise BackupError("备份包含重复字段，无法确定内容")
            result[key] = value
        return result

    try:
        raw = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_keys)
        envelope = BackupEnvelope.model_validate(raw)
        if envelope.version != 1:
            raise BackupError("不支持此备份版本，请使用兼容的应用版本")
        datetime.fromisoformat(envelope.created_at)
        unsigned = {key: value for key, value in raw.items() if key != "checksum"}
        if not hmac.compare_digest(hashlib.sha256(_canonical(unsigned)).hexdigest(), envelope.checksum):
            raise BackupError("备份完整性校验失败，文件可能已损坏或修改")
        if not envelope.data.topics and not envelope.data.documents:
            raise BackupError("备份中没有可恢复的内容")
        return envelope.model_dump()
    except BackupError:
        logger.warning("备份校验被拒绝，未恢复任何数据")
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, ValidationError):
        logger.warning("备份格式校验失败，未恢复任何数据")
        raise BackupError("备份格式无效；只支持本应用导出的版本1文字备份") from None


def configured_secret_values(root: Path = ROOT) -> set[str]:
    """只提取用于脱敏比对的凭据值，不返回或序列化配置内容。"""
    values: set[str] = set()

    def collect(data: object, sensitive: bool = False) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                collect(value, sensitive or bool(_SECRET_FIELD.search(str(key))))
        elif isinstance(data, list):
            for value in data:
                collect(value, sensitive)
        elif sensitive and isinstance(data, str) and data.strip():
            values.add(data.strip())

    collect(dict(os.environ))
    try:
        for path in (root / "settings.json", root / "sync_server" / "settings.json"):
            if path.exists():
                collect(json.loads(path.read_text(encoding="utf-8-sig")))
        env_path = root / "campus_rag" / ".env"
        if env_path.exists():
            collect(dict(dotenv_values(env_path)))
    except (OSError, ValueError):
        logger.warning("无法读取脱敏所需的本地配置，取消导出")
        raise BackupError("无法完成密钥脱敏检查，请检查配置文件是否可读后重试") from None
    return values


def redact_text(text: str, secrets: set[str]) -> str:
    """移除已配置凭据及常见带标识的密钥、令牌和私钥块。"""
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "[已脱敏]")
    text = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[私钥已脱敏]", text, flags=re.S)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b", "[已脱敏]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[已脱敏]", text)
    text = re.sub(
        r'''(?i)((?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|密码|密钥)["']?\s*[:=：]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;，；}\]]+)''',
        r"\1[已脱敏]", text,
    )
    return text


def _canonical(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_documents(username: str) -> dict:
    from campus_rag import read_user_data_for_backup
    return read_user_data_for_backup(username)


def _write_document(username: str, source: str, content: str) -> None:
    from campus_rag import update_user_data
    update_user_data(username, source, content)


def _document_matches(source: str, content: str, chunks: list[tuple[int, str]]) -> bool:
    from campus_rag import backup_document_matches
    return backup_document_matches(source, content, chunks)


class BackupService:
    """从业务数据读取可见文本，生成可移植且无配置项的 JSON 备份。"""

    def __init__(self, auth: AuthService | None = None, archive: ConversationArchive | None = None,
                 document_reader: Callable[[str], dict] | None = None,
                 secret_reader: Callable[[], set[str]] | None = None,
                 document_writer: Callable[[str, str, str], None] | None = None) -> None:
        self.auth = auth or AuthService()
        self.archive = archive or ConversationArchive()
        self.document_reader = document_reader or _read_documents
        self.secret_reader = secret_reader or configured_secret_values
        self.document_writer = document_writer or _write_document

    def _documents(self, username: str) -> dict[str, dict]:
        data = self.document_reader(username)
        grouped: dict[str, list[tuple[int, str]]] = {}
        for meta, content in zip(data.get("metadatas") or [], data.get("documents") or [], strict=True):
            meta = meta or {}
            source = meta.get("source") or "手动输入"
            if not isinstance(source, str) or not isinstance(content, str):
                raise BackupError("个人资料内容异常，导出已取消")
            order = meta.get("chunk_index", 0)
            grouped.setdefault(source, []).append((order if isinstance(order, int) else 0, content))
        return {
            hashlib.sha256(source.encode("utf-8")).hexdigest(): {
                "source": source, "content": "\n".join(text for _, text in sorted(chunks, key=lambda item: item[0])),
                "chunks": chunks,
            } for source, chunks in grouped.items()
        }

    def catalog(self, username: str) -> dict:
        """列出可选择的话题与资料；读取失败明确标注，可独立重试。"""
        secrets = self.secret_reader()
        errors: list[str] = []
        topics, documents = [], []
        try:
            topics = [{"id": item["id"], "name": redact_text(item["name"], secrets)} for item in self.auth.list_topics(username)]
        except Exception:
            logger.warning("备份话题目录读取失败")
            errors.append("话题读取失败，请刷新重试")
        try:
            documents = [{"id": key, "name": redact_text(item["source"], secrets), "characters": len(item["content"])}
                         for key, item in self._documents(username).items()]
        except Exception:
            logger.warning("备份资料目录读取失败")
            errors.append("个人资料读取失败，请刷新重试；仍可单独导出对话")
        return {"topics": topics, "documents": documents, "errors": errors}

    def export(self, username: str, topic_ids: list[str], document_ids: list[str]) -> bytes:
        """导出显式选中的可见文本，遇到缺失或读取错误整体失败。"""
        if not topic_ids and not document_ids:
            raise BackupError("请至少选择一项对话或资料")
        if len(topic_ids) > 200 or len(document_ids) > 500:
            raise BackupError("一次最多导出200个话题和500份资料，请分批导出")
        secrets = self.secret_reader()
        topics = {item["id"]: item for item in self.auth.list_topics(username)} if topic_ids else {}
        documents = self._documents(username) if document_ids else {}
        if set(topic_ids) - topics.keys() or set(document_ids) - documents.keys():
            raise BackupError("所选数据已不存在，请刷新列表后重新选择")
        chosen_topics = [topics[key] for key in dict.fromkeys(topic_ids)]
        histories = self.archive.read_histories([item["thread_id"] for item in chosen_topics]) if chosen_topics else {}
        data = {
            "topics": [{"name": redact_text(item["name"], secrets), "messages": [
                {"role": message["role"], "content": redact_text(message["content"], secrets)}
                for message in histories[item["thread_id"]] if message["role"] in ("user", "assistant")
            ]} for item in chosen_topics],
            "documents": [{"source": redact_text(documents[key]["source"], secrets),
                           "content": redact_text(documents[key]["content"], secrets)} for key in dict.fromkeys(document_ids)],
        }
        envelope = {"format": BACKUP_FORMAT, "version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "data": data}
        envelope["checksum"] = hashlib.sha256(_canonical(envelope)).hexdigest()
        result = json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(result) > MAX_BACKUP_BYTES:
            raise BackupError("备份超过20 MB，请减少选择的内容后分批导出")
        # 导出与恢复共用格式校验，不能生成本应用无法恢复的备份。
        parse_backup(result)
        return result

    def preview_restore(self, content: bytes) -> dict:
        """验证备份并展示恢复范围，预览不写入任何业务数据。"""
        backup = parse_backup(content)
        secrets = self.secret_reader()
        return {
            "checksum": backup["checksum"], "created_at": backup["created_at"],
            "topics": [{"name": redact_text(topic["name"], secrets), "message_count": len(topic["messages"])}
                       for topic in backup["data"]["topics"]],
            "documents": [{"source": redact_text(doc["source"], secrets), "characters": len(doc["content"])}
                          for doc in backup["data"]["documents"]],
        }

    def restore(self, username: str, content: bytes, confirmed_checksum: str) -> dict:
        """确认后恢复为新副本，已恢复项跳过，失败项可再次尝试。"""
        backup = parse_backup(content)
        if not re.fullmatch(r"[0-9a-f]{64}", confirmed_checksum) or not hmac.compare_digest(backup["checksum"], confirmed_checksum):
            raise BackupError("确认内容与预览不一致，请重新预览")
        secrets = self.secret_reader()
        results = []
        with _RESTORE_LOCK:
            # 先确认现有资料可读，不能将读取故障当作“不存在”后覆盖。
            existing = self._documents(username) if backup["data"]["documents"] else {}
            for index, item in enumerate(backup["data"]["topics"]):
                name = redact_text(item["name"], secrets)
                try:
                    topic = self.auth.create_restored_topic(username, name, backup["checksum"], index)
                    messages = [{"role": message["role"], "content": redact_text(message["content"], secrets)} for message in item["messages"]]
                    written = self.archive.write_history_if_empty(topic["thread_id"], messages)
                    results.append({"kind": "topic", "name": name, "status": "restored" if written else "skipped", "message": ""})
                except Exception:
                    logger.warning("单个备份话题恢复失败，可重试")
                    results.append({"kind": "topic", "name": name, "status": "failed", "message": "对话恢复失败，可重试；已有对话未覆盖"})
            for index, item in enumerate(backup["data"]["documents"]):
                name = redact_text(item["source"], secrets)
                suffix = f"（恢复 {backup['checksum'][:16]}-{index + 1}）"
                source = name + suffix
                try:
                    text = redact_text(item["content"], secrets)
                    copies = [doc for doc in existing.values() if doc["source"].endswith(suffix)]
                    if copies:
                        complete = len(copies) == 1 and _document_matches(copies[0]["source"], text, copies[0]["chunks"])
                        results.append({"kind": "document", "name": name,
                                        "status": "skipped" if complete else "failed",
                                        "message": "" if complete else "已有恢复副本不完整或已修改，请核对；未覆盖已有资料"})
                        continue
                    self.document_writer(username, source, text)
                    results.append({"kind": "document", "name": name, "status": "restored", "message": ""})
                except Exception:
                    logger.warning("单份备份资料恢复失败，可重试")
                    results.append({"kind": "document", "name": name, "status": "failed", "message": "资料恢复失败，请检查嵌入服务后重试"})
        return {"results": results, "restored": sum(item["status"] == "restored" for item in results),
                "skipped": sum(item["status"] == "skipped" for item in results),
                "failed": sum(item["status"] == "failed" for item in results)}


def get_backup_service() -> BackupService:
    """提供无模型初始化的备份服务。"""
    return BackupService()
