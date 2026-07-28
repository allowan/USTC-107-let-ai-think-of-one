# campus_rag — 多租户校园活动 RAG 系统

## 环境准备

依赖已合并到项目根目录的 `requirements.txt`，在项目根目录安装即可。

### 安装 Ollama（本地模型）

到 [ollama.com](https://ollama.com) 下载安装，然后拉取模型：

```bash
ollama pull nomic-embed-text     # 嵌入模型（必需）
```

首次运行高级查询时会自动下载重排序模型 `BAAI/bge-reranker-base`（约 1GB）。

### 配置环境变量

```bash
cp campus_rag/.env.example campus_rag/.env
```

编辑 `campus_rag/.env`：

```ini
# Embedding 配置（默认 provider: ollama）
EMBED_PROVIDER=ollama
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_HOST=http://127.0.0.1:11434

# 若使用 openai 兼容的 embedding：
# EMBED_PROVIDER=openai
# OPENAI_EMBED_MODEL=text-embedding-3-small
# OPENAI_BASE_URL=https://api.deepseek.com/v1
# OPENAI_API_KEY=sk-your-key

# LLM 配置由项目根目录 settings.json 统一管理（api_key、base_url、model）
# 如需使用本地 Ollama 生成回答，可覆盖：
# LLM_PROVIDER=ollama
# OLLAMA_MODEL=llama3.1:8b
```

---

## 项目结构

```
campus_rag/
├── __init__.py            # 包入口，自动加载 .env 并导出公开接口
├── config.py              # LlamaIndex 全局配置（LLM、Embedding、chunk 参数）
├── llm_factory.py         # LLM/Embedding 工厂，支持 ollama ↔ openai 热切换
├── data_loader.py         # 文档加载与分块（.txt 文件）
├── index_manager.py       # ChromaDB 集合管理（public + user_{id} 隔离）
├── query.py               # 检索门面：纯检索 / LLM 生成回答 / 入库
├── query_engine.py        # 高级查询引擎（向量检索 + 重排序 + LLM 生成）
├── keyword_retriever.py   # BM25 关键词检索器（jieba 分词）
├── auth.py                # 用户认证 + 话题 CRUD + 工具偏好管理
├── data/                  # 校园通知 .txt 文件（公共数据源）
├── .env.example           # 嵌入配置模板
└── README.md
```

> `ingest.py` 已废弃，入库功能合并至 `query.py`。

---

## 模块说明

### `config.py` — 全局配置

导入即生效，会自动调用 `llm_factory` 创建 LLM 和 Embedding 实例并注入到 LlamaIndex 的全局 `Settings` 中，同时设定分块参数（chunk_size=1024, chunk_overlap=50）。其他模块只需 `import config` 即可获得一致的全局设置，无需各自初始化。

### `llm_factory.py` — 模型工厂

根据 `campus_rag/.env`（LLM 则由根目录 `settings.json` 管理）动态创建模型实例，支持 ollama（本地免费）和 openai（兼容接口）两种后端。对外暴露 `get_llm()`（对话模型，用于生成回答）和 `get_embed_model()`（嵌入模型，用于向量化文档和查询）。切换后端只需修改 `.env` 中的 `EMBED_PROVIDER` 字段，无需改动任何代码。

### `data_loader.py` — 数据加载

提供文档加载与分块能力。`load_documents_from_files(directory)` 扫描指定目录下所有 `.txt` 文件，每个文件转换为一个 `Document` 对象并附带 `source`（文件名）元数据。`split_documents(documents)` 使用 `SentenceSplitter` 对长文档做二次分块，确保每块不超过 1024 字符，方便后续向量化和检索。

### `index_manager.py` — 索引管理

核心类 `RAGSystem`，封装了 ChromaDB 的持久化向量存储操作。公共数据存入 `public` 集合（所有用户共享），用户私有数据存入 `user_{id}` 集合（按用户隔离）。提供完整的生命周期方法：从目录建索引、增量添加文档（自动 MD5 去重）、按来源删除、清空集合、统计文档数等。

### `query.py` — 检索门面

对外统一入口，封装了 RAGSystem 的初始化、缓存和重建逻辑，Agent 工具直接调用此层。按功能分为三类：

- **纯检索**（不经过 LLM）：`search_notices()` 查公共通知，`search_user_data()` 查用户私有数据，直接返回原文片段
- **LLM 生成回答**：`search_notices_answer()` 和 `search_user_data_answer()` 在检索后调用 `query_engine` 经 LLM 总结输出
- **入库管理**：`add_user_data()`、`add_user_files()`、`list_user_data()`、`delete_user_data()` 负责用户私有数据的增删查

### `query_engine.py` — 高级查询引擎

实现完整的 RAG 生成管线。入口 `get_rag_response()` 接收用户问题和索引，依次执行：向量检索获取 top-k 候选片段 → 合并去重 → `BAAI/bge-reranker-base` 重排序 → LLM 基于精选上下文生成最终回答。同时导出 `rerank_nodes()` 供其他模块单独使用重排序能力。

### `keyword_retriever.py` — BM25 检索器

基于 `rank_bm25` 算法 + `jieba` 中文分词实现的稀疏检索器，对精确关键词匹配（如人名、课程编号、日期）比向量检索更敏感。内部缓存已加载的目录索引，避免重复构建。当前作为独立组件可用，尚未接入 `query_engine.py` 形成向量 + BM25 的混合检索管线。

### `__init__.py` — 包入口

导入时自动加载 `campus_rag/.env` 环境变量，然后汇总各模块的公开接口统一导出。外部只需 `from campus_rag import ...` 即可使用全部功能——检索、LLM 生成、入库、认证、话题管理，无需关心内部模块路径和依赖关系。

### `auth.py` — 用户认证

基于 SQLite + bcrypt 的简易用户系统，首次导入自动建表（`users`、`topics`、`user_tool_prefs`）并创建默认管理员 `admin / admin123`。功能覆盖：用户注册/登录/列表、话题 CRUD（创建、列出、删除、重命名、查找）、用户工具偏好管理（按话题独立启/禁用 Agent 工具）。话题和偏好当前通过 `server/services/auth_service.py` 间接调用，`authenticate` 等登录函数未被路由直接使用（本地单用户模式）。

---

## 测试指南

### 1. 公共数据检索

```bash
python -c "from campus_rag import search_notices; print(search_notices('暑假有什么活动'))"
```

### 2. 用户认证

```bash
python -c "
from campus_rag import authenticate, register_user
print(authenticate('admin', 'admin123'))
register_user('student1', 'pass123')
"
```

### 3. 用户数据隔离

```bash
python -c "
from campus_rag import add_user_data, search_user_data
from llama_index.core import Document

add_user_data('alice', [Document(text='【7月5日】编程比赛 地点：线上')])
print('alice:', search_user_data('编程比赛', user_id='alice'))
print('bob:', search_user_data('编程比赛', user_id='bob'))
"
```

### 4. 文件导入

```bash
python -c "
from campus_rag import add_user_files, search_user_data
n = add_user_files('alice', './campus_rag/data/')
print(f'导入 {n} 篇', search_user_data('暑假', user_id='alice')[:200])
"
```

### 5. 高级查询（LLM 生成回答）

```bash
python -c "
from campus_rag import RAGSystem, get_rag_response
rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine('alice')
print(get_rag_response('今年暑假有什么活动', public_index=pub_idx, user_index=user_idx))
"
```

### 6. 通过 Agent 测试

```bash
python main.py
```

---

## 扩展功能

以下功能已实现（Phase 1）：

- **`search_all()`** — 同时检索公共 + 私有数据，返回带标签的合并结果
- **`add_public_activity()`** — 管理员动态添加公共通知并入库
- **`add_user_activity()`** — 用户添加纯文本个人记录
- **`get_rag_response_hybrid()`** — 向量 + BM25 混合检索 + 重排序 + LLM 生成