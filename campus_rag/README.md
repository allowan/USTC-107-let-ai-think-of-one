# campus_rag — RAG 核心库

独立可测的校园通知检索系统：LlamaIndex + ChromaDB 向量检索、BM25 关键词检索、API 重排序、源链接溯源。不依赖 `server/`，可单独调用与测试。

## 公开接口（经 `campus_rag/__init__.py` 导出）

跨模块使用一律通过包入口导出的公共 API，禁止直接导入内部函数或私有变量。

### 纯检索（不经过 LLM）

```python
from campus_rag import search_notices, search_user_data

search_notices("暑假有什么活动？")
search_user_data("我的课表", user_id="local_user")
```

### LLM 总结检索（向量检索 + 重排序 + LLM 生成）

```python
from campus_rag import search_notices_answer, search_user_data_answer

search_notices_answer("暑假有什么活动？")
search_user_data_answer("我的课表", user_id="local_user")
```

### 数据入库与管理

```python
from campus_rag import add_user_data, add_user_files, list_user_data, delete_user_data, update_user_data
from llama_index.core import Document

docs = [Document(text="操作系统 周三3-4节 3A201", metadata={"source": "课表"})]
add_user_data("local_user", docs)
add_user_files("local_user", "./my_data/课表.txt")
add_user_files("local_user", "./my_data/")           # 导入整个目录
list_user_data("local_user")
update_user_data("local_user", "课表", "新内容")      # 先探测嵌入可用性再删旧写新
delete_user_data("local_user", "课表.txt")
```

同步服务专用（公共集合）：`add_public_documents` / `delete_public_data` / `replace_public_documents` / `reset_caches`。

### 高级查询引擎

```python
from campus_rag import RAGSystem, get_rag_response, rerank_nodes

rag = RAGSystem()
pub_idx, user_idx = rag.get_combined_query_engine("local_user")
answer = get_rag_response("暑假有什么活动？", pub_idx, user_idx)
nodes = rerank_nodes("查询文本", nodes, top_n=10)
```

## 模块构成

| 文件 | 职责 |
|---|---|
| `config.py` | LlamaIndex 全局设置（分块参数）；`init_llm/init_embed` + `require_llm/require_embed_model` fail-fast 守卫，禁止静默降级到 Mock |
| `llm_factory.py` | `get_llm()` / `get_embed_model()` 工厂，支持 openai / ollama 后端 |
| `data_loader.py` | `.txt` 加载、SentenceSplitter 分块（打 `chunk_index` 序号）、按通知 ID 提取源网址 |
| `index_manager.py` | `RAGSystem`：ChromaDB 集合管理、维度守卫与自愈、MD5 去重 |
| `keyword_retriever.py` | `BM25Retriever`：rank_bm25 + jieba 分词（jieba 缺失时正则回退） |
| `query.py` | 检索门面：单例管理、检索出口统一附来源头、入库统一入口 |
| `query_engine.py` | RAG 管线：向量检索 → BM25 预过滤加权 → 重排序 → LLM 生成 |
| `auth.py` | 话题 CRUD + 工具偏好 CRUD（SQLite，锚定项目根 `users.db`）；另含遗留的登录函数（`authenticate` / `register_user` / `list_users`），本地单用户形态下无路由调用 |
| `data/` | 校园通知 `.txt` 源数据（公共索引可从这里全量重建） |

## 检索管线

```
用户问题
  ├── 向量检索 (ChromaDB: public + user_{id})
  ├── BM25 关键词检索（对向量结果预过滤，命中节点加权；仅公共通知检索启用）
  ├── 合并去重
  ├── 重排序 (qwen3-reranker，API 调用 /rerank 端点；不可用时降级为原始分数排序)
  └── LLM 生成回答（携带来源文件名 + 源链接）
```

## 数据隔离模型

```
ChromaDB（项目根 chroma_db/）
├── public            ← 官方通知（共享，可从 campus_rag/data 重建）
├── user_local_user   ← 本地个人数据（不可自动重建）
└── ...
```

- 默认数据目录与向量库目录均为锚定项目根的绝对路径，不依赖启动 CWD。
- **维度守卫**：集合已存向量维度与当前嵌入模型不一致时，公共集合自动删除并从源数据重建；个人集合抛出可操作错误（避免 MockEmbedding 维度 1 永久污染）。
- **写路径安全**：`update_user_data` / `replace_public_documents` 在删除旧数据前先探测嵌入可用性，不可用则拒绝整个操作，原数据不受影响。

## 配置（`campus_rag/.env`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `EMBED_PROVIDER` | 嵌入来源：`openai`（API）或 `ollama`（本地回退） | `openai` |
| `EMBED_API_KEY` | 嵌入 API Key | — |
| `EMBED_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.llm.ustc.edu.cn/v1` |
| `EMBED_MODEL` | 嵌入模型名 | `qwen3-embedding` |
| `RERANK_PROVIDER` | 设为 `api` 启用 qwen3-reranker；未配置时降级为原始分数排序 | — |
| `RERANK_API_KEY` | 重排序 API Key | — |
| `RERANK_BASE_URL` | 重排序 API 地址 | `https://api.llm.ustc.edu.cn/v1` |
| `RERANK_MODEL` | 重排序模型名 | `qwen3-reranker` |
| `WEBSEARCH_PROVIDER` | 联网搜索源：`tavily`（需 Key）或 `ddg`（免 Key 兜底） | `tavily` |
| `TAVILY_API_KEY` | Tavily 搜索 API Key（免费版 1000 次/月） | — |
| `LLM_PROVIDER` / `OPENAI_*` / `OLLAMA_*` | RAG 回答生成用 LLM 的覆盖项（默认读 `settings.json`） | — |

> 嵌入必须使用独立的 `EMBED_*` / `RERANK_*` 变量，不要复用 `OPENAI_*`（那是 LLM 分支的覆盖变量，混用会互相污染）。
> 注意：嵌入网关 `api.llm.ustc.edu.cn` 仅校园网/VPN 可达。

## 测试

```bash
pytest tests/test_campus_rag.py -v

# 快速冒烟（需嵌入/LLM API 可达）
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"
python -c "from campus_rag import search_notices_answer; print(search_notices_answer('今年暑假有什么活动？'))"
```

嵌入或 LLM 不可用时，依赖网络的用例会自动跳过（不视为失败）。
