"""
Sync service: pulls public notices from sync_server, updates local ChromaDB.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger("server")

ROOT = Path(__file__).resolve().parent.parent.parent
SYNC_STATE_PATH = ROOT / "data" / "sync_state.json"

# sync_server 地址：环境变量优先（部署位置可变，禁止硬编码生效）
SYNC_SERVER_URL = os.getenv("SYNC_SERVER_URL", "http://127.0.0.1:8001")


class SyncService:
    """Manages sync of public documents from remote sync_server to local ChromaDB."""

    @staticmethod
    def get_local_version() -> int:
        try:
            with open(SYNC_STATE_PATH, encoding="utf-8") as f:
                return json.load(f).get("version", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            return 0

    @staticmethod
    def _set_local_version(version: int):
        SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SYNC_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"version": version}, f)

    @staticmethod
    async def _fetch(url: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers={"User-Agent": "USTC-Campus-Client/1.0"})
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("Sync fetch failed: %s — %s", url, e)
            return None

    async def check_remote_version(self) -> int:
        data = await self._fetch(f"{SYNC_SERVER_URL}/api/sync/version")
        return data["version"] if data else -1

    async def sync(self, force_full: bool = False) -> dict:
        """Run sync. Returns dict with status and details."""
        remote_version = await self.check_remote_version()
        if remote_version < 0:
            return {"status": "error", "message": "无法连接到同步服务器"}

        local_version = self.get_local_version()

        if remote_version == 0:
            return {"status": "ok", "message": "同步服务器无数据", "version": 0}

        if remote_version == local_version and not force_full:
            return {"status": "ok", "message": "已是最新", "version": local_version}

        # Try incremental first
        if local_version > 0 and not force_full:
            changes = await self._fetch(
                f"{SYNC_SERVER_URL}/api/sync/changes?since={local_version}"
            )
            if changes and changes.get("version", 0) > local_version:
                try:
                    # 嵌入/入库是同步阻塞调用，必须在事件循环外执行，
                    # 否则同步期间整个后端无法响应任何请求
                    await asyncio.to_thread(self._apply_changes, changes)
                except Exception as e:
                    logger.error("应用增量变更失败: %s", e, exc_info=True)
                    return {"status": "error", "message": f"应用增量变更失败: {e}"}
                self._set_local_version(changes["version"])
                return {
                    "status": "ok",
                    "message": f"增量更新至版本 {changes['version']}",
                    "version": changes["version"],
                    "upserted": len(changes.get("upsert") or []),
                    "deleted": len(changes.get("deleted_sources") or []),
                }

        # Fallback: full sync
        full = await self._fetch(f"{SYNC_SERVER_URL}/api/sync/full")
        if not full:
            return {"status": "error", "message": "全量同步失败"}

        try:
            await asyncio.to_thread(self._apply_full_sync, full)
        except Exception as e:
            logger.error("应用全量同步失败: %s", e, exc_info=True)
            return {"status": "error", "message": f"应用全量同步失败: {e}"}
        self._set_local_version(full["version"])
        return {
            "status": "ok",
            "message": f"全量同步完成，版本 {full['version']}",
            "version": full["version"],
            "document_count": len(full.get("documents") or []),
        }

    def _apply_changes(self, changes: dict):
        """Apply incremental changes to local ChromaDB（经 campus_rag 公共门面）。"""
        from llama_index.core import Document
        from campus_rag import add_public_documents, delete_public_data

        upsert = changes.get("upsert") or []
        deleted = changes.get("deleted_sources") or []

        for source in deleted:
            delete_public_data(source)

        if upsert:
            docs = [Document(text=item["content"], metadata={"source": item["source"]}) for item in upsert]
            add_public_documents(docs)

    def _apply_full_sync(self, full: dict):
        """Full sync: wipe local public index and rebuild（经 campus_rag 公共门面）。"""
        from llama_index.core import Document
        from campus_rag import replace_public_documents

        documents = full.get("documents") or []
        docs = [Document(text=d["content"], metadata={"source": d["source"]}) for d in documents]
        replace_public_documents(docs)


_sync_service: SyncService | None = None


def get_sync_service() -> SyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service
