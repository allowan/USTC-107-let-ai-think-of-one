# campus_rag — 多租户校园活动 RAG 系统

## 环境准备

依赖已合并到项目根目录的 `requirements.txt`，在项目根目录安装即可。

### 安装 Ollama（本地模型）

到 [ollama.com](https://ollama.com) 下载安装，然后拉取模型：

```bash
ollama pull llama3.1:8b          # 对话模型
ollama pull nomic-embed-text     # 嵌入模型
```

首次运行时会自动下载重排序模型 `BAAI/bge-reranker-base`（约 1GB）。

### 配置环境变量

编辑 `campus_rag/.env`：

```ini
# LLM 配置（ollama / openai）
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
# 当 LLM_PROVIDER=openai 时生效
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=deepseek-chat

# Embedding 配置（ollama / openai）
EMBED_PROVIDER=ollama
OLLAMA_EMBED_MODEL=nomic-embed-text
OPENAI_EMBED_MODEL=text-embedding-3-small
```

---

## 项目结构

```
campus_rag/
├── __init__.py            # 包入口，自动加载 .env 并导出公开接口
├── config.py              # LlamaIndex 全局配置（LLM、Embedding、chunk 参数）
├── llm_factory.py         # LLM/Embedding 工厂，支持 ollama ↔ openai 热切换
├── data_loader.py         # 文档加载与分块
├── index_manager.py       # ChromaDB 集合管理（公共 + 用户隔离）
├── query.py               # 简单检索接口（不经过 LLM，直接返回原文片段）
├── query_engine.py        # 高级查询引擎（混合检索 + 重排序 + LLM 生成）
├── keyword_retriever.py   # BM25 关键词检索器
├── auth.py                # 用户认证系统（SQLite + bcrypt）
├── ingest.py              # 动态入库接口
├── data/                  # 校园通知 txt 文件
├── chroma_db/             # ChromaDB 持久化目录（自动生成）
├── .env                   # 环境变量
└── README.md
```

---

## 模块说明

### `config.py` — 全局配置

导入即生效，设置 LlamaIndex 的全局 LLM、Embedding 模型及分块参数。其他模块只需 `import config` 即可。

```python
# config.py
from llama_index.core import Settings
from .llm_factory import get_llm, get_embed_model

Settings.llm = get_llm()
Settings.embed_model = get_embed_model()
Settings.chunk_size = 1024
Settings.chunk_overlap = 50
```

### `llm_factory.py` — 模型工厂

根据 `.env` 中的 `LLM_PROVIDER` / `EMBED_PROVIDER` 动态创建模型实例，支持 ollama（本地免费）和 openai（兼容接口）两种后端。

- `get_llm()` — 返回对话模型（用于生成回答）
- `get_embed_model()` — 返回嵌入模型（用于向量化文档和查询）

### `data_loader.py` — 数据加载

- `load_documents_from_files(directory)` — 读取目录下所有 `.txt` 文件，每个文件为一个 `Document`，附带 `source` 元数据
- `split_documents(documents)` — 使用 `SentenceSplitter` 对文档二次分块，确保每块不超过 1024 token

### `index_manager.py` — 索引管理

核心类 `RAGSystem`，基于 ChromaDB 持久化向量存储。

**公共数据方法：**

| 方法 | 说明 |
|---|---|
| `create_public_index(data_dir)` | 从目录新建公共索引 |
| `get_or_create_public_index(data_dir)` | 获取已有索引，不存在则创建 |
| `get_public_index()` | 直接获取公共索引 |
| `add_documents_to_public(documents)` | 增量添加文档到公共集合 |

**用户私有数据方法：**

| 方法 | 说明 |
|---|---|
| `get_or_create_user_index(user_id, data_dir)` | 获取或创建用户索引 |
| `get_user_index(user_id)` | 获取用户个人索引 |
| `add_user_documents(user_id, documents)` | 向用户索引追加文档 |
| `clear_user_index(user_id)` | 清空用户全部数据 |
| `get_combined_query_engine(user_id)` | 返回 (public_index, user_index) 元组 |

**数据隔离模型：**

```
ChromaDB
├── public           ← 官方通知（共享）
├── user_alice       ← alice 的私有数据
├── user_bob         ← bob 的私有数据
└── ...
```

### `query.py` — 简单检索接口

不经过 LLM，直接从向量库检索并返回原文片段。适合作为 Agent 工具。

```python
from campus_rag import search_notices, search_user_data, search_all

# 只查公共通知
search_notices("暑假有什么活动？")

# 只查用户私有数据
search_user_data("我的课表", user_id="alice")

# 同时查公共 + 私有
search_all("近期活动", user_id="alice")
```

### `query_engine.py` — 高级查询引擎

完整的 RAG 管线：向量检索 / 混合检索 → 重排序 → LLM 生成回答。

```python
from campus_rag import RAGSystem, get_rag_response, get_rag_response_hybrid

rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine("alice")

# 纯向量检索 + 重排序 + LLM 生成
answer = get_rag_response("暑假有什么活动？", pub_idx, user_idx)

# 混合检索（向量 + BM25）+ 重排序 + LLM 生成
answer = get_rag_response_hybrid("暑假有什么活动？", pub_idx, user_idx=user_idx)
```

**管线流程：**

```
用户问题
  ├── 向量检索 (ChromaDB: public + user_{id})
  ├── BM25 关键词检索 (rank_bm25)          ← 仅 hybrid 模式
  ├── 合并去重
  ├── 重排序 (FlagEmbedding BGE-reranker)
  └── LLM 生成回答 (Ollama / OpenAI)
```

### `keyword_retriever.py` — BM25 检索器

基于 `rank_bm25` 的稀疏检索，对关键词匹配敏感，与向量检索互补。

```python
from campus_rag.keyword_retriever import BM25Retriever

bm25 = BM25Retriever("./data")
nodes = bm25.retrieve("编程比赛", top_k=10)
```

### `auth.py` — 用户认证

基于 SQLite + bcrypt 的简易用户系统，首次导入自动建表和默认管理员。

| 函数 | 说明 |
|---|---|
| `authenticate(username, password)` | 返回 `(是否成功, 是否管理员)` |
| `register_user(username, password, is_admin)` | 注册新用户，返回是否成功 |
| `list_users()` | 列出所有用户 |

默认管理员：`admin` / `admin123`

```python
from campus_rag import authenticate, register_user

ok, is_admin = authenticate("admin", "admin123")
register_user("student1", "pass123")
```

### `ingest.py` — 动态入库

```python
from campus_rag import add_public_activity, add_user_activity
from campus_rag.ingest import add_user_files

# 管理员添加公共通知
add_public_activity("【7月10日】校园科技节 地点：大活中心", admin_check=True)

# 用户添加个人数据（纯文本）
add_user_activity("alice", "操作系统 周三3-4节 3A201")

# 用户导入 txt 文件
add_user_files("alice", "./my_data/课表.txt")   # 单个文件
add_user_files("alice", "./my_data/")            # 整个目录
```

### `__init__.py` — 包入口

自动加载 `.env`，并导出所有公开接口：

```python
from campus_rag import (
    # 简单检索
    search_notices, search_user_data, search_all,
    # 高级查询
    get_rag_response, get_rag_response_hybrid, rerank_nodes,
    # 入库
    add_user_data, add_user_files, add_public_activity, add_user_activity,
    # 认证
    authenticate, register_user, list_users,
    # 核心类
    RAGSystem,
)
```

---

## 测试指南

### 1. 测试公共数据检索

```bash
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"
```

### 2. 测试用户认证

```bash
python -c "
from campus_rag import authenticate, register_user
# 管理员登录
ok, admin = authenticate('admin', 'admin123')
print('管理员登录:', ok, admin)
# 注册新用户
register_user('student1', 'pass123')
ok, _ = authenticate('student1', 'pass123')
print('学生登录:', ok)
"
```

### 3. 测试用户数据隔离

```bash
python -c "
from campus_rag import add_user_activity, search_user_data, search_notices

# alice 添加个人数据
add_user_activity('alice', '【7月5日】我的编程比赛 地点：线上')

# alice 查自己的数据
print('=== alice 个人数据 ===')
print(search_user_data('编程比赛', user_id='alice'))

# bob 查不到 alice 的数据
print('=== bob 查 alice 的数据 ===')
print(search_user_data('编程比赛', user_id='bob'))

# 公共数据大家都能查
print('=== 公共通知 ===')
print(search_notices('比赛'))
"
```

### 4. 测试文件导入

```bash
python -c "
from campus_rag.ingest import add_user_files
from campus_rag import search_user_data

n = add_user_files('alice', './campus_rag/data/')
print(f'导入了 {n} 个文档')
print(search_user_data('暑假', user_id='alice'))
"
```

### 5. 测试高级查询引擎（LLM 生成回答）

```bash
python -c "
from campus_rag import RAGSystem, get_rag_response

rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine('alice')
answer = get_rag_response('今年暑假有什么活动？', pub_idx, user_idx)
print(answer)
"
```

### 6. 测试混合检索

```bash
python -c "
from campus_rag import RAGSystem, get_rag_response_hybrid

rag = RAGSystem()
pub_idx, _ = rag.get_combined_query_engine('alice')
answer = get_rag_response_hybrid('编程比赛', pub_idx, data_dir='./campus_rag/data/')
print(answer)
"
```

### 7. 通过 Agent 测试

```bash
python main.py
```

### 8. 切换云端模型

修改 `campus_rag/.env`，将 `LLM_PROVIDER` 和 `EMBED_PROVIDER` 改为 `openai`，填入对应的 `OPENAI_BASE_URL` 和 `OPENAI_API_KEY`，无需改任何代码即可切换。
