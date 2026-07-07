# 前端功能测试报告

测试日期：2026-07-07  
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
| 1 | 健康检查 GET /api/health | ✅ PASS | 返回 agent_ready: false（Agent 懒加载，首次对话时初始化） |
| 2 | 用户登录 POST /api/auth/login | ✅ PASS | 返回 JWT token，含 user_id/username/is_admin |
| 3 | 用户注册 POST /api/auth/register | ✅ PASS | 用户名 >= 2 字符，重名检测正常 |
| 4 | 文件列表 GET /api/files/list | ✅ PASS | 空 workspace 返回 {"files":[]} |
| 5 | 文件读取 GET /api/files/read | ✅ PASS | |
| 6 | 文件写入 POST /api/files/write | ✅ PASS | |
| 7 | 文件删除 DELETE /api/files/delete | ✅ PASS | |
| 8 | 文件上传 POST /api/files/upload | ✅ PASS | 仅支持 UTF-8 文本文件 |
| 9 | 搜索通知 GET /api/search/notices | ✅ PASS | RAG 检索正常，返回带来源的格式化结果 |
| 10 | 搜索个人数据 GET /api/search/my-data | ✅ PASS | |
| 11 | WebSocket 对话 /ws/chat | ✅ PASS | Agent 调用正常，回复内容正确 |
| 12 | Vite 代理 /api/* → localhost:8000 | ✅ PASS | 所有 API 路由代理正常 |
| 13 | Vite 代理 /ws → ws://localhost:8000 | ✅ PASS | WebSocket 代理正常 |
| 14 | 前端 TypeScript 编译 | ✅ PASS | tsc --noEmit 无错误 |
| 15 | 前端页面加载 /login, /chat, /files | ✅ PASS | 各路由正常渲染 |

## 发现并修复的问题

### 1. FilesPage.tsx — 未使用的 `goUp` 函数导致 TS 编译错误

- **位置**: `frontend/src/pages/FilesPage.tsx:53`
- **问题**: `goUp()` 函数声明但从未使用，面包屑导航已直接调用 `setCurrentPath`
- **修复**: 删除该未使用函数
- **影响**: tsc --noEmit 报错，但不影响运行时

### 2. useChat.ts — 死代码

- **位置**: `frontend/src/hooks/useChat.ts`
- **问题**: 用 `useMemo` 创建 WebSocket，无任何组件引用；且每次 wsUrl 变化都会新建连接但不断开旧连接
- **修复**: 删除该文件及空 hooks 目录
- **影响**: 清理后不影响任何功能（ChatPage 有独立实现）

## 已知问题（未实现/设计限制，未修复）

### 1. Chat WebSocket 不支持真正的流式输出

后端 `server.py:170-174` 通过 `asyncio.to_thread` 同步调用 Agent，等待全部生成完毕后才发送单条 `token` 消息。前端 `ChatPage.tsx` 已为流式令牌做好了累积准备，消息从空直接跳到完整内容。如需真流式，需改为 `agent_instance.astream_events()`。

### 2. Admin 端点缺乏鉴权

`server.py:264` 使用 `authenticate(user, "")`（空密码）做 admin 验证，始终返回 False。Admin 页面/功能本身也尚未实现。

### 3. 未使用的服务端 import

`server.py:26` 从 main 导入的 `search_campus_notices, search_my_data` 未被使用（仅使用了 `build_agent`）。不影响运行。

## API 端到端测试

所有 API 均通过 Vite 前端代理 (localhost:3000 → localhost:8000) 测试通过：

```
GET  /api/health              → 200 {"status":"ok"}
POST /api/auth/login           → 200 {"token":"...","user_id":"admin",...}
POST /api/auth/register        → 200 {"token":"...","user_id":"test",...}
GET  /api/files/list?path=     → 200 {"files":[]}
GET  /api/files/read?path=x    → 文件内容
POST /api/files/write          → 200 {"message":"..."}
DELETE /api/files/delete?path=x → 200 {"message":"..."}
POST /api/files/upload         → 200 {"message":"...","path":"..."}
GET  /api/search/notices?q=讲座 → 200 检索结果
GET  /api/search/my-data?q=xxx → 200 检索结果
WS   /ws/chat?token=xxx        → 正常收发 JSON 消息
```

## 前端页面渲染测试

- `/login` — 登录/注册双 Tab 表单正常渲染，Ant Design 组件正常
- `/chat` — WebSocket 连接成功，消息收发正常，气泡 UI 正常
- `/files` — 文件表格、面包屑、上传按钮正常渲染
