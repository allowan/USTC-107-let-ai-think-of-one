import json
import os
from pathlib import Path
from langchain.chat_models import init_chat_model

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def read_json() -> dict:
    """读取当前模型的有效配置，活动分组连接参数优先于全局 env。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        env = dict(data.get("env", {}))
        active_model = str(env.get("model") or "").strip()
        active_group = next((
            group for group in data.get("groups", [])
            if any(
                str(model.get("request_id") or "").strip() == active_model
                for model in group.get("models", []) if isinstance(model, dict)
            )
        ), None)
        if active_group:
            for key in ("api_key", "base_url", "api_type"):
                value = active_group.get(key)
                if isinstance(value, str) and value.strip():
                    env[key] = value.strip()
        return env
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def init_chat():
    """初始化聊天模型。环境变量优先，settings.json 作为 fallback。"""
    file_env = read_json()

    api_key = os.environ.get("LLM_API_KEY") or file_env.get("api_key", "")
    base_url = os.environ.get("LLM_BASE_URL") or file_env.get("base_url", "https://api.deepseek.com")
    model_id = os.environ.get("LLM_MODEL") or file_env.get("model", "deepseek-v4-flash")

    if not api_key:
        raise RuntimeError(
            "未配置 LLM API Key。请在环境变量 LLM_API_KEY 中设置，"
            "或复制 settings.example.json 为 settings.json 并填入 api_key。"
        )

    return init_chat_model(
        model=model_id,
        model_provider="openai",
        base_url=base_url,
        api_key=api_key,
    )


def select_model(data: dict, group: str, model: str) -> dict:
    """在设置数据中选择模型，并返回规范化后的模型信息。"""
    groups = data.get("groups", [])
    target_group = next(
        (item for item in groups if item.get("group_name") == group), None
    )
    if target_group is None:
        raise ValueError(f"未找到分组: {group}")

    models = target_group.get("models", [])
    target_model = next(
        (item for item in models if item.get("show_id") == model or item.get("request_id") == model),
        None,
    )
    if target_model is None:
        raise ValueError(f"在分组 '{group}' 中未找到模型: {model}")

    request_id = str(target_model.get("request_id") or "").strip()
    if not request_id:
        raise ValueError(f"分组 '{group}' 中的模型缺少 request_id")

    env = data.setdefault("env", {})
    env["model"] = request_id
    # 分组级连接参数是可选覆盖项。空字符串表示沿用当前全局配置，不能把
    # 已配置的 Key/Base URL 擦除，否则一次模型切换就会破坏聊天功能。
    for key in ("api_key", "base_url", "api_type"):
        value = target_group.get(key)
        if isinstance(value, str) and value.strip():
            env[key] = value.strip()

    return {
        "group": str(target_group.get("group_name") or group),
        "model": request_id,
        "show_id": str(target_model.get("show_id") or request_id),
    }


def change_model(group: str, model: str, settings_path: Path | None = None) -> dict:
    """更新 settings.json 中的模型选择；模型在下一次请求时按需初始化。"""
    settings_path = settings_path or Path(__file__).resolve().parent.parent / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)
    selected = select_model(data, group, model)

    # 写回 settings.json（原子写：先临时文件再 rename，避免写一半损坏配置）
    tmp = settings_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, settings_path)

    return selected
