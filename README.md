# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

本地单用户客户端：无登录、无用户系统，所有数据（对话历史、个人知识库、向量索引）保存在本机。

## 功能特性

- **多轮对话** — SSE/WebSocket 流式输出 + LangGraph 检查点持久化，支持 Markdown 渲染和“停止生成”打断
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
     ├── web_search / fetch_url                       → 联网搜索与网页抓取（tools/）
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

## campus_rag 模块详解

 **重排序模型部署说明**：项目使用 `BAAI/bge-reranker-base`（约 1GB）做交叉编码重排序。该模型**不会自动下载**——代码默认开启 HuggingFace 离线模式（`HF_HUB_OFFLINE=1`），需提前将模型下载到本地 HF 缓存，并将 `HF_HOME` 环境变量指向缓存目录：

```bash
# 下载模型到本地缓存（任选其一）
export HF_HOME=/path/to/hf_cache        # 例如 E:\HFCache
huggingface-cli download BAAI/bge-reranker-base

# 或用 Python 下载
python -c "from transformers import AutoModelForSequenceClassification, AutoTokenizer; \
AutoTokenizer.from_pretrained('BAAI/bge-reranker-base'); \
AutoModelForSequenceClassification.from_pretrained('BAAI/bge-reranker-base')"
```

模型缺失时 `rerank_nodes` 会自动降级为按原始向量分数排序，不阻断检索。

### `config.py` — 全局配置

导入即生效，设置 LlamaIndex 的全局 LLM、Embedding 模型及分块参数。

```python
from llama_index.core import Settings
from .llm_factory import get_llm, get_embed_model

Settings.llm = get_llm()
Settings.embed_model = get_embed_model()
Settings.chunk_size = 1024
Settings.chunk_overlap = 50
```

### `llm_factory.py` — 模型工厂

- `get_llm()` — 返回对话模型，默认从 `settings.json` 读取配置，支持 DeepSeek 模型
- `get_embed_model()` — 返回嵌入模型，支持 ollama / openai 两种后端

### `data_loader.py` — 数据加载

- `load_documents_from_files(directory)` — 读取目录下所有 `.txt` 文件，每个文件为一个 `Document`，附带 `source` 元数据
- `split_documents(documents)` — 使用 `SentenceSplitter` 分块，每块不超过 1024 token

### `index_manager.py` — 索引管理

核心类 `RAGSystem`，基于 ChromaDB 持久化向量存储，自动 MD5 去重。

**公共数据方法：**

| 方法 | 说明 |
|---|---|
| `create_public_index(data_dir)` | 从目录新建公共索引 |
| `create_public_index_via_docs(documents)` | 从 Document 列表创建公共索引（用于全量同步） |
| `get_or_create_public_index(data_dir)` | 获取已有索引，不存在则创建 |
| `get_public_index()` | 直接获取公共索引 |
| `add_documents_to_public(documents)` | 增量添加文档到公共集合 |
| `list_public_documents()` | 列出公共集合中所有文档 |
| `delete_public_document(doc_id)` | 按 ChromaDB ID 删除单条文档 |
| `delete_public_documents_by_source(source)` | 按来源文件名删除所有文档块 |
| `get_public_documents_by_source(source)` | 按 source 获取文档详情 |

**个人数据方法：**

| 方法 | 说明 |
|---|---|
| `get_or_create_user_index(user_id)` | 获取或创建个人索引 |
| `get_user_index(user_id)` | 获取个人索引 |
| `add_user_documents(user_id, documents)` | 向个人索引追加文档 |
| `list_user_documents(user_id)` | 列出个人所有文档 |
| `delete_user_documents_by_source(user_id, source)` | 按来源删除个人数据 |
| `clear_user_index(user_id)` | 清空个人全部数据 |
| `get_combined_query_engine(user_id)` | 返回 `(public_index, user_index)` 元组 |

**统计方法：**

| 方法 | 说明 |
|---|---|
| `get_collection_stats()` | 返回各集合的文档计数 |
| `get_user_collection_size(username)` | 返回个人集合文档数量 |

**数据隔离模型：**

```
ChromaDB
├── public            ← 官方通知（共享）
├── user_local_user   ← 本地个人数据
└── ...
```

### `query.py` — 检索接口

模块级函数，内部自动管理 RAGSystem 单例和 ChromaDB 连接恢复。

**纯向量检索（不经过 LLM）：**

```python
from campus_rag import search_notices, search_user_data

search_notices("暑假有什么活动？")
search_user_data("我的课表", user_id="local_user")
```

**LLM 总结检索（向量检索 + 重排序 + LLM 生成）：**

```python
from campus_rag import search_notices_answer, search_user_data_answer

search_notices_answer("暑假有什么活动？")
search_user_data_answer("我的课表", user_id="local_user")
```

**数据入库：**

```python
from campus_rag import add_user_data, add_user_files, list_user_data, delete_user_data
from llama_index.core import Document

docs = [Document(text="操作系统 周三3-4节 3A201", metadata={"source": "课表"})]
add_user_data("local_user", docs)
add_user_files("local_user", "./my_data/课表.txt")
add_user_files("local_user", "./my_data/")           # 导入整个目录
list_user_data("local_user")
delete_user_data("local_user", "课表.txt")
```

### `query_engine.py` — RAG 管线

完整的 RAG 管线：向量检索 → 重排序 → LLM 生成回答。

```python
from campus_rag import RAGSystem, get_rag_response, rerank_nodes

rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine("local_user")

# 同时检索公共和个人数据
answer = get_rag_response("暑假有什么活动？", pub_idx, user_idx)

# 仅检索公共数据
answer = get_rag_response("讲座", public_index=pub_idx)

# 仅检索个人数据
answer = get_rag_response("我的课表", user_index=user_idx)

# 单独使用重排序
nodes = rerank_nodes("查询文本", nodes, top_n=10)
```

**管线流程：**

```
用户问题
  ├── 向量检索 (ChromaDB: public + user_{id})
  ├── 合并去重
  ├── 重排序 (bge-reranker-base，AutoTokenizer + AutoModelForSequenceClassification)
  └── LLM 生成回答
```

`rerank_nodes` 内置降级策略：重排序模型不可用时自动退化为按原始分数排序。BM25Retriever 和 VectorIndexRetriever 均有缓存，数据未变化时不会重复构建。

### `keyword_retriever.py` — BM25 检索器

基于 `rank_bm25` + `jieba` 分词的稀疏检索，对关键词匹配敏感，与向量检索互补。

```python
from campus_rag.keyword_retriever import BM25Retriever

bm25 = BM25Retriever("./data")
nodes = bm25.retrieve("编程比赛", top_k=10)
```

`_tokenize` 内置降级策略：`jieba` 不可用时自动回退到正则分词。

### `__init__.py` — 包入口

```python
from campus_rag import (
    # 检索
    search_notices, search_user_data,
    search_notices_answer, search_user_data_answer,
    # 入库
    add_user_data, add_user_files,
    list_user_data, delete_user_data,
    # 高级查询
    get_rag_response, rerank_nodes,
    # 核心类
    RAGSystem,
)
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

通知栏目批量采集配置在 `campus_rag/ustc_columns.json`。默认同步中国科大主页
“服务类通知”最近一页中的 10 条文章，并将每篇公开正文保存成独立 TXT：

```bash
python scripts/sync_ustc_columns.py
python scripts/sync_ustc_columns.py --reindex
```

`max_pages` 控制追溯页数，`max_articles` 控制单次文章上限。旧版通知若跳转到
统一身份认证，将记为 `skipped`，不会尝试绕过登录。

Agent 提供四个互补的联网工具：`web_search` 按关键词查找公开网页，
`web_fetch` 在已知 URL 时提取网页可见正文；`ustc_web_search` 只搜索配置中的
中国科大官方网站，`ustc_web_fetch` 只读取白名单校站。校站清单配置在
`campus_rag/ustc_sites.json`，默认包括学校主页、网络信息中心、本科生院教务处、
研究生院、就业信息网和图书馆。

抓取器拒绝本机和私有网络地址，
限制单页响应大小为 2 MiB、工具输出为 20000 字符；中国科大官方域名允许兼容
本地代理的 Fake-IP DNS 映射。

搜索工具会将网页标题和 URL 组合成 Markdown 链接（`[标题](URL)`），Agent 在回答中应保留这种格式；聊天页面也会将裸 URL 渲染为可点击链接，并把链接外的括号、句号等标点保留在链接外，在新标签页打开。

### RAG 模块测试

```bash
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
或教务系统。进入页面后使用“导入课表文件”导入 JSON/CSV，使用“刷新本地课表”重新
读取本机数据。若要从教务系统更新，请在教务系统中导出课表后再导入；项目不保存账号、
密码或浏览器 Cookie，也不通过浏览器插件读取课表。

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
- **嵌入模型**：本地 Ollama 的 `nomic-embed-text` 首次加载需几十秒；切换为云端嵌入可避免此问题
- **数据文件格式**：`campus_rag/data/` 下的通知文件必须以 `.txt` 结尾，否则会被跳过
- **文档分块**：每篇通知会被 `SentenceSplitter` 切分为多个 1024 字符的块，管理面板按文件名聚合显示
- **Windows 代理**：如果系统配置了 HTTP 代理，httpx 可能误用导致 Ollama 连接 502，`llm_factory.py` 已内置清除逻辑
- **ChromaDB 持久化**：向量数据存储在项目根目录的 `chroma_db/`，删除后重启服务会自动从 `data/` 重新索引
- **Sync Server**：公共通知同步需要额外启动 Sync Server（端口 8001），未启动时同步功能显示离线，不影响其他功能
- **工具偏好**：每个话题可独立启/禁用 Agent 工具，偏好通过设置面板管理
- **重排序模型离线**：`campus_rag/query_engine.py` 默认开启 HF 离线模式，`bge-reranker-base` 需提前下载到 `HF_HOME` 指向的本地缓存（见上文「重排序模型部署说明」）。模型不可用时重排序自动降级为按原始分数排序
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
