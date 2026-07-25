"""Settings routes: /api/settings/*"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
_SETTINGS_PATH = Path(__file__).resolve().parent.parent.parent / "settings.json"


@router.get("")
async def get_settings(user: str = Depends(get_user)):
    with open(_SETTINGS_PATH, encoding="utf-8") as f:
        return json.load(f)


@router.put("")
async def update_settings(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    with open(_SETTINGS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    env = data.setdefault("env", {})
    for key in ("api_key", "base_url", "api_type"):
        if key in body:
            env[key] = body[key]
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    chat._clear_agent_cache()
    return {"message": "全局设置已更新"}


@router.post("/model")
async def switch_model(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    from model.config import change_model as config_change_model

    group = (body.get("group") or "").strip()
    model = (body.get("model") or "").strip()
    if not group or not model:
        raise HTTPException(status_code=400, detail="分组和模型不能为空")
    try:
        config_change_model(group, model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    chat._clear_agent_cache()
    return {"message": "模型已切换", "model": model}


@router.get("/tools")
async def get_tool_settings(
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    from main import TOOL_METADATA
    from campus_rag.auth import get_user_tool_prefs

    prefs = get_user_tool_prefs(user)
    result = []
    for tool in TOOL_METADATA:
        enabled = prefs.get(tool["name"], True) if prefs else True
        result.append({**tool, "enabled": enabled})
    return {"tools": result}


@router.put("/tools")
async def update_tool_settings(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    from campus_rag.auth import set_user_tool_prefs

    tools = body.get("tools")
    if not isinstance(tools, dict):
        raise HTTPException(status_code=400, detail="tools 必须是对象")
    set_user_tool_prefs(user, tools)
    chat.invalidate_user_agent(user)
    return {"message": "工具设置已更新"}
