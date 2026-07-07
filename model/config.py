import json
import os
from pathlib import Path
from langchain.chat_models import init_chat_model

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def read_json() -> dict:
    """读取 settings.json 中的 env 配置（文件不存在时返回空字典）。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("env", {})
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

def change_model(group: str, model: str):
    """更改模型选项：根据 group 与 model 索引更新 env 并重新初始化模型"""
    settings_path = Path(__file__).resolve().parent.parent / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)

    groups = data.get("groups", [])
    # 按 group_name 定位分组
    target_group = next(
        (g for g in groups if g.get("group_name") == group), None
    )
    if target_group is None:
        raise ValueError(f"未找到分组: {group}")

    # 在该分组的 models 中按 show_id 定位模型（回退匹配 request_id）
    models = target_group.get("models", [])
    target_model = next(
        (m for m in models if m.get("show_id") == model or m.get("request_id") == model),
        None,
    )
    if target_model is None:
        raise ValueError(f"在分组 '{group}' 中未找到模型: {model}")

    # 用分组与模型信息更新 env
    env = data.setdefault("env", {})
    env["api_key"] = target_group.get("api_key", "")
    env["base_url"] = target_group.get("base_url", "")
    env["api_type"] = target_group.get("api_type", "chat-completions")
    env["model"] = target_model.get("request_id", "")

    # 写回 settings.json
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # 应用初始化
    return init_chat()
