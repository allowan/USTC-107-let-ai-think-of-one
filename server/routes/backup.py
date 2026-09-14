"""个人文字备份接口。"""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from server.deps import get_user
from server.deps import ensure_local_origin as ensure_backup_origin
from server.services.backup_service import MAX_BACKUP_BYTES, BackupError, BackupService, get_backup_service

router = APIRouter(prefix="/api/backup", tags=["backup"])
logger = logging.getLogger(__name__)


class ExportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_ids: list[str] = Field(default_factory=list, max_length=200)
    document_ids: list[str] = Field(default_factory=list, max_length=500)


@router.get("/catalog")
async def backup_catalog(request: Request, user: str = Depends(get_user),
                         service: BackupService = Depends(get_backup_service)) -> dict:
    """读取可备份数据目录，不返回配置。"""
    ensure_backup_origin(request)
    try:
        return await asyncio.to_thread(service.catalog, user)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.warning("备份目录检查失败，可重试")
        raise HTTPException(status_code=503, detail="备份目录检查失败，请稍后重试") from None


@router.post("/export")
async def export_backup(payload: ExportSelection, request: Request, user: str = Depends(get_user),
                        service: BackupService = Depends(get_backup_service)) -> Response:
    """下载选中对话和资料的脱敏 JSON。"""
    ensure_backup_origin(request)
    try:
        content = await asyncio.to_thread(service.export, user, payload.topic_ids, payload.document_ids)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.warning("备份导出失败，可重试；未返回部分数据")
        raise HTTPException(status_code=503, detail="备份读取失败，未生成部分备份，请稍后重试") from None
    return Response(content, media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="campus-personal-backup.json"',
        "Cache-Control": "no-store",
    })


@router.post("/preview")
async def preview_backup(request: Request, file: UploadFile = File(...), user: str = Depends(get_user),
                         service: BackupService = Depends(get_backup_service)) -> dict:
    """上传文件只用于校验和预览，不执行恢复。"""
    ensure_backup_origin(request)
    content = await file.read(MAX_BACKUP_BYTES + 1)
    try:
        return await asyncio.to_thread(service.preview_restore, content)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.warning("备份预览检查失败，可重试")
        raise HTTPException(status_code=503, detail="备份预览检查失败，请稍后重试") from None


@router.post("/restore")
async def restore_backup(request: Request, file: UploadFile = File(...), confirmed_checksum: str = Form(...),
                         user: str = Depends(get_user), service: BackupService = Depends(get_backup_service)) -> dict:
    """再次验证用户已确认的文件后恢复为新副本。"""
    ensure_backup_origin(request)
    content = await file.read(MAX_BACKUP_BYTES + 1)
    try:
        return await asyncio.to_thread(service.restore, user, content, confirmed_checksum)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.warning("恢复前数据检查失败，可重试")
        raise HTTPException(status_code=503, detail="恢复前检查失败，请检查本地数据和配置后重试") from None
