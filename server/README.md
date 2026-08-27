# server — FastAPI 后端

主服务（端口 8000）：路由/服务分层架构，SSE 流式对话，本地单用户（无 JWT）。

## 架构分层

| 层 | 位置 | 职责 |
|---|---|---|
| 入口 | `server.py`（根目录）/ `server/main.py` | uvicorn 启动 shim，缺依赖时给出激活虚拟环境的指引 |
| 应用工厂 | `server/__init__.py` | `create_app()`：路由注册、CORS、前端静态文件挂载（`frontend/dist` 存在时） |
| 生命周期 | `server/lifespan.py` | 启动时初始化 ChatService（未配 LLM Key 时降级不阻断启动），关闭时收尾 agent 连接 |
| 依赖注入 | `server/deps.py` | `get_user()` 恒返回 `local_user`（本地单用户，无认证） |
| 路由 | `server/routes/` | 参数校验、调用 service、返回响应——禁止写业务逻辑 |
| 服务 | `server/services/` | 业务编排，委托 `campus_rag` / `main.py` |

### services

| 服务 | 职责 |
|---|---|
| `chat_service.py` | Agent 生命周期（默认/按用户缓存）、SSE 事件流、checkpoint 删除与损坏重试；未配 LLM Key 时保持懒加载，课表/个人数据 API 不受影响 |
| `auth_service.py` | 话题 CRUD（委托 `campus_rag.auth`） |
| `rag_service.py` | 检索与个人数据管理（委托 `campus_rag.query`） |
| `schedule_service.py` | 本地结构化课表存储（SQLite `schedule.db`，按用户+学期隔离，连接用完即关） |
| `ustc_schedule.py` | 解析用户提供的教务课表 HTML/结构化 JSON（不接触账号密码与 Cookie） |
| `sync_service.py` | 从 Sync Server 拉取公共通知（增量优先、全量兜底），版本号持久化于 `data/sync_state.json` |

## API 总览（端口 8000）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（agent / LLM / ChromaDB，全部在线程池探测不阻塞事件循环；LLM 未配置时仅降级不报错） |
| GET | `/api/topics` | 话题列表 |
| POST | `/api/topics` | 创建话题 |
| PUT | `/api/topics/{id}` | 重命名话题 |
| DELETE | `/api/topics/{id}` | 删除话题及对话记录（含 checkpoint） |
| POST | `/api/topics/{id}/summarize` | 自动生成话题标题 |
| GET | `/api/topics/{id}/history` | 获取话题对话历史 |
| POST | `/api/chat/stream` | SSE 流式对话（`{"content","topic_id"}`），事件：`thinking` / `tool_use` / `token` / `error` / `done` |
| GET | `/api/personal-data` | 列出个人数据（按来源聚合，按 `chunk_index` 还原顺序） |
| POST | `/api/personal-data` | 添加个人数据 |
| POST | `/api/personal-data/import-schedule` | 将已导入的本地课表写入个人知识库供检索（仅限本地来源） |
| PUT | `/api/personal-data/{source}` | 编辑个人数据 |
| DELETE | `/api/personal-data/{source}` | 删除个人数据 |
| GET | `/api/schedule` | 获取本地课表（可按学期筛选） |
| POST | `/api/schedule/import` | 用结构化数据替换指定学期课表（仅限本地来源） |
| POST | `/api/schedule/import-ustc` | 解析用户粘贴/导出的教务课表 HTML/JSON 并替换该学期（仅限本地来源） |
| GET | `/api/search/notices?q=` | 搜索公共通知（纯检索，不经 LLM） |
| GET | `/api/search/my-data?q=` | 搜索个人数据（纯检索，不经 LLM） |
| GET | `/api/settings` | 获取 LLM 配置 |
| PUT | `/api/settings` | 更新 API Key / Base URL（忽略空值，原子写回） |
| POST | `/api/settings/model` | 按分组切换模型 |
| GET | `/api/settings/tools` | 获取 Agent 工具开关状态 |
| PUT | `/api/settings/tools` | 更新工具开关 |
| GET | `/api/sync/status` | 本地/远程版本差异 |
| POST | `/api/sync/now` | 立即触发同步 |

交互式文档：`http://localhost:8000/api/docs`。

## 关键约定

- **thread_id 契约**：`user-{username}-topic-{topic_id}`，话题删除 / 历史加载 / 对话写入三处共用，`tests/test_server_api.py::TestThreadIdContract` 守护。
- **路径参数禁止二次解码**：starlette 路由层已自动解码一次，路由内再 `unquote()` 会损坏字面含 `%` 的参数。
- **阻塞调用进线程池**：检索/入库含嵌入 API 调用，`async` 路由中一律 `asyncio.to_thread`；同步长任务同理（见 `sync_service.sync`）。
- **SSE 损坏自愈**：检测到 checkpoint 损坏（tool_calls 与 tool messages 不匹配）时自动删除该 thread 并重试一次。
- **设置变更失效链**：更新配置/切换模型 → `clear_agent_cache()`（含默认 agent）；更新工具开关 → 仅失效该用户 agent。
- **课表写入口仅限本地来源**：`/api/schedule/import*` 与 `/api/personal-data/import-schedule` 统一经 `ensure_local_origin` 校验 Origin（无 Origin 或 localhost/127.0.0.1 才放行）。

## 测试

```bash
pytest tests/test_server_api.py -v   # 路由契约/编码往返/状态机，离线可运行（RAG 用 stub）
```
