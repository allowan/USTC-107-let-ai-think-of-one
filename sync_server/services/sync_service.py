"""Sync service: version checks, incremental and full sync."""

from datetime import datetime, timezone

import sync_server.database as db


class SyncService:

    @staticmethod
    def get_version() -> dict:
        return {
            "version": db.current_version(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def get_changes(since: int) -> dict:
        return db.get_changes(since)

    @staticmethod
    def get_full_snapshot() -> dict:
        return db.get_full_snapshot()
