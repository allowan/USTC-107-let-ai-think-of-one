"""Settings routes: /api/settings/*"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
_SETTINGS_PATH = Path(__file__).resolve().parent.parent.parent / "settings.json"


def _load_settings() -> dict:
    """读取 settings.json；缺失或损坏时给出可操作的错误而非裸 500。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="settings.json 不存在，请复制 settings.example.json 为 settings.json 并填入配置",
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"settings.json 已损坏（{e}），请参照 settings.example.json 修复",
        )


def _save_settings(data: dict) -> None:
    """原子写回：先写临时文件再 rename，避免写一半崩溃导致配置永久损坏。"""
    tmp = _SETTINGS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, _SETTINGS_PATH)


@router.get("")
async def get_settings(user: str = Depends(get_user)):
    return _load_settings()


@router.put("")
async def update_settings(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    data = _load_settings()
    env = data.setdefault("env", {})
    for key in ("api_key", "base_url", "api_type"):
        value = body.get(key)
        # 空字符串写入会让 base_url 变成 ""，init_chat 无兜底直接报错；
        # 前端清空字段保存时应保留原值而非破坏配置。
        if key in body and isinstance(value, str) and value.strip():
            env[key] = value.strip()
    _save_settings(data)
    chat.clear_agent_cache()
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
    chat.clear_agent_cache()
    return {"message": "模型已切换", "model": model}


@router.get("/tools")
async def get_tool_settings(
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    from main import TOOL_METADATA
    from campus_rag import get_user_tool_prefs

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
    from campus_rag import set_user_tool_prefs

    tools = body.get("tools")
    if not isinstance(tools, dict):
        raise HTTPException(status_code=400, detail="tools 必须是对象")
    set_user_tool_prefs(user, tools)
    chat.invalidate_user_agent(user)
    return {"message": "工具设置已更新"}
