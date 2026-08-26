# tools — Agent 工具

LangChain 工具定义，注册于根目录 `main.py`（`TOOL_METADATA` 与 `_shared_tools` 是前后端契约，`tests/test_web_tools.py` 守护一致性）。

## 工具清单

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索，返回标题/摘要/链接列表；`WEBSEARCH_PROVIDER=tavily`（需 `TAVILY_API_KEY`）或 `ddg`（免 Key 兜底） |
| `fetch_url` | 抓取指定 URL 正文（BeautifulSoup 剥离 script/style/nav 等非正文标签，超过 50000 字符截断） |

配置变量位于 `campus_rag/.env`（与嵌入/重排序同处），环境变量已存在时不覆盖。

## 约定

- 工具失败必须返回可读错误文本给 Agent（而非抛异常中断对话），并记录日志。
- 抓取的超长页面必须截断，防止撞穿 LLM context window。
- 新增工具时同步更新 `main.py` 的 `TOOL_METADATA`；旧用户的工具偏好字典中未出现的工具视为"未表态"，默认启用。
