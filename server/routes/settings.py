"""Settings routes: /api/settings/*"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/api/settings", tags=["settings"])
_SETTINGS_PATH = Path(__file__).resolve().parent.parent.parent / "settings.json"
_SETTINGS_EXAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "settings.example.json"
_API_TYPES = {"chat-completions", "responses"}


def _load_default_settings() -> dict:
    """返回可展示的默认配置，不把示例占位 Key 当成真实凭据。"""
    try:
        with open(_SETTINGS_EXAMPLE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"默认设置模板不可用，请检查 settings.example.json（{e}）",
        ) from e
    api_key = data.get("env", {}).get("api_key", "")
    if api_key.startswith("your-") or api_key.startswith("sk-your-"):
        data["env"]["api_key"] = ""
    return data


def _load_settings() -> dict:
    """读取本地设置；首次启动缺少私有配置时返回安全的模板默认值。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return _load_default_settings()
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


def _normalize_model_group(body: dict) -> dict:
    """校验并规范化一个供应商分组，避免无效配置写入 settings.json。"""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="供应商分组必须是对象")
    group_name = str(body.get("group_name") or "").strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="供应商名称不能为空")

    base_url = str(body.get("base_url") or "").strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL 不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Base URL 必须以 http:// 或 https:// 开头")

    api_key = str(body.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    raw_models = body.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise HTTPException(status_code=400, detail="每个供应商至少需要配置一个模型")
    models = []
    seen_ids = set()
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            raise HTTPException(status_code=400, detail="模型配置必须是对象")
        request_id = str(raw_model.get("request_id") or "").strip()
        show_id = str(raw_model.get("show_id") or request_id).strip()
        if not request_id:
            raise HTTPException(status_code=400, detail="模型 ID 不能为空")
        identity = request_id.casefold()
        if identity in seen_ids:
            raise HTTPException(status_code=400, detail=f"模型 ID 重复: {request_id}")
        seen_ids.add(identity)
        models.append({
            "request_id": request_id,
            "show_id": show_id or request_id,
            "toolCalling": bool(raw_model.get("toolCalling", True)),
            "vision": bool(raw_model.get("vision", False)),
        })

    api_type = str(body.get("api_type") or "chat-completions").strip() or "chat-completions"
    if api_type not in _API_TYPES:
        raise HTTPException(status_code=400, detail="API Type 必须是 chat-completions 或 responses")

    return {
        "group_name": group_name,
        "vendor": str(body.get("vendor") or "customendpoint").strip() or "customendpoint",
        "api_key": api_key,
        "api_type": api_type,
        "base_url": base_url,
        "models": models,
    }


def _find_group_index(groups: list, group_name: str) -> int | None:
    target = group_name.casefold()
    return next(
        (index for index, group in enumerate(groups)
         if str(group.get("group_name") or "").casefold() == target),
        None,
    )


def _apply_active_group_connection(data: dict, group: dict) -> None:
    """活动模型属于该分组时，立即应用分组连接参数。"""
    env = data.setdefault("env", {})
    active_model = str(env.get("model") or "").strip()
    group_model_ids = {
        str(model.get("request_id") or "").strip()
        for model in group.get("models", []) if isinstance(model, dict)
    }
    if active_model and active_model in group_model_ids:
        for key in ("api_key", "base_url", "api_type"):
            env[key] = group[key]


@router.get("")
async def get_settings(user: str = Depends(get_user)):
    data = _load_settings()
    file_model = str(data.get("env", {}).get("model") or "")
    env_model = os.environ.get("LLM_MODEL", "").strip()
    data["runtime"] = {
        "effective_model": env_model or file_model,
        "model_source": "environment" if env_model else "settings",
        "model_locked": bool(env_model),
    }
    return data


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
    from model.config import select_model

    group = (body.get("group") or "").strip()
    model = (body.get("model") or "").strip()
    if not group or not model:
        raise HTTPException(status_code=400, detail="分组和模型不能为空")
    if os.environ.get("LLM_MODEL", "").strip():
        raise HTTPException(
            status_code=409,
            detail="当前模型由环境变量 LLM_MODEL 固定，请移除该变量后再从设置中切换",
        )
    try:
        data = _load_settings()
        selected = select_model(data, group, model)
        _save_settings(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    chat.clear_agent_cache()
    return {"message": "模型已切换", **selected}


@router.post("/available-models")
async def get_available_models(
    body: dict,
    user: str = Depends(get_user),
):
    """通过 OpenAI 兼容接口的 /models 端点获取可用模型。"""
    data = _load_settings()
    env = data.get("env", {})
    base_url = str(body.get("base_url") or env.get("base_url") or "").strip()
    api_key = str(body.get("api_key") or env.get("api_key") or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="请填写有效的 HTTP(S) Base URL")

    url = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"模型列表请求失败（上游 HTTP {exc.response.status_code}）",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"无法获取模型列表: {exc}") from exc

    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise HTTPException(status_code=502, detail="模型列表响应缺少 data 数组")
    model_ids = sorted({
        str(item.get("id") or "").strip()
        for item in raw_models if isinstance(item, dict) and item.get("id")
    }, key=str.casefold)
    return {"models": model_ids, "url": url}


@router.post("/groups", status_code=201)
async def add_model_group(
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    group = _normalize_model_group(body)
    data = _load_settings()
    groups = data.setdefault("groups", [])
    if _find_group_index(groups, group["group_name"]) is not None:
        raise HTTPException(status_code=409, detail=f"供应商分组已存在: {group['group_name']}")
    groups.append(group)
    _apply_active_group_connection(data, group)
    _save_settings(data)
    chat.clear_agent_cache()
    return {"message": "供应商分组已添加", "group": group}


@router.put("/groups/{group_name}")
async def update_model_group(
    group_name: str,
    body: dict,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    group = _normalize_model_group(body)
    data = _load_settings()
    groups = data.setdefault("groups", [])
    index = _find_group_index(groups, group_name)
    if index is None:
        raise HTTPException(status_code=404, detail=f"未找到供应商分组: {group_name}")
    duplicate = _find_group_index(groups, group["group_name"])
    if duplicate is not None and duplicate != index:
        raise HTTPException(status_code=409, detail=f"供应商分组已存在: {group['group_name']}")

    active_model = str(data.get("env", {}).get("model") or "")
    new_model_ids = {model["request_id"] for model in group["models"]}
    other_model_ids = {
        model.get("request_id")
        for group_index, item in enumerate(groups) if group_index != index
        for model in item.get("models", [])
    }
    if active_model and active_model not in new_model_ids and active_model not in other_model_ids:
        raise HTTPException(status_code=409, detail="不能从供应商分组中移除当前正在使用的模型")

    groups[index] = group
    _apply_active_group_connection(data, group)
    _save_settings(data)
    chat.clear_agent_cache()
    return {"message": "供应商分组已更新", "group": group}


@router.delete("/groups/{group_name}")
async def delete_model_group(
    group_name: str,
    user: str = Depends(get_user),
    chat: ChatService = Depends(get_chat_service),
):
    data = _load_settings()
    groups = data.setdefault("groups", [])
    index = _find_group_index(groups, group_name)
    if index is None:
        raise HTTPException(status_code=404, detail=f"未找到供应商分组: {group_name}")
    if len(groups) == 1:
        raise HTTPException(status_code=409, detail="至少需要保留一个供应商分组")

    active_model = str(data.get("env", {}).get("model") or "")
    remaining_model_ids = {
        model.get("request_id")
        for group_index, item in enumerate(groups) if group_index != index
        for model in item.get("models", [])
    }
    if active_model and active_model not in remaining_model_ids:
        raise HTTPException(status_code=409, detail="不能删除包含当前使用模型的供应商分组")

    removed = groups.pop(index)
    _save_settings(data)
    chat.clear_agent_cache()
    return {"message": "供应商分组已删除", "group_name": removed["group_name"]}


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
