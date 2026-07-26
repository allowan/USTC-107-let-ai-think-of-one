# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

## 功能特性

- **多轮对话** — SSE/WebSocket 流式输出 + LangGraph 检查点持久化，支持 Markdown 渲染
- **话题管理** — 多话题隔离，每个话题独立的对话历史，自动生成标题
- **RAG 检索** — 混合检索（向量 + BM25）+ 重排序，精准匹配校园通知和个人数据
- **个人知识库** — 用户私有数据的增删改查，支持按来源聚合展示
- **公共通知同步** — Sync Server 架构，支持增量/全量同步，客户端自动拉取最新通知
- **设置中心** — LLM API Key/Base URL 热更新、模型切换、Agent 工具开关

## 快速开始

### 1. 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 推荐 3.12 |
| Node.js | 18+ | 推荐 22 |
| Ollama | latest | 用于本地嵌入模型 |
| conda | 可选 | 项目提供 `107` 环境 |

**首次克隆后：**

```bash
# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd frontend && npm install
```

### 2. 配置 LLM API Key

**方式一：settings.json**

```bash
cp settings.example.json settings.json
```

编辑 `settings.json`，填入 DeepSeek API Key：

```json
{
    "env": {
        "api_key": "sk-your-deepseek-key",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash"
    }
}
```

**方式二：环境变量**

```bash
export LLM_API_KEY="sk-your-deepseek-key"
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-v4-flash"
```

环境变量优先级高于 `settings.json`。

### 3. 配置嵌入模型

```bash
cp campus_rag/.env.example campus_rag/.env
```

`campus_rag/.env` 默认使用本地 Ollama：

```env
EMBED_PROVIDER=ollama
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_HOST=http://127.0.0.1:11434
```

也可切换为 OpenAI 兼容的云端嵌入：

```env
EMBED_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-your-key
OPENAI_EMBED_MODEL=deepseek-embedding-v1
```

### 4. 启动 Ollama

```bash
# 首次拉取嵌入模型（约 274 MB）
ollama pull nomic-embed-text

# 启动 Ollama 服务（默认监听 127.0.0.1:11434）
ollama serve
```

### 5. 启动后端

```bash
python server.py
```

服务运行在 `http://localhost:8000`，API 文档在 `http://localhost:8000/api/docs`。

> **Windows 注意**：如果使用 conda，确保先 `conda activate 107`。如果遇到 Ollama 嵌入返回 502 错误，说明系统代理干扰了 httpx，`llm_factory.py` 已内置清除代理环境变量的逻辑，重启服务即可。

### 6. 启动 Sync Server（可选）

Sync Server 是公共通知同步服务端，独立运行在端口 8001：

```bash
cd sync_server && python main.py
```

如果不启动 Sync Server，主服务的同步功能会显示服务离线，不影响其他功能。

### 7. 启动前端

```bash
cd frontend
npm run dev
```

访问 `http://localhost:3000`。

## 配置参考

### LLM 配置（`settings.json` 或环境变量）

| 变量 | settings.json | 说明 | 默认值 |
|---|---|---|---|
| `LLM_API_KEY` | `env.api_key` | API Key | **必填** |
| `LLM_BASE_URL` | `env.base_url` | API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | `env.model` | 模型名 | `deepseek-v4-flash` |

### 嵌入模型配置（`campus_rag/.env`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `EMBED_PROVIDER` | 嵌入来源：`ollama` 或 `openai` | `ollama` |
| `OLLAMA_EMBED_MODEL` | Ollama 嵌入模型名 | `nomic-embed-text` |
| `OLLAMA_HOST` | Ollama 服务地址 | `http://127.0.0.1:11434` |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | — |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key | — |
| `OPENAI_EMBED_MODEL` | 云端嵌入模型名 | `text-embedding-3-small` |

### 其他配置

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WORKSPACE_ROOT` | 文件工作区路径 | 项目根目录 `workspace/` |

## 项目结构

```
USTC-107-let-ai-think-of-one/
├── server.py                  # 后端入口（uvicorn 启动）
├── server/                    # FastAPI 应用包
│   ├── __init__.py            #   应用工厂、路由注册、静态文件挂载
│   ├── main.py                #   开发/调试入口（python server/main.py）
│   ├── lifespan.py            #   启动/关闭生命周期（ChatService 初始化）
│   ├── deps.py                #   依赖注入（本地用户标识）
│   ├── routes/                #   路由模块
│   │   ├── chat.py            #     SSE / WebSocket 流式对话
│   │   ├── topics.py          #     话题 CRUD、历史、自动标题
│   │   ├── search.py          #     公共通知 / 个人数据检索
│   │   ├── personal_data.py   #     个人知识库 CRUD
│   │   ├── settings.py        #     LLM 配置、模型切换、工具开关
│   │   ├── sync.py            #     公共通知同步管理
│   │   └── health.py          #     健康检查
│   └── services/              #   业务逻辑层
│       ├── auth_service.py    #     话题管理服务
│       ├── chat_service.py    #     Agent 管理、对话执行
│       ├── rag_service.py     #     RAG 检索、数据入库
│       └── sync_service.py    #     客户端同步逻辑
├── sync_server/               # 公共通知同步服务端（独立进程，端口 8001）
│   ├── main.py                #   FastAPI 应用入口
│   ├── database.py            #   SQLite 数据库 + 版本管理
│   ├── deps.py                #   Admin 认证依赖
│   ├── routes/
│   │   ├── admin.py           #     通知 CRUD、统计（需 admin token）
│   │   └── sync.py            #     版本查询、增量/全量同步（公开）
│   ├── services/
│   │   ├── admin_service.py   #     通知管理逻辑
│   │   └── sync_service.py    #     同步数据逻辑
│   ├── static/admin.html      #   Sync Server 管理后台页面
│   └── data/                  #   同步源数据（.txt 通知文件）
├── main.py                    # LangChain Agent 定义、工具注册、系统提示
├── model/
│   └── config.py              # LLM 初始化（支持 settings.json 热切换）
├── campus_rag/                # RAG 检索系统
│   ├── data/                  #   校园通知 .txt 源数据
│   ├── config.py              #   LlamaIndex 全局设置
│   ├── llm_factory.py         #   LLM / Embedding 工厂
│   ├── data_loader.py         #   文档加载和 SentenceSplitter 切分
│   ├── index_manager.py       #   ChromaDB 索引管理（公共 + 用户隔离）
│   ├── keyword_retriever.py   #   BM25 关键词检索（jieba 分词）
│   ├── query.py               #   检索接口（Agent 工具用）
│   ├── query_engine.py        #   RAG 管线（向量/混合检索 + 重排序 + LLM）
│   ├── ingest.py              #   运行时文档注入
│   ├── auth.py                #   话题 CRUD、工具偏好
│   ├── .env.example           #   嵌入配置模板
│   └── README.md              #   RAG 模块文档
├── tools/                     # Agent 工具
│   └── search.py              #   网页抓取工具
├── frontend/                  # React 18 前端
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.tsx        #   SSE 流式对话 + Markdown 渲染
│       │   ├── PersonalDataPage.tsx #   个人知识库管理
│       │   └── SyncPage.tsx        #   公共通知同步
│       ├── components/
│       │   └── Layout/
│       │       ├── AppLayout.tsx    #   侧边栏（菜单 + 话题列表）+ 顶栏
│       │       └── SettingsModal.tsx #   LLM/工具 设置弹窗
│       ├── services/
│       │   └── api.ts              #   API 调用封装
│       ├── stores/
│       │   ├── userStore.ts         #   用户状态
│       │   └── topicStore.ts        #   话题状态
│       └── types/
│           └── index.ts            #   TypeScript 类型定义
├── tests/                     # 单元测试
├── data/                      # 运行时数据（checkpoint DB，gitignore）
├── workspace/                 # 用户文件存储（gitignore）
├── chroma_db/                 # ChromaDB 向量数据库（gitignore）
└── settings.example.json      # LLM 配置模板

```

## API 总览

### 主服务（端口 8000）

#### 通用

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |

#### 话题

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/topics` | 话题列表 |
| POST | `/api/topics` | 创建话题 |
| DELETE | `/api/topics/{id}` | 删除话题及对话记录 |
| PUT | `/api/topics/{id}` | 重命名话题 |
| POST | `/api/topics/{id}/summarize` | 自动生成话题标题 |
| GET | `/api/topics/{id}/history` | 获取话题对话历史 |

#### 对话

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/chat/stream` | SSE 流式对话（`{"content":"...","topic_id":"..."}`） |
| WS | `/ws/chat` | WebSocket 流式对话 |

#### 个人知识库

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/personal-data` | 列出个人数据（按来源聚合） |
| POST | `/api/personal-data` | 添加个人数据 |
| PUT | `/api/personal-data/{source}` | 编辑个人数据 |
| DELETE | `/api/personal-data/{source}` | 删除个人数据 |

#### 搜索

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/search/notices?q=` | 搜索公共通知 |
| GET | `/api/search/my-data?q=` | 搜索个人数据 |

#### 设置

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/settings` | 获取 LLM 配置 |
| PUT | `/api/settings` | 更新 API Key / Base URL |
| POST | `/api/settings/model` | 切换模型 |
| GET | `/api/settings/tools` | 获取工具开关状态 |
| PUT | `/api/settings/tools` | 更新工具开关 |

#### 同步

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/sync/status` | 查看本地/远程版本差异 |
| POST | `/api/sync/now` | 立即触发同步 |

### Sync Server（端口 8001）

#### 客户端同步（公开）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/sync/version` | 获取当前版本号 |
| GET | `/api/sync/changes?since=` | 增量同步变更 |
| GET | `/api/sync/full` | 全量同步所有文档 |

#### 管理后台（需 admin token）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/notices` | 通知列表 |
| POST | `/api/admin/notices` | 添加通知 |
| GET | `/api/admin/notices/{source}/content` | 获取通知原文 |
| PUT | `/api/admin/notices/{source}` | 编辑通知 |
| DELETE | `/api/admin/notices/{source}` | 删除通知 |
| GET | `/api/admin/stats` | 系统统计 |
| GET | `/admin` | 管理后台 HTML 页面 |

## 测试

### 后端测试

```bash
# 运行单元测试
pytest tests/ -v

# 手动测试 API
# 1. 健康检查
curl http://localhost:8000/api/health

# 2. 搜索
curl "http://localhost:8000/api/search/notices?q=讲座"

# 3. 个人知识库
curl "http://localhost:8000/api/personal-data"

# 4. 同步状态
curl "http://localhost:8000/api/sync/status"
```

### 前端测试

```bash
cd frontend
npx tsc --noEmit   # TypeScript 类型检查
npm run build       # 生产构建
```

### 端到端测试流程

1. 启动 Ollama：`ollama serve`
2. 启动后端：`python server.py`
3. （可选）启动 Sync Server：`cd sync_server && python main.py`
4. 启动前端：`cd frontend && npm run dev`
5. 浏览器打开 `http://localhost:3000`
6. 创建话题：侧边栏点击 + 按钮
7. 测试对话：发送"有什么暑期学校的活动？"
8. 测试个人知识库：侧边栏"个人数据" → 添加/编辑/删除
9. 测试同步：侧边栏"同步" → 查看状态 → 触发同步
10. 测试设置：顶栏齿轮图标 → 切换模型 / 管理工具开关

## 已知注意事项

- **首次对话较慢**：Agent 和 RAG 索引采用懒加载，首次调用时需要初始化（约 5-10 秒）
- **嵌入模型**：本地 Ollama 的 `nomic-embed-text` 首次加载需几十秒；切换为云端嵌入可避免此问题
- **数据文件格式**：`campus_rag/data/` 下的通知文件必须以 `.txt` 结尾，否则会被跳过
- **文档分块**：每篇通知会被 `SentenceSplitter` 切分为多个 1024 字符的块，管理面板按文件名聚合显示
- **Windows 代理**：如果系统配置了 HTTP 代理，httpx 可能误用导致 Ollama 连接 502，`llm_factory.py` 已内置清除逻辑
- **ChromaDB 持久化**：向量数据存储在项目根目录的 `chroma_db/`，删除后重启服务会自动从 `data/` 重新索引
- **Sync Server**：公共通知同步需要额外启动 Sync Server（端口 8001），未启动时同步功能显示离线，不影响其他功能
- **工具偏好**：每个话题可独立启/禁用 Agent 工具，偏好通过设置面板管理

## 未来规划

### 数据库多文件格式支持

当前 `campus_rag/data/` 仅支持 `.txt` 纯文本文件。计划扩展支持以下格式：

- [ ] **PDF** — 校园通知常以 PDF 发布，使用 `PyMuPDF` 或 `pdfplumber` 解析
- [ ] **Word (.docx)** — 使用 `python-docx` 解析
- [ ] **Markdown (.md)** — 保留格式结构，按标题层级智能分块
- [ ] **HTML** — 爬取网页后可直接入库，使用 `BeautifulSoup` 清洗
- [ ] **Excel (.xlsx)** — 表格类数据（如课表、考试安排），按行/sheet 分块

实现思路：在 `data_loader.py` 中增加 `FormatRouter`，根据文件后缀分发到对应的解析器，统一输出 `Document` 列表进入现有 RAG 管线。

### 数据库自动爬取更新

- [ ] **定时爬取** — 用 APScheduler 或后台 asyncio 任务定时抓取校园网站通知（教务处、研究生院、各学院官网）
- [ ] **增量更新** — 记录已爬取 URL 和内容哈希，仅对新通知或变更内容触发重新索引
- [ ] **爬取结果自动入库** — 抓取 → 清洗 → 分块 → 写入 ChromaDB 全自动
- [ ] **管理面板手动触发** — 在 Sync Server 管理后台增加「立即爬取」按钮

### 工具扩展

- [ ] **联网搜索工具** — 集成 Tavily / DuckDuckGo Search API 作为 Agent 工具，弥补本地知识库的时效性缺口（参考 `tools/search.py` 现有网页抓取逻辑，可复用）
- [ ] **知识图谱工具** — 基于 Neo4j 或 NetworkX 构建课程依赖、教师关系等结构化知识
- [ ] **邮件/通知推送工具** — Agent 可代用户订阅关键词，匹配到新通知时推送提醒
- [ ] **日程解析工具** — 从通知中提取时间、地点、事件，自动生成日历事件
- [ ] **图片/多模态支持** — 结合多模态 LLM 解析通知中的海报图片

### 工程化

- [ ] Docker 部署支持
- [ ] CI/CD 流水线（GitHub Actions）
