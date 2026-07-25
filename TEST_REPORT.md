# 前端功能测试报告

测试日期：2026-07-07（更新于 2026-07-25）
测试环境：localhost:3000 (前端) + localhost:8000 (后端)

## 测试环境配置

| 项目 | 值 |
|---|---|
| Python | 3.14.6 (conda env: 107) |
| Node.js | v22.23.1 |
| npm | 10.9.8 |
| 后端框架 | FastAPI + uvicorn |
| 前端框架 | React 18 + Vite 6 + TypeScript 5.6 |
| LLM | DeepSeek V4 Flash |
| Embedding | Ollama nomic-embed-text |
| Vector DB | ChromaDB |

## 测试结果汇总

| # | 功能 | 状态 | 备注 |
|---|---|---|---|
| 1 | 健康检查 GET /api/health | PASS | 返回 agent_ready 状态 |
| 2 | 用户登录 POST /api/auth/login | PASS | 返回 JWT token，含 user_id/username/is_admin |
| 3 | 用户注册 POST /api/auth/register | PASS | 用户名 >= 2 字符，重名检测正常 |
| 4 | 话题管理 CRUD | PASS | 创建/重命名/删除/自动标题 |
| 5 | 话题对话历史 GET /api/topics/{id}/history | PASS | 按 thread_id 隔离 |
| 6 | SSE 流式对话 POST /api/chat/stream | PASS | Agent 调用正常，流式输出正常 |
| 7 | WebSocket 对话 /ws/chat | PASS | Agent 调用正常，回复内容正确 |
| 8 | 搜索通知 GET /api/search/notices | PASS | RAG 检索正常，返回带来源的格式化结果 |
| 9 | 搜索个人数据 GET /api/search/my-data | PASS | 用户数据隔离正确 |
| 10 | 个人知识库 CRUD /api/personal-data | PASS | 增删改查均正常，按来源聚合 |
| 11 | 设置 GET/PUT /api/settings | PASS | LLM 配置读写正常 |
| 12 | 模型切换 POST /api/settings/model | PASS | 热切换生效 |
| 13 | 工具开关 GET/PUT /api/settings/tools | PASS | 用户级工具偏好持久化 |
| 14 | 同步状态 GET /api/sync/status | PASS | 离线/在线状态正确返回 |
| 15 | Vite 代理 /api/* → localhost:8000 | PASS | 所有 API 路由代理正常 |
| 16 | Vite 代理 /ws → ws://localhost:8000 | PASS | WebSocket 代理正常 |
| 17 | 前端 TypeScript 编译 | PASS | tsc --noEmit 无错误 |
| 18 | 前端页面加载 /chat, /personal-data, /sync | PASS | 各路由正常渲染 |

## 架构变更记录（2026-07-25 更新）

自初始测试以来，项目架构有以下重要变更：

- **后端拆分**：`server.py` 单体文件拆分为 `server/` 包（routes/ + services/ 分层）
- **Sync Server**：新增独立的 `sync_server/` 服务（端口 8001），负责公共通知的版本化同步
- **前端重构**：页面从 LoginPage / ChatPage / FilesPage / AdminPage 调整为 ChatPage / PersonalDataPage / SyncPage，登录集成在 AppLayout 中，设置功能独立为 SettingsModal
- **新功能**：话题管理、个人知识库、LLM 设置热更新、工具开关、公共通知同步

## 发现并修复的问题

### 1. FilesPage.tsx — 未使用的 `goUp` 函数导致 TS 编译错误

- **位置**: `frontend/src/pages/FilesPage.tsx:53`（已移除）
- **问题**: `goUp()` 函数声明但从未使用，面包屑导航已直接调用 `setCurrentPath`
- **修复**: 删除该未使用函数
- **影响**: tsc --noEmit 报错，但不影响运行时

### 2. useChat.ts — 死代码

- **位置**: `frontend/src/hooks/useChat.ts`（已移除）
- **问题**: 用 `useMemo` 创建 WebSocket，无任何组件引用；且每次 wsUrl 变化都会新建连接但不断开旧连接
- **修复**: 删除该文件及空 hooks 目录
- **影响**: 清理后不影响任何功能（ChatPage 有独立实现）

## 已知问题

### 1. Chat WebSocket 不支持真正的流式输出

后端通过 `asyncio.to_thread` 同步调用 Agent，等待全部生成完毕后才发送单条消息。前端已为流式令牌做好了累积准备，消息从空直接跳到完整内容。如需真流式，需改为 `agent_instance.astream_events()`。

### 2. Sync Server 需独立启动

Sync Server 是独立进程（端口 8001），不随主服务自动启动。未启动时客户端同步功能显示离线状态，需手动启动。

## API 端到端测试

所有 API 均通过 Vite 前端代理 (localhost:3000 → localhost:8000) 测试通过：

```
GET  /api/health              → 200 {"status":"ok"}
POST /api/auth/login           → 200 {"token":"...","user_id":"admin",...}
POST /api/auth/register        → 200 {"token":"...","user_id":"test",...}
GET  /api/topics               → 200 []
POST /api/topics               → 200 {"id":"...","title":"..."}
POST /api/chat/stream          → 200 text/event-stream
WS   /ws/chat?token=xxx        → 正常收发 JSON 消息
GET  /api/search/notices?q=讲座 → 200 检索结果
GET  /api/search/my-data?q=xxx → 200 检索结果
GET  /api/personal-data        → 200 {"items":[...]}
POST /api/personal-data        → 200 {"message":"数据已添加"}
GET  /api/settings             → 200 LLM 配置 JSON
GET  /api/settings/tools       → 200 {"tools":[...]}
GET  /api/sync/status          → 200 {"local_version":...,"remote_version":...}
```

## 前端页面渲染测试

- `/chat` — WebSocket 连接成功，消息收发正常，气泡 UI 正常，话题切换正常
- `/personal-data` — 数据列表、添加/编辑/删除弹窗正常
- `/sync` — 版本状态展示正常，同步按钮正常
