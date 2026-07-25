"""
Sync service: pulls public notices from sync_server, updates local ChromaDB.
"""

import json
import logging
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger("server")

ROOT = Path(__file__).resolve().parent.parent.parent
SYNC_STATE_PATH = ROOT / "data" / "sync_state.json"

# Default sync_server URL — override via environment variable
SYNC_SERVER_URL = "http://127.0.0.1:8001"


class SyncService:
    """Manages sync of public documents from remote sync_server to local ChromaDB."""

    @staticmethod
    def _get_local_version() -> int:
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
    def _fetch(url: str) -> dict | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "USTC-Campus-Client/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning("Sync fetch failed: %s — %s", url, e)
            return None

    def check_remote_version(self) -> int:
        data = self._fetch(f"{SYNC_SERVER_URL}/api/sync/version")
        return data["version"] if data else -1

    def sync(self, force_full: bool = False) -> dict:
        """Run sync. Returns dict with status and details."""
        remote_version = self.check_remote_version()
        if remote_version < 0:
            return {"status": "error", "message": "无法连接到同步服务器"}

        local_version = self._get_local_version()

        if remote_version == 0:
            return {"status": "ok", "message": "同步服务器无数据", "version": 0}

        if remote_version == local_version and not force_full:
            return {"status": "ok", "message": "已是最新", "version": local_version}

        # Try incremental first
        if local_version > 0 and not force_full:
            changes = self._fetch(
                f"{SYNC_SERVER_URL}/api/sync/changes?since={local_version}"
            )
            if changes and changes.get("version", 0) > local_version:
                self._apply_changes(changes)
                self._set_local_version(changes["version"])
                return {
                    "status": "ok",
                    "message": f"增量更新至版本 {changes['version']}",
                    "version": changes["version"],
                    "upserted": len(changes.get("upsert") or []),
                    "deleted": len(changes.get("deleted_sources") or []),
                }

        # Fallback: full sync
        full = self._fetch(f"{SYNC_SERVER_URL}/api/sync/full")
        if not full:
            return {"status": "error", "message": "全量同步失败"}

        self._apply_full_sync(full)
        self._set_local_version(full["version"])
        return {
            "status": "ok",
            "message": f"全量同步完成，版本 {full['version']}",
            "version": full["version"],
            "document_count": len(full.get("documents") or []),
        }

    def _apply_changes(self, changes: dict):
        """Apply incremental changes to local ChromaDB."""
        from llama_index.core import Document
        from campus_rag.index_manager import RAGSystem
        from campus_rag.query import _reset

        rag = RAGSystem()
        upsert = changes.get("upsert") or []
        deleted = changes.get("deleted_sources") or []

        for source in deleted:
            rag.delete_public_documents_by_source(source)

        if upsert:
            docs = [Document(text=item["content"], metadata={"source": item["source"]}) for item in upsert]
            rag.add_documents_to_public(docs)

        _reset()

    def _apply_full_sync(self, full: dict):
        """Full sync: wipe local public index and rebuild."""
        from llama_index.core import Document
        from campus_rag.index_manager import RAGSystem
        from campus_rag.query import _reset

        rag = RAGSystem()

        # Clear existing public collection
        try:
            rag.chroma_client.delete_collection("public")
        except Exception:
            pass

        documents = full.get("documents") or []
        if documents:
            docs = [Document(text=d["content"], metadata={"source": d["source"]}) for d in documents]
            rag.create_public_index_via_docs(docs)

        _reset()


_sync_service: SyncService | None = None


def get_sync_service() -> SyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service
