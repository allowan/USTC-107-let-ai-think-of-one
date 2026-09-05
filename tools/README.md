# tools — Agent 工具

LangChain 工具定义，注册于根目录 `main.py`（`TOOL_METADATA` 与 `_shared_tools` 是前后端契约，`tests/test_web_search.py` 守护一致性）。

## 工具清单

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索，返回带 Markdown 链接的结果列表；`WEBSEARCH_PROVIDER=tavily`（默认，需 `TAVILY_API_KEY`）或 `ddg`（免 Key 兜底），Tavily 未配置/失败时自动回退 DuckDuckGo |
| `web_fetch` | 抓取指定公开 URL 的可见正文（SSRF 校验：拒绝本机/私有/保留地址，超过 2 MiB 或 20000 字符截断） |
| `ustc_web_search` | 只搜索配置白名单中的中国科大官方网站（`site:ustc.edu.cn` + 域名过滤） |
| `ustc_web_fetch` | 读取白名单内中国科大官方网页正文，重定向出白名单即拒绝 |
| `course_review_search` | 搜索评课社区（icourse.club）公开课程页，站内检索失败时回退 `site:icourse.club` 网页搜索，结果只保留课程详情页链接 |
| `course_review_fetch` | 读取评课社区白名单内的课程详情页正文（仅允许 `/course/` 路径） |

校站白名单配置在 `campus_rag/ustc_sites.json`，评课社区配置在 `campus_rag/course_review_sites.json`；联网搜索配置变量（`WEBSEARCH_PROVIDER` / `TAVILY_API_KEY`）位于 `campus_rag/.env`（与嵌入/重排序同处），环境变量已存在时不覆盖。
`ustc.edu.cn` 与 `icourse.club` 域名允许本地代理的 Fake-IP DNS 映射（见 `TRUSTED_PROXY_HOST_SUFFIXES`）。

`tools/ustc_crawler.py` 提供通知栏目采集辅助函数，供 `scripts/sync_ustc_columns.py` 使用，不注册为 Agent 工具。要点：

- 支持的栏目文章链接模式：主站 `/info/<栏目>/<文章>.htm`、研究生院 `/article/<文章>`、教务处 `<栏目>/<文章>.html`、网络信息中心等 PageWeb 站点 `/<年>/<月日>/c<栏目>a<文章>/page.htm`。
- 分页：从页脚 `1/N` 页码元素解析总页数（正则限定"数字/数字必须是某元素的完整文本"，避免把模板资源路径里的数字误读成上万页）。
- 限流：教务处等站点对短时高频抓取返回 403，列表页与文章页均做退避重试（3 次，1.5~2s 递增），文章请求固定 0.3s 间隔、并发降为 2。
- 落盘格式与手动种子文件完全一致：文件名 `{通知ID}_{标题}.txt`（通知 ID 取 URL 文章号；哈希兜底时加 `x` 前缀，防止被误当通知 ID），文档头 `来源：<URL>` / `标题：<标题>` / 空行 / 正文。内容与上次一致即跳过（增量）；标题或正文变化时按新文件名重写。
- 语料不入库：`.gitignore` 对 `campus_rag/data/` 按白名单只放行 7 个手写种子文件，全部爬取语料可随时用脚本重新生成。

## 约定

- 工具失败必须返回可读错误文本给 Agent（而非抛异常中断对话），并记录日志。
- 抓取的超长页面必须截断，防止撞穿 LLM context window。
- 新增工具时同步更新 `main.py` 的 `TOOL_METADATA`；旧用户的工具偏好字典中未出现的工具视为"未表态"，默认启用。
