# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

本地单用户客户端：无登录、无用户系统，所有数据（对话历史、个人知识库、向量索引）保存在本机。

## 功能特性

- **多轮对话** — SSE 流式输出 + LangGraph 检查点持久化，支持 Markdown 渲染（含 GFM 表格）和“停止生成”打断
- **话题管理** — 多话题隔离，每个话题独立的对话历史，自动生成标题
- **今日面板** — 打开即见“我追踪的事件 + 即将截止/进行中与即将开始 + 最近发布”，数据全部来自本地时间索引，不依赖 LLM；事件可一键追踪置顶，临近 3 天高亮
- **RAG 检索** — 向量与 BM25 候选排名融合 + 重排序，检索校园通知和个人数据；Agent 直接基于带来源的片段回答；检索为空时自动用 jieba 关键词缩减重试一次（检索自愈）
- **个人知识库** — 私有数据的增删改查，支持按来源聚合展示；支持上传 TXT/Markdown/CSV/JSON/PDF/DOCX 文件解析为文本后入库
- **最新消息** — 实时抓取五个校站（主站服务通知/教务处/网络信息中心/研究生院/图书馆）首页头条，按发布时间排序，抓取失败自动回退缓存并标注来源状态
- **公共通知同步** — Sync Server 架构，支持增量/全量同步，客户端自动拉取最新通知
- **多跳推理** — Agent 面对复杂问题自动进行多轮检索：先初次检索，从结果中提取关键线索发起二次检索，反复直到信息完整，综合所有结果回答
- **时间感知** — 从通知中确定性抽取截止日/发生时间（展览·施工·停水等 span）/发布日/类别/地点存入时间索引（`events.db`），“最近有什么要截止的报名”“现在有什么展览/哪里在施工”按真实日期排序回答，不遗漏措辞不同但时间临近的通知；进行中事件单独标注
- **联网搜索** — Agent 内置联网搜索（Tavily / DuckDuckGo）与网页抓取工具，弥补本地知识库时效性缺口，回答自动附来源链接
- **评课参考** — 接入评课社区（icourse.club）公开课程评价搜索与正文读取，选课建议时区分官方信息与学生主观评价
- **可溯源** — 检索结果与回答均携带「来源文件名 + 源链接」，联网搜索结果附网页链接
- **设置中心** — LLM API Key/Base URL 热更新、模型切换、Agent 工具开关

## 框架介绍

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 18 + Vite 6 + TypeScript + Ant Design + Zustand | SPA，详见 [`frontend/README.md`](frontend/README.md) |
| 后端 | FastAPI + uvicorn（端口 8000） | 路由/服务分层，详见 [`server/README.md`](server/README.md) |
| Agent | LangChain + LangGraph | 工具调用 + checkpoint 持久化（`main.py`） |
| RAG | LlamaIndex + ChromaDB + BM25 + qwen3-embedding / qwen3-reranker | 独立可测核心库，详见 [`campus_rag/README.md`](campus_rag/README.md) |
| LLM | DeepSeek V4（远程 API，OpenAI 兼容） | 配置见 `settings.json`，支持热切换（`model/config.py`） |
| 同步 | 独立 Sync Server（端口 8001） | 公共通知分发，详见 [`sync_server/README.md`](sync_server/README.md) |
| 存储 | SQLite（话题/工具偏好/检查点） + ChromaDB（向量） | 全部本地文件 |

```
用户提问
  → Agent（main.py）决定调用哪些工具
     ├── search_campus_notices / search_notices_raw   → campus_rag 公共通知检索
     ├── get_upcoming_events(kind=deadline|start)     → 时间索引：即将截止的事件 / 即将开始或进行中的事件（events.db）
     ├── search_my_data / search_user_data_raw        → campus_rag 个人数据检索
     ├── web_search / web_fetch / ustc_web_search / ustc_web_fetch → 联网搜索与网页抓取（tools/）
     ├── course_review_search / course_review_fetch → 评课社区课程评价（tools/）
     ├── get_my_schedule / import_ustc_schedule   → 本地课表读取（默认按日期自动取当前学期）与教务课表导入
     └── add_personal_data                            → 个人知识库入库
  → SSE 流式回传前端（thinking / tool_use / token / done 事件）
```

## 快速开始

### 1. 环境要求

| 依赖 | 版本 |
|---|---|
| Python | 3.11+（推荐 3.12） |
| Node.js | 18+（推荐 22） |

### 2. 安装依赖

```bash
# （推荐）创建并激活 Python 虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell；Linux/macOS 用 source .venv/bin/activate

# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd frontend && npm install && cd ..
```

### 3. 配置 Key

项目最多需要三组 Key，分别填在不同文件（切勿混写）：

| Key | 填写位置 | 用途 | 获取方式 |
|---|---|---|---|
| DeepSeek API Key | 根目录 `settings.json` | 对话 Agent 与 RAG 回答生成 | DeepSeek 开放平台申请 |
| 嵌入/重排序 API Key | `campus_rag/.env` | 向量嵌入与检索重排序（默认 USTC LLM 网关） | 科大 LLM 网关平台申请（需校园网/VPN 访问） |
| Tavily API Key（可选） | `campus_rag/.env` | 联网搜索（不配置则自动回退免 Key 的 DuckDuckGo） | https://tavily.com 注册，免费版 1000 次/月 |

**① LLM 配置**

```bash
copy settings.example.json settings.json   # Linux/macOS 用 cp
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

也可改用环境变量 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，优先级高于 `settings.json`。

**② 嵌入与重排序配置**

```bash
copy campus_rag\.env.example campus_rag\.env   # Linux/macOS 用 cp
```

`.env.example` 已预置 USTC 网关的配置模板，只需把两处 `sk-xxx` 替换为你自己的网关 Key（嵌入与重排序可共用同一个 Key）：

```dotenv
# 嵌入模型（qwen3-embedding）
EMBED_PROVIDER=openai
EMBED_API_KEY=sk-your-ustc-gateway-key
EMBED_BASE_URL=https://api.llm.ustc.edu.cn/v1
EMBED_MODEL=qwen3-embedding

# 重排序模型（qwen3-reranker）
RERANK_PROVIDER=api
RERANK_API_KEY=sk-your-ustc-gateway-key
RERANK_BASE_URL=https://api.llm.ustc.edu.cn/v1
RERANK_MODEL=qwen3-reranker
```

网关不可用时：嵌入可改为本地 Ollama（`EMBED_PROVIDER=ollama`，模板内有回退配置）；重排序不配置会自动降级为按向量分数排序，不阻断使用。

**③ 联网搜索配置（可选）**

在 `campus_rag/.env` 末尾追加：

```dotenv
WEBSEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-your-tavily-key
```

不配置时 `web_search` 自动回退到免 Key 的 DuckDuckGo 实现，其余功能不受影响。

### 4. 启动

开三个终端依次启动：

```bash
# ① 后端（端口 8000，API 文档 http://localhost:8000/api/docs）
python server.py

# ② Sync Server（可选，端口 8001；不启动则同步页显示离线，不影响其他功能）
cd sync_server && python main.py

# ③ 前端（端口 3000）
cd frontend && npm run dev
```

后端服务运行在 `http://localhost:8000`，API 文档在 `http://localhost:8000/api/docs`。
未配置 `LLM_API_KEY` 时，后端仍会启动；聊天功能会显示模型配置错误，但课表导入、课表查询和个人数据功能仍可使用。

> **Windows 注意**：如果使用 conda，确保先 `conda activate 107`。如果遇到 Ollama 嵌入返回 502 错误，说明系统代理干扰了 httpx，`llm_factory.py` 已内置清除代理环境变量的逻辑，重启服务即可。

### 5. 验证

- 浏览器访问 `http://localhost:3000`，新建话题，发送“有什么暑期学校的活动？”
- 后端健康检查：`curl http://localhost:8000/api/health`
- 首次回答较慢（约 5–10 秒）：Agent 与向量索引懒加载初始化，属正常现象

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
| `EMBED_PROVIDER` | 嵌入来源：`openai`（任意 OpenAI 兼容 API）或 `ollama`（本地） | `ollama` |
| `EMBED_API_KEY` | 嵌入服务 API Key（用独立 `EMBED_*`，勿复用 `OPENAI_*`） | — |
| `EMBED_BASE_URL` | 嵌入服务地址 | — |
| `EMBED_MODEL` | 云端嵌入模型名 | `text-embedding-3-small` |
| `OLLAMA_EMBED_MODEL` | Ollama 嵌入模型名（仅 ollama 时生效） | `nomic-embed-text` |
| `OLLAMA_HOST` | Ollama 服务地址（仅 ollama 时生效） | `http://127.0.0.1:11434` |

### 重排序模型配置（`campus_rag/.env`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `RERANK_PROVIDER` | 设为 `api` 启用 API 重排序；未配置时降级为按原始向量分数排序 | — |
| `RERANK_API_KEY` | 重排序服务 API Key | — |
| `RERANK_BASE_URL` | 重排序服务地址（代码自动拼接 `/rerank` 端点） | — |
| `RERANK_MODEL` | 重排序模型名 | `qwen3-reranker` |

### 联网搜索配置（`campus_rag/.env`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WEBSEARCH_PROVIDER` | 搜索源：`tavily`（需 Key）或 `ddg`（DuckDuckGo，免 Key） | `tavily` |
| `TAVILY_API_KEY` | Tavily API Key（免费版 1000 次/月）；未配置时自动回退 DuckDuckGo | — |

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
│   │   ├── personal_data.py   #     个人知识库 CRUD、文件解析导入
│   │   ├── schedule.py        #     课表查询 / 导入
│   │   ├── digest.py          #     今日面板摘要、事件追踪
│   │   ├── news.py            #     校站头条聚合
│   │   ├── settings.py        #     LLM 配置、模型切换、工具开关
│   │   ├── sync.py            #     公共通知同步管理
│   │   └── health.py          #     健康检查
│   └── services/              #   业务逻辑层
│       ├── auth_service.py    #     话题管理服务
│       ├── chat_service.py    #     Agent 管理、对话执行（未配 LLM Key 时降级不阻断启动）
│       ├── rag_service.py     #     RAG 检索、数据入库
│       ├── schedule_service.py #    本地课表存储（schedule.db）
│       ├── ustc_schedule.py   #     教务课表 HTML/JSON 解析（不接触账号密码）
│       ├── news_service.py    #     校站头条实时抓取与缓存
│       ├── file_import.py     #     个人文件文本提取（PDF/DOCX/TXT 等，不保存原文件）
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
├── campus_rag/                # RAG 检索系统（详见 campus_rag/README.md）
│   ├── __init__.py            #   包入口，导出公开接口
│   ├── config.py              #   LlamaIndex 全局设置
│   ├── llm_factory.py         #   LLM / Embedding 工厂（ollama ↔ openai）
│   ├── data_loader.py         #   文档加载和 SentenceSplitter 切分
│   ├── index_manager.py       #   ChromaDB 索引管理（公共 + 个人隔离）
│   ├── keyword_retriever.py   #   BM25 关键词检索（jieba 分词）
│   ├── query.py               #   检索接口（向量检索 / LLM 总结 / 入库）
│   ├── query_engine.py        #   RAG 管线（向量检索 + 重排序 + LLM 生成）
│   ├── data/                  #   校园通知 .txt 源数据
│   ├── ustc_sites.json        #   科大官网白名单（联网工具用）
│   ├── course_review_sites.json #  评课社区白名单（联网工具用）
│   └── .env.example           #   嵌入配置模板
├── tools/                     # Agent 工具
│   ├── search.py              #   联网搜索与网页抓取（Tavily 主 + DuckDuckGo 兜底）
│   └── ustc_crawler.py        #   通知栏目采集辅助（供 scripts/ 使用）
├── frontend/                  # React 18 前端
│   └── src/
│       ├── pages/
│       │   ├── DigestPage.tsx      #   今日面板：追踪事件 + 即将截止/进行中 + 最近发布
│       │   ├── NewsPage.tsx        #   最新消息：五个校站首页头条聚合
│       │   ├── ChatPage.tsx        #   SSE 流式对话 + Markdown 渲染（GFM 表格）+ 停止生成
│       │   ├── PersonalDataPage.tsx #   个人知识库管理
│       │   ├── SchedulePage.tsx    #   结构化课表导入与离线查看
│       │   └── SyncPage.tsx        #   公共通知同步
│       ├── components/
│       │   ├── Schedule/
│       │   │   ├── UstcScheduleImportModal.tsx   # 教务课表导入弹窗（HTML/JSON/CSV）
│       │   │   └── ImportExistingScheduleModal.tsx # 已导入课表同步到个人数据弹窗
│       │   └── Layout/
│       │       ├── AppLayout.tsx    #   侧边栏（菜单 + 话题列表）+ 顶栏
│       │       └── SettingsModal.tsx #   LLM/工具 设置弹窗
│       ├── services/
│       │   └── api.ts              #   API 调用封装
│       ├── stores/
│       │   └── topicStore.ts        #   话题状态
│       └── types/
│           └── index.ts            #   TypeScript 类型定义
├── tests/                     # 单元测试（`pytest tests/ -v`）+ events_ground_truth.json 事件抽取真值
├── scripts/                   # 网页源同步、通知栏目采集与事件抽取评测（详见 campus_rag/README.md）
├── data/                      # 运行时数据（checkpoint DB，gitignore）
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
| POST | `/api/schedule/import-ustc` | 解析教务课表 HTML/JSON 并导入（仅允许本地来源） |

#### 个人知识库

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/personal-data` | 列出个人数据（按来源聚合） |
| POST | `/api/personal-data` | 添加个人数据 |
| POST | `/api/personal-data/parse-file` | 解析上传文件（TXT/MD/CSV/JSON/PDF/DOCX）为文本供编辑后入库 |
| POST | `/api/personal-data/import-schedule` | 将已导入的本地课表写入个人知识库 |
| GET | `/api/news?refresh=` | 五个校站首页头条聚合（实时抓取 + 5 分钟缓存，`refresh=true` 强制刷新） |
| PUT | `/api/personal-data/{source}` | 编辑个人数据 |
| DELETE | `/api/personal-data/{source}` | 删除个人数据 |

#### 搜索

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/search/notices?q=` | 搜索公共通知 |
| GET | `/api/search/my-data?q=` | 搜索个人数据 |
| GET | `/api/digest?days=7` | 校园信息摘要：最近新通知 + 临近截止/进行中与即将开始事件（基于时间索引，不依赖嵌入/LLM） |
| GET | `/api/digest/tracked` | 列出追踪的事件（今日面板置顶） |
| POST | `/api/digest/tracked` | 追踪一条事件 |
| DELETE | `/api/digest/tracked/{source}` | 取消追踪 |

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

### 网页采集与更新

需要长期跟踪的公开网页配置在 `campus_rag/web_sources.json`：

```json
[
  {
    "name": "中国科大网络信息中心柜面服务",
    "url": "https://ustcnet.ustc.edu.cn/40939/list.htm",
    "output": "ustcnet_40939_counter_service.txt"
  }
]
```

抓取并比较网页正文；只有内容变化时才更新本地 TXT：

```bash
python scripts/sync_web_sources.py
```

抓取完成后同时重建公共 ChromaDB 向量索引：

```bash
python scripts/sync_web_sources.py --reindex
```

通知栏目批量采集配置在 `campus_rag/ustc_columns.json`。默认同步四个栏目的最近一页：
中国科大主页“服务类通知”（10 条）、教务处教学通知（10 条）、教务处信息通知（10 条）、
研究生院通知公告（15 条）。支持的站点文章链接格式：主站 `/info/<栏目>/<文章>.htm`、
研究生院 `/article/<id>`、教务处 `<栏目>/<子栏目>/<id>.html`：

```bash
python scripts/sync_ustc_columns.py
python scripts/sync_ustc_columns.py --reindex
```

`max_pages` 控制追溯页数（分页命名仅适配主站 Visual SiteBuilder，教务处/研究生院请保持 1），
`max_articles` 控制单次文章上限。旧版通知若跳转到
统一身份认证，将记为 `skipped`，不会尝试绕过登录。教务处/研究生院栏目与本地手动种子文件
（`20425_…` / `3384_…` 等）内容相同但文件名不同：首次跑采集后可删除手动种子文件，
避免公共索引里同文双份（或用 `delete_public_data(source)` 精确清理旧 source）。

Agent 提供六个互补的联网工具：`web_search` 按关键词查找公开网页，
`web_fetch` 在已知 URL 时提取网页可见正文；`ustc_web_search` 只搜索配置中的
中国科大官方网站，`ustc_web_fetch` 只读取白名单校站；`course_review_search`
和 `course_review_fetch` 专门搜索、读取 USTC 评课社区的公开课程页。校站清单配置在
`campus_rag/ustc_sites.json`，已包含综合教务系统
`https://jw.ustc.edu.cn/home` 和公开课程目录
`https://catalog.ustc.edu.cn/query`；评课社区配置在
`campus_rag/course_review_sites.json`，入口为 `https://icourse.club/`。

### 选课信息与评课对比

综合教务系统的个人课表、已选课程和选课结果需要统一身份认证。项目可以打开并检索
教务公开页面，但不会保存账号、密码、Cookie，也不会代替用户提交选课；个人课表继续
通过“获取课表”导入用户主动复制或选择的 HTML/JSON。公开课程目录可作为官方课程信息
来源。用户询问选课建议时，Agent 会先使用教务系统/课程目录获取课程名称、教师、学分、
时间等官方信息，再使用 `course_review_search` / `course_review_fetch` 查询
`icourse.club` 的评分、难度、作业量、给分、收获和学生点评，回答中分别标注官方事实与
学生主观意见。评课内容可能过时或存在样本偏差，只作为参考。

抓取器拒绝本机和私有网络地址，
限制单页响应大小为 2 MiB、工具输出为 20000 字符；中国科大官方域名允许兼容
本地代理的 Fake-IP DNS 映射。

搜索工具会将网页标题和 URL 组合成 Markdown 链接（`[标题](URL)`），Agent 在回答中应保留这种格式；聊天页面也会将裸 URL 渲染为可点击链接，并把链接外的括号、句号等标点保留在链接外，在新标签页打开。

### RAG 模块测试

```bash
# 事件抽取质量评测（零第三方依赖）：对比真值与抽取结果，输出逐字段 P/R
python scripts/eval_events.py

# 检索召回率评测：默认 BM25 离线模式，--vector 走向量检索（需嵌入服务）；
# 输出 Recall@1/3/5/10 与 MRR@10。当前基线：BM25 R@1 88.6% / R@5 100%，
# 向量 R@1 88.6% / R@3 100%（35 条 query，真值 tests/retrieval_ground_truth.json）
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --vector

# 公共数据检索
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"

# LLM 总结检索（需配置 settings.json 中的 api_key 或 LLM_API_KEY）
python -c "from campus_rag import search_notices_answer; print(search_notices_answer('今年暑假有什么活动？'))"

# 个人数据入库与检索
python -c "
from campus_rag import add_user_data, search_user_data
from llama_index.core import Document
docs = [Document(text='【7月5日】编程比赛 地点：线上', metadata={'source': '个人备忘'})]
add_user_data('local_user', docs)
print(search_user_data('编程比赛', user_id='local_user'))
"

# BM25 独立检索
python -c "
from campus_rag.keyword_retriever import BM25Retriever
bm25 = BM25Retriever('./campus_rag/data/')
nodes = bm25.retrieve('编程比赛', top_k=5)
for n in nodes:
    print(n.score, n.node.text[:100])
"

# 高级查询引擎
python -c "
from campus_rag import RAGSystem, get_rag_response
rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine('local_user')
print(get_rag_response('今年暑假有什么活动？', pub_idx, user_idx))
"
```

### 课表导入与离线查看

“我的课表”是项目自己的 UI，课程数据保存在本机 `schedule.db`，查看不依赖 Chrome
或教务系统。进入页面后可以使用“导入课表文件”导入 JSON/CSV，也可以点击“获取课表”，
在教务系统打开“我的课表”，等待课程加载完成后，在开发者工具 Console 执行
`copy(document.documentElement.outerHTML)`，再将复制内容粘贴到导入窗口。解析器读取 USTC
教务系统的 `#lessons` 明细表和 `timetable` 节次时间，导入后使用“刷新本地课表”重新读取
本机数据。个人数据页面的“导入已有课表”会选择本机已保存的学期课表并同步到个人知识库，
不会重新请求或解析教务 HTML，也不会修改结构化课表。项目不保存账号、密码或浏览器 Cookie。

JSON 格式示例：

```json
{
  "semester": "2026年秋季学期",
  "courses": [
    {
      "course_code": "210716.01",
      "name": "课程名称",
      "teachers": ["教师姓名"],
      "credits": 2,
      "meetings": [
        {
          "weekday": 5,
          "sections": [8, 9],
          "weeks": [1, 2, 3],
          "start_time": "15:55",
          "end_time": "17:30",
          "location": "教室"
        }
      ]
    }
  ]
}
```

CSV 至少包含 `name,weekday,sections,weeks,location,start_time,end_time` 列。
课表卡片会同时显示具体时间和节次；未提供具体时间时，系统会对常见节次使用默认时间段。

课表接口：

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/schedule` | 获取当前用户的本地课表 |
| POST | `/api/schedule/import` | 用结构化课程数据替换指定学期课表 |
| POST | `/api/schedule/import-ustc` | 解析用户提供的 USTC 课表 HTML/JSON 并更新课表 |
| POST | `/api/personal-data/import-schedule` | 读取已保存课表并同步到个人数据 |

### 后端测试

```bash
# 运行单元测试
pytest tests/ -v

# 手动测试 API
curl http://localhost:8000/api/health
curl "http://localhost:8000/api/search/notices?q=讲座"
curl "http://localhost:8000/api/personal-data"
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
- **联网搜索超时**：`web_search`/`ustc_web_search` 的连接超时为 5 秒、读取超时为 15 秒；网页正文抓取读取超时为 20 秒，失败会返回明确错误，不会无限等待
- **嵌入/重排序服务**：默认走 USTC LLM 网关的云端模型，需校园网或 VPN 才能访问；嵌入改用本地 Ollama 时（`EMBED_PROVIDER=ollama`）首次加载模型需几十秒
- **数据文件格式**：`campus_rag/data/` 下的通知文件必须以 `.txt` 结尾，否则会被跳过
- **文档分块**：每篇通知会被 `SentenceSplitter` 切分为多个 1024 字符的块，管理面板按文件名聚合显示
- **Windows 代理**：如果系统配置了 HTTP 代理，httpx 可能误用导致 Ollama 连接 502，`llm_factory.py` 已内置清除逻辑
- **ChromaDB 持久化**：向量数据存储在项目根目录的 `chroma_db/`，删除后重启服务会自动从 `data/` 重新索引
- **Sync Server**：公共通知同步需要额外启动 Sync Server（端口 8001），未启动时同步功能显示离线，不影响其他功能
- **工具偏好**：每个话题可独立启/禁用 Agent 工具，偏好通过设置面板管理
- **重排序降级**：重排序走 `campus_rag/.env` 配置的 `RERANK_*` API（默认 USTC 网关 qwen3-reranker），未配置或端点不可用时自动降级为按原始向量分数排序，不阻断检索
- **未配 LLM Key 也能启动**：后端在未配置 DeepSeek Key 时正常启动，课表、个人数据、同步等 API 可用，仅对话功能报配置错误提示；配好 Key 后无需重启即可生效（设置面板保存会失效 Agent 缓存）
- **教务课表导入**：项目不保存教务账号、密码或浏览器 Cookie；请在教务系统课表页加载完成后复制运行时 HTML（或导出 JSON/CSV）粘贴导入
- **DeepSeek `/beta` 端点**：DeepSeek V4 系列模型（`deepseek-v4-flash` / `deepseek-v4-pro`）需通过 `/beta` 路径访问。`llm_factory.py` 会在检测到 `api.deepseek.com` 且 `base_url` 未含 `/beta` 时自动补齐后缀，`settings.json` 中写 `https://api.deepseek.com` 即可，无需手动加 `/beta`

## 未来规划

### 增加数据覆盖的广度和深度

* **时效性** — ✅ 第一阶段已完成。`scripts/sync_ustc_columns.py` 配置化采集 11 个官方栏目（主站服务类通知、教务处教学/信息通知、研究生院通知/新闻/政策、网络信息中心公告等，约 340 篇），带限流退避重试与按内容增量更新；语料不入 git（`.gitignore` 的 `ustc*.txt`），换机重跑脚本 + `--reindex` 即可恢复。后续可扩展栏目（校历、就业信息、社团活动）与定时增量同步
* **数据结构化**：课表、成绩等是结构化信息，现有 txt 格式不能很好存储（课表已支持结构化导入，成绩待做）
* **数据多模态**：图片支持较难；pdf、word 已支持在个人知识库上传解析为文本入库（`/api/personal-data/parse-file`），公共语料的 pdf/word 转化待做

### 推理能力强化

* **多跳推理** — ✅ 已实现。Agent system prompt 内嵌多跳推理指南，自动多轮检索并综合回答
* **个性化**：建立个人档案，检索时根据个人特征加权，如网安专业对网安相关通知更重视
* **可溯源** — ✅ 已实现。入库时提取源网址存入元数据（数字 ID 前缀文件按 ID 匹配官方链接；爬虫文档回退解析正文"来源："行），检索结果与回答均携带来源链接

### 工程化

* 一键安装运行（降低启动步骤复杂度）
* 系统指标（召回率、命中率）评测体系 — ✅ 已建立两个维度：事件抽取（真值 `tests/events_ground_truth.json` + 逐字段 P/R，`scripts/eval_events.py`）与检索召回（真值 `tests/retrieval_ground_truth.json` + Recall@k/MRR，`scripts/eval_retrieval.py`，支持 BM25 离线与向量两种模式）；端到端回答质量评测待建
* 安全性强化

### 工具扩展

- [x] **联网搜索工具** — Tavily 主 + DuckDuckGo 兜底查找公开网页，`web_fetch`/`ustc_web_fetch` 工具提取正文；支持配置化网页增量更新和公共索引重建
- [ ] **知识图谱工具** — 基于 Neo4j 或 NetworkX 构建课程依赖、教师关系等结构化知识
- [x] **主动推送（今日面板）** — 前端 `/today` 面板消费 `/api/digest`，打开即见临近截止/进行中/即将开始事件与最近新通知；事件可追踪置顶，临近 3 天高亮；固定时间聚合推送/桌面通知为后续阶段
- [x] **日程解析工具（第一阶段）** — 从通知中确定性抽取截止日/发生时间（展览·施工·停水等 span）/发布日/类别/适用对象/地点，`get_upcoming_events(kind=deadline|start)` 按真实日期查询，进行中事件单独标注；自动生成日历事件为后续阶段
- [ ] **图片/多模态支持** — 结合多模态 LLM 解析通知中的海报图片
