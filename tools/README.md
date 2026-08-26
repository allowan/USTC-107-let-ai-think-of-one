# tools — Agent 工具

LangChain 工具定义，注册于根目录 `main.py`（`TOOL_METADATA` 与 `_shared_tools` 是前后端契约，`tests/test_web_search.py` 守护一致性）。

## 工具清单

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索，返回带 Markdown 链接的结果列表；`WEBSEARCH_PROVIDER=tavily`（默认，需 `TAVILY_API_KEY`）或 `ddg`（免 Key 兜底），Tavily 未配置/失败时自动回退 DuckDuckGo |
| `web_fetch` | 抓取指定公开 URL 的可见正文（SSRF 校验：拒绝本机/私有/保留地址，超过 2 MiB 或 20000 字符截断） |
| `ustc_web_search` | 只搜索配置白名单中的中国科大官方网站（`site:ustc.edu.cn` + 域名过滤） |
| `ustc_web_fetch` | 读取白名单内中国科大官方网页正文，重定向出白名单即拒绝 |

校站白名单配置在 `campus_rag/ustc_sites.json`；联网搜索配置变量（`WEBSEARCH_PROVIDER` / `TAVILY_API_KEY`）位于 `campus_rag/.env`（与嵌入/重排序同处），环境变量已存在时不覆盖。

`tools/ustc_crawler.py` 提供通知栏目采集辅助函数，供 `scripts/sync_ustc_columns.py` 使用，不注册为 Agent 工具。

## 约定

- 工具失败必须返回可读错误文本给 Agent（而非抛异常中断对话），并记录日志。
- 抓取的超长页面必须截断，防止撞穿 LLM context window。
- 新增工具时同步更新 `main.py` 的 `TOOL_METADATA`；旧用户的工具偏好字典中未出现的工具视为"未表态"，默认启用。
