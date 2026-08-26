# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

本地单用户客户端：无登录、无用户系统，所有数据（对话历史、个人知识库、向量索引）保存在本机。

## 功能特性

- **多轮对话** — SSE 流式输出 + LangGraph 检查点持久化，支持 Markdown 渲染和“停止生成”打断
- **话题管理** — 多话题隔离，每个话题独立的对话历史，自动生成标题
- **RAG 检索** — 向量检索 + BM25 关键词检索 + 重排序，精准匹配校园通知和个人数据
- **个人知识库** — 私有数据的增删改查，支持按来源聚合展示
- **公共通知同步** — Sync Server 架构，支持增量/全量同步，客户端自动拉取最新通知
- **多跳推理** — Agent 面对复杂问题自动进行多轮检索：先初次检索，从结果中提取关键线索发起二次检索，反复直到信息完整，综合所有结果回答
- **联网搜索** — Agent 内置联网搜索（Tavily / DuckDuckGo）与网页抓取工具，弥补本地知识库时效性缺口，回答自动附来源链接
- **可溯源** — 检索结果与回答均携带「来源文件名 + 源链接」，联网搜索结果附网页链接
- **设置中心** — LLM API Key/Base URL 热更新、模型切换、Agent 工具开关

## 框架介绍

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 18 + Vite 6 + TypeScript + Ant Design + Zustand | SPA，详见 [`frontend/README.md`](frontend/README.md) |
| 后端 | FastAPI + uvicorn（端口 8000） | 路由/服务分层，详见 [`server/README.md`](server/README.md) |
| Agent | LangChain + LangGraph | 工具调用 + checkpoint 持久化（`main.py`） |
| RAG | LlamaIndex + ChromaDB + BM25 + qwen3-reranker | 独立可测核心库，详见 [`campus_rag/README.md`](campus_rag/README.md) |
| LLM | DeepSeek V4（远程 API，OpenAI 兼容） | 配置见 `settings.json`，支持热切换（`model/config.py`） |
| 同步 | 独立 Sync Server（端口 8001） | 公共通知分发，详见 [`sync_server/README.md`](sync_server/README.md) |
| 存储 | SQLite（话题/工具偏好/检查点） + ChromaDB（向量） | 全部本地文件 |

```
用户提问
  → Agent（main.py）决定调用哪些工具
     ├── search_campus_notices / search_notices_raw   → campus_rag 公共通知检索
     ├── search_my_data / search_user_data_raw        → campus_rag 个人数据检索
     ├── web_search / web_fetch / ustc_web_search / ustc_web_fetch → 联网搜索与网页抓取（tools/）
     └── add_personal_data                            → 个人知识库入库
  → SSE 流式回传前端（thinking / tool_use / token / done 事件）
```

## 快速开始

### 1. 环境要求

| 依赖 | 版本 |
|---|---|
| Python | 3.11+（推荐 3.12） |
| Node.js | 18+（推荐 22） |

```bash
# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd frontend && npm install && cd ..
```

### 2. 配置

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

环境变量优先级高于 `settings.json`。对话 Agent 和 RAG 总结共用这组
`LLM_*` 配置；如果同时设置了 `OPENAI_*`，RAG 会优先使用 `OPENAI_*`。

### 3. 启动

```bash
# 后端（端口 8000，API 文档 /api/docs）
python server.py

# Sync Server（可选，端口 8001；不启动则同步页显示离线，不影响其他功能）
cd sync_server && python main.py

# 前端（端口 3000）
cd frontend && npm run dev
```

浏览器访问 `http://localhost:3000`。

## 配置参考

### LLM 配置（`settings.json` 或环境变量）

| 变量 | settings.json | 说明 | 默认值 |
|---|---|---|---|
| `LLM_API_KEY` | `env.api_key` | API Key | **必填** |
| `LLM_BASE_URL` | `env.base_url` | API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | `env.model` | 模型名 | `deepseek-v4-flash` |
| `LLM_TIMEOUT_SECONDS` | — | RAG 总结请求超时（5–120 秒） | `45` |

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
│   │   ├── chat.py            #     SSE 流式对话
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
├── campus_rag/                # RAG 检索系统（详见下方模块说明）
│   ├── __init__.py            #   包入口，导出公开接口
│   ├── config.py              #   LlamaIndex 全局设置
│   ├── llm_factory.py         #   LLM / Embedding 工厂（ollama ↔ openai）
│   ├── data_loader.py         #   文档加载和 SentenceSplitter 切分
│   ├── index_manager.py       #   ChromaDB 索引管理（公共 + 个人隔离）
│   ├── keyword_retriever.py   #   BM25 关键词检索（jieba 分词）
│   ├── query.py               #   检索接口（向量检索 / LLM 总结 / 入库）
│   ├── query_engine.py        #   RAG 管线（向量检索 + 重排序 + LLM 生成）
│   ├── data/                  #   校园通知 .txt 源数据
│   └── .env.example           #   嵌入配置模板
├── tools/                     # Agent 工具
│   ├── search.py              #   联网搜索与网页抓取（Tavily 主 + DuckDuckGo 兜底）
│   └── ustc_crawler.py        #   通知栏目采集辅助（供 scripts/ 使用）
├── frontend/                  # React 18 前端
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.tsx        #   SSE 流式对话 + Markdown 渲染
│       │   ├── PersonalDataPage.tsx #   个人知识库管理
│       │   ├── SchedulePage.tsx    #   结构化课表导入与离线查看
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
├── tests/                     # 单元测试（`pytest tests/ -v`）
├── scripts/                   # 网页源同步与通知栏目采集（详见 campus_rag/README.md）
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
| POST | `/api/chat/stream` | SSE 流式对话（`{"content":"...","topic_id":"..."}`）；客户端断开即可停止当前生成 |
| GET | `/api/schedule` | 获取本地课表 |
| POST | `/api/schedule/import` | 导入结构化课表（仅允许本地来源） |

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

## 已知注意事项

- **首次对话较慢**：Agent 和 RAG 索引采用懒加载，首次调用时需要初始化（约 5-10 秒）
- **联网搜索超时**：`web_search`/`ustc_web_search` 的连接超时为 5 秒、读取超时为 15 秒；网页正文抓取读取超时为 20 秒，失败会返回明确错误，不会无限等待
- **嵌入模型**：本地 Ollama 的 `nomic-embed-text` 首次加载需几十秒；切换为云端嵌入可避免此问题
- **数据文件格式**：`campus_rag/data/` 下的通知文件必须以 `.txt` 结尾，否则会被跳过
- **文档分块**：每篇通知会被 `SentenceSplitter` 切分为多个 1024 字符的块，管理面板按文件名聚合显示
- **Windows 代理**：如果系统配置了 HTTP 代理，httpx 可能误用导致 Ollama 连接 502，`llm_factory.py` 已内置清除逻辑
- **ChromaDB 持久化**：向量数据存储在项目根目录的 `chroma_db/`，删除后重启服务会自动从 `data/` 重新索引
- **Sync Server**：公共通知同步需要额外启动 Sync Server（端口 8001），未启动时同步功能显示离线，不影响其他功能
- **工具偏好**：每个话题可独立启/禁用 Agent 工具，偏好通过设置面板管理
- **重排序降级**：重排序走 `campus_rag/.env` 配置的 `RERANK_*` API（默认 USTC 网关 qwen3-reranker），未配置或端点不可用时自动降级为按原始向量分数排序，不阻断检索
- **DeepSeek `/beta` 端点**：DeepSeek V4 系列模型（`deepseek-v4-flash` / `deepseek-v4-pro`）需通过 `/beta` 路径访问。`llm_factory.py` 会在检测到 `api.deepseek.com` 且 `base_url` 未含 `/beta` 时自动补齐后缀，`settings.json` 中写 `https://api.deepseek.com` 即可，无需手动加 `/beta`

## 未来规划

### 增加数据覆盖的广度和深度

* **时效性**：使用爬虫爬取相关网站和系统（教务处公告、研究生院通知、课程表、考试成绩、就业信息、社团活动、校车时刻、校历、政策文件等）保证时效性
* **数据结构化**：课表、成绩等是结构化信息，现有 txt 格式不能很好存储
* **数据多模态**：图片支持较难，pdf、word 等格式应转化为 md 或 txt

### 推理能力强化

* **多跳推理** — ✅ 已实现。Agent system prompt 内嵌多跳推理指南，自动多轮检索并综合回答
* **个性化**：建立个人档案，检索时根据个人特征加权，如网安专业对网安相关通知更重视
* **可溯源** — ✅ 已实现。入库时按文件名通知 ID 提取源网址存入元数据，检索结果与回答均携带来源链接

### 工程化

* 一键安装运行（降低启动步骤复杂度）
* 系统指标（召回率、命中率）评测体系
* 安全性强化

### 工具扩展

- [x] **联网搜索工具** — 使用 DuckDuckGo 查找公开网页，并通过独立 `web_fetch` 工具提取正文；支持配置化网页增量更新和公共索引重建
- [ ] **知识图谱工具** — 基于 Neo4j 或 NetworkX 构建课程依赖、教师关系等结构化知识
- [ ] **邮件/通知推送工具** — Agent 代用户订阅关键词，匹配新通知时推送提醒
- [ ] **日程解析工具** — 从通知中提取时间、地点、事件，自动生成日历事件
- [ ] **图片/多模态支持** — 结合多模态 LLM 解析通知中的海报图片
