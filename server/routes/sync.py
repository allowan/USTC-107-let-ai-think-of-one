"""Sync routes: /api/sync/* — 本地同步管理"""

from fastapi import APIRouter, Depends

from server.deps import get_user
from server.services.sync_service import SyncService, get_sync_service

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
async def sync_status(
    user: str = Depends(get_user),
    sync: SyncService = Depends(get_sync_service),
):
    local_version = sync._get_local_version()
    remote_version = sync.check_remote_version()
    return {
        "local_version": local_version,
        "remote_version": remote_version,
        "needs_sync": remote_version > local_version,
        "server_online": remote_version >= 0,
    }


@router.post("/now")
async def sync_now(
    user: str = Depends(get_user),
    sync: SyncService = Depends(get_sync_service),
):
    result = sync.sync()
    return result
