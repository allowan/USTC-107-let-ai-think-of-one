"""Admin authentication for sync_server."""

import json
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"

security = HTTPBearer(auto_error=False)


def _get_admin_token() -> str:
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        return json.load(f).get("admin_token", "")


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    token = _get_admin_token()
    if not token:
        return  # No token configured — allow all (dev mode)
    if credentials is None:
        raise HTTPException(status_code=401, detail="需要管理员令牌")
    if credentials.credentials != token:
        raise HTTPException(status_code=403, detail="管理员令牌无效")
