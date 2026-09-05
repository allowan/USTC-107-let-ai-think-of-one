"""Sync routes: /api/sync/* — 客户端同步（公开，无需认证）"""

from fastapi import APIRouter, Query

from sync_server.services.sync_service import SyncService

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/version")
def get_version() -> dict:
    """返回当前版本号和更新时间。客户端据此判断是否需要同步。"""
    return SyncService.get_version()


@router.get("/changes")
def get_changes(since: int = Query(0, ge=0)) -> dict:
    """增量同步：返回 since 版本之后的所有变更。since=0 表示从头开始。"""
    return SyncService.get_changes(since)


@router.get("/full")
def full_sync() -> dict:
    """全量同步：返回所有文档和当前版本号（兜底）。"""
    return SyncService.get_full_snapshot()
