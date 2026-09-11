"""按字段白名单导出个人文字数据，绝不打包配置或原始数据库。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import dotenv_values

from server.services.auth_service import AuthService
from server.services.conversation_archive import ConversationArchive

logger = logging.getLogger(__name__)
MAX_BACKUP_BYTES = 20 * 1024 * 1024
BACKUP_FORMAT = "campus-personal-text-backup"
ROOT = Path(__file__).resolve().parents[2]
_SECRET_FIELD = re.compile(r"(?:api.?key|(?:^|[_-])key$|token|secret|password|passwd|credential|private.?key)", re.I)


class BackupError(ValueError):
    """可向用户展示的备份操作错误，不包含内部凭据。"""


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


class BackupService:
    """从业务数据读取可见文本，生成可移植且无配置项的 JSON 备份。"""

    def __init__(self, auth: AuthService | None = None, archive: ConversationArchive | None = None,
                 document_reader: Callable[[str], dict] | None = None,
                 secret_reader: Callable[[], set[str]] | None = None) -> None:
        self.auth = auth or AuthService()
        self.archive = archive or ConversationArchive()
        self.document_reader = document_reader or _read_documents
        self.secret_reader = secret_reader or configured_secret_values

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
        return result


def get_backup_service() -> BackupService:
    """提供无模型初始化的备份服务。"""
    return BackupService()
