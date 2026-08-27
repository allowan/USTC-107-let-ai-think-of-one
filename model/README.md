# model — Agent LLM 配置

LangChain `init_chat_model` 的初始化与热切换（`config.py`），供 `main.py` 的 Agent 与设置路由使用。

## 配置（`settings.json`，项目根）

```json
{
    "env": {
        "api_key": "sk-...",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_type": "chat-completions"
    },
    "groups": [ ... ]
}
```

| 键 | 说明 |
|---|---|
| `env.api_key` | API Key（必填；缺失时 `init_chat()` 抛出可操作错误） |
| `env.base_url` | API 地址 |
| `env.model` | 模型名 |
| `groups` | 模型分组（前端"切换模型"的来源），`change_model(group, model)` 按 `group_name` + `show_id/request_id` 定位并写回 `env` |

环境变量优先级更高：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 可分别覆盖 `env` 中的对应项。

## 行为要点

- `init_chat()` 每次读取最新配置，配合 `ChatService.clear_agent_cache()` 实现热切换。
- `change_model()` 原子写回 `settings.json`（临时文件 + rename），写一半崩溃不会损坏配置。
- 路由侧更新 `env` 时会忽略空字符串，避免清空字段保存打断 LLM 初始化。
