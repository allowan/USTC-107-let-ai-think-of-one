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
pub_idx = rag.get_public_index()
answer = get_rag_response("暑假有什么活动？", public_index=pub_idx, data_dir="campus_rag/data")
nodes = rerank_nodes("查询文本", nodes, top_n=10)
```

### 事件时间索引（截止日/发生时间查询）

把通知里的关键字段抽取成结构化记录，使“未来 N 天内截止/发生的事件”成为确定性数据库查询（日期运算在代码里完成，不交给 LLM）。抽取用确定性正则（离线、非阻塞、可复现），入库时自动同步，无需手动调用。

```python
from campus_rag import get_upcoming_events, get_upcoming_starts, sync_notice_events

# 未来 30 天内截止的全部事件，按截止日升序
get_upcoming_events(days=30)
# 只看某类（选课/考试/答辩/评奖/竞赛/讲座/实习/助教/交通/展览/后勤/报名/其他）
get_upcoming_events(days=7, category="报名")
# 与 [today, today+days] 有交集的“发生型”事件（展览/施工/停水停电/班车等）：
# 时间窗相交语义，进行中（已开始未结束）的事件同样返回
get_upcoming_starts(days=30)
# 显式同步种子语料（启动时由 server/lifespan.py 自动调用；纯regex，不需嵌入）
sync_notice_events()
# 聚合“最近新通知 + 临近/进行中事件”为一份 dict（供前端今日面板消费）
#   返回 {generated_on, days, upcoming:[{…,kind,ongoing,days_left}], recent:[{…,days_since}]}
get_notice_digest(days=7)
```

返回 `list[dict]`，每项含 `source / title / category / audience / publish_date / deadline / deadline_text / event_start / event_end / location / url`。事件同步已挂入 `add_public_documents` / `replace_public_documents` / `delete_public_data`、RAG 初始化（`_ensure_init`）与应用启动（`lifespan` 调 `sync_notice_events`），按内容哈希 + 抽取器版本（`EXTRACTOR_VERSION`，升级抽取逻辑后递增以触发旧记录自动重抽）幂等；抽取失败只记日志，绝不影响 RAG 入库与检索。因不依赖嵌入，即使未配嵌入/LLM，事件查询仍可用。

抽取边界（评测可见 `scripts/eval_events.py`）：只抽日粒度；月粒度区间（“2026.9-2027.1”）、新闻式时间状语先行（“6月15日下午，…”）、网页表格转文本的跨行时间表（如选课阶段表）不在覆盖范围，由语义检索兜底。

### 追踪事件（今日面板用）

```python
from campus_rag import track_event, untrack_event, list_tracked_events

track_event("local_user", "20425_xxx.txt", "秋季选课", "选课", "deadline", "2026-09-11", url)
untrack_event("local_user", "20425_xxx.txt")
list_tracked_events("local_user")
```

## 模块构成

| 文件 | 职责 |
|---|---|
| `config.py` | LlamaIndex 全局设置（分块参数）；`init_llm/init_embed` + `require_llm/require_embed_model` fail-fast 守卫，禁止静默降级到 Mock |
| `llm_factory.py` | `get_llm()` / `get_embed_model()` 工厂，支持 openai / ollama 后端 |
| `data_loader.py` | `.txt` 加载、SentenceSplitter 分块（打 `chunk_index` 序号）、源网址提取（数字 ID 前缀文件按 ID 匹配；爬虫文档回退到正文"来源："行） |
| `index_manager.py` | `RAGSystem`：ChromaDB 集合管理、维度守卫与自愈、MD5 去重 |
| `keyword_retriever.py` | `BM25Retriever`：rank_bm25 + jieba 分词（jieba 缺失时正则回退） |
| `query.py` | 检索门面：单例管理、检索出口统一附来源头、入库统一入口；空结果时 jieba 关键词缩减重试一次（检索自愈）；`reset_caches` 同时失效 query_engine 的检索器/BM25 缓存 |
| `query_engine.py` | RAG 管线：向量检索 → 空召回关键词重试 → BM25 预过滤加权 → 重排序 → LLM 生成 |
| `events.py` | 通知事件时间索引：确定性正则抽取截止日/发生时间（span·instant）/发布日/类别/适用对象/地点，存入 `events.db`（抽取器版本 `EXTRACTOR_VERSION` 控制旧记录自动重抽），供 `get_upcoming_events` / `get_upcoming_starts` 按时间查询（不依赖 LLM，离线可用） |
| `auth.py` | 话题 / 工具偏好 / 追踪事件 CRUD（SQLite，锚定项目根 `users.db`）。本地单用户形态，无登录函数 |
| `data/` | 校园通知 `.txt` 源数据（公共索引可从这里全量重建）。统一格式：文件名 `{通知ID}_{标题}.txt`，文档头三行 `来源：<URL>` / `标题：<标题>` / 空行，之后为正文（段间无空行，正文只含通知内容，无站点导航/页脚噪声）。主体由 `scripts/sync_ustc_columns.py` 采集（主站服务类通知、教务处教学/信息通知、研究生院通知、网络信息中心公告等）。当前共 323 篇：7 个为 git 跟踪的手写种子，其余为未跟踪文件（数据未加忽略规则，提交时自行 `git add campus_rag/data/`）。改动数据源后需重跑 `--reindex` 重建公共索引；`events.db` 会在启动时自动重抽 |

> 数据治理说明（2026-09）：语料做过一轮"格式清洗 + 去重"。格式清洗剥离站点导航/面包屑/发布元信息/版权页脚/相关文章列表与 HTML 空格残留，可随时用 `python scripts/clean_data_files.py`（幂等，支持 `--dry-run`）复跑；同一轮删除了 8 个分页列表帧、3 个跨来源镜像重复（保留对应原始通知）与 1 个抓取损坏残片，校验后语料为 323 篇。改动或补充 txt 后需对公共索引重跑 `--reindex`。

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
- **事件时间索引**独立存于项目根 `events.db`（SQLite，与 `schedule.db`/`users.db` 同层），与向量库解耦： ChromaDB 管“语义相似”，`events.db` 管“时间排序”，两者均由 `campus_rag/data` 与同步文档派生，删除后重启可自愈。
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

# 事件抽取质量评测（零第三方依赖，仅标准库）：
# 对比 campus_rag/data 真值（tests/events_ground_truth.json）与 parse_notice 输出，
# 输出逐字段 P/R 与偏差明细；调整 events.py 抽取正则后重跑验证。
python scripts/eval_events.py

# 检索召回率评测：对比 query 真值（tests/retrieval_ground_truth.json）与
# top-k 命中来源，输出 Recall@1/3/5/10 与 MRR@10 及未命中明细；
# 默认 BM25 离线模式，--vector 走向量检索公开接口（需嵌入服务可达）。
# 调整切块、top_k、重排序等检索参数后重跑对比。
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --vector

# 快速冒烟（需嵌入/LLM API 可达）
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"
python -c "from campus_rag import search_notices_answer; print(search_notices_answer('今年暑假有什么活动？'))"
```

嵌入或 LLM 不可用时，依赖网络的用例会自动跳过（不视为失败）。
