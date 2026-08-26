"""Admin routes: /api/admin/notices/* — 通知管理（需 admin token）"""

from fastapi import APIRouter, Depends, HTTPException

from sync_server.deps import require_admin
from sync_server.services.admin_service import AdminService, get_admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 注意：路径参数已由框架解码一次，禁止再次 unquote——双重解码会把字面含 %
# 的 source（如 "100%进度"）损坏，导致读取/更新/删除找错目标。


def _admin() -> AdminService:
    return get_admin_service()


@router.get("/notices")
async def list_notices(admin=Depends(require_admin), svc=Depends(_admin)):
    return {"notices": svc.list_notices()}


@router.post("/notices")
async def add_notice(body: dict, admin=Depends(require_admin), svc=Depends(_admin)):
    content = (body.get("content") or "").strip()
    source = (body.get("source") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    result = svc.add_notice(content, source)
    return {"message": "通知已添加", **result}


@router.get("/notices/{source}/content")
async def get_notice(source: str, admin=Depends(require_admin), svc=Depends(_admin)):
    notice = svc.get_notice(source)
    if not notice:
        raise HTTPException(status_code=404, detail="通知不存在")
    return notice


@router.put("/notices/{source}")
async def update_notice(source: str, body: dict, admin=Depends(require_admin), svc=Depends(_admin)):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if svc.get_notice(source) is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    result = svc.update_notice(source, content)
    return {"message": "通知已更新", **result}


@router.delete("/notices/{source}")
async def delete_notice(source: str, admin=Depends(require_admin), svc=Depends(_admin)):
    deleted = svc.delete_notice(source)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"message": "通知已删除"}


@router.get("/stats")
async def get_stats(admin=Depends(require_admin), svc=Depends(_admin)):
    return svc.get_stats()
