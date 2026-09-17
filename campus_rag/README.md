# campus_rag — RAG 核心库

独立可测的校园通知检索系统：LlamaIndex + ChromaDB 向量检索、BM25 关键词检索、API 重排序、源链接溯源。不依赖 `server/`，可单独调用与测试。

## 公开接口（经 `campus_rag/__init__.py` 导出）

`search_notices_with_evidence(query)` / `search_user_data_with_evidence(query, user_id)` 返回 `(content, artifact)`，只检索一次并从同一组节点生成工具正文和证据。artifact 含 `evidence` 与 `warnings`；每片段包含稳定标识、来源、标题、链接、发布日期、最多 2000 字原文及类别。发布日期仅使用明确元数据/标记为发布日期的原文，不将正文里的活动日期当成发布日期。工具通过 LangChain `content_and_artifact` 持久化，普通字符串搜索接口保持兼容。

跨模块使用一律通过包入口导出的公共 API，禁止直接导入内部函数或私有变量。

### 纯检索（不经过 LLM）

```python
from campus_rag import search_notices, search_user_data

search_notices("暑假有什么活动？")
search_user_data("我的课表", user_id="local_user")
```

### LLM 总结检索（混合检索 + 重排序 + LLM 生成）

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
update_user_data("local_user", "课表", "新内容")      # 新分块写入成功后替换旧分块
delete_user_data("local_user", "课表.txt")
```

同步服务专用（公共集合）：`add_public_documents`（追加）/ `upsert_public_documents`（按来源替换）/ `delete_public_data` / `replace_public_documents`（全量替换）/ `reset_caches`。

写入先完成新分块的嵌入与持久化，再删除被替换的旧 ID；新增写入失败会尝试清理本次新增 ID；移除旧 ID 失败时保留已写入的新内容供重试，异常继续上抛。公共全量同步沿用现有集合，空快照保持为空。该顺序保障嵌入/新增写入失败时旧数据仍在，但不是跨 ChromaDB 与事件库的事务：进程在写新与删旧之间崩溃可能暂留重复块，需重试同步。进程内写操作串行化，查询仍可并行。

个人数据操作不再初始化公共通知索引。纯检索与回答查询复用索引对象及同一套检索器缓存；向量与关键词缓存均有容量上限。

个人资料列表仅在集合不存在时返回空列表；存储读取失败会上抛，界面提示重试，避免把故障显示成“暂无资料”。追加资料仅在同一来源内去重，相同文字可以分别属于不同资料；去重读取失败时停止写入。

### 高级查询引擎

个人备份读取接口 `read_user_data_for_backup(user_id)` 经 query 门面读取该用户集合的原始 `ids / metadatas / documents`，不读取向量、公共集合或配置，不初始化 RAGSystem、嵌入模型或 LLM。不存在的向量库目录或个人集合返回空列表；存储读取故障记录不含正文的日志并上抛，不能视为空资料。读取与本进程写入互斥；不承诺跨进程事务快照。返回的元数据是内部原始资料，导出服务仍须按白名单筛选，不能直接序列化整个元数据。

```python
from campus_rag import RAGSystem, get_rag_response, rerank_nodes

rag = RAGSystem()
pub_idx = rag.get_public_index()
answer = get_rag_response("暑假有什么活动？", public_index=pub_idx, data_dir="campus_rag/data")
nodes = rerank_nodes("查询文本", nodes, top_n=10)
```

### 事件时间索引（截止日/发生时间查询）

事件读取接口严格区分“查询成功但无结果”和“事件库不可用”：`get_upcoming_events`、`get_upcoming_starts`、`get_notice_digest` 遇到存储或日期数据异常时记录日志并抛出稳定的 `EventQueryError`。启动期事件抽取仍为 best-effort；同步写入或删除失败必须向上传播，阻止版本推进。

事件同步复用 `sync_events_from_documents`：默认保持启动阶段的尽力抽取，`strict=True` 将失败向上传播，`replace_all=True` 强制严格处理并复用同一写入事务替换快照；删除同样通过现有入口的 `strict=True` 控制。

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

返回 `list[dict]`，每项含 `source / title / category / audience / publish_date / deadline / deadline_text / event_start / event_end / location / url`。事件同步已挂入 `add_public_documents` / `upsert_public_documents` / `replace_public_documents` / `delete_public_data` 与应用启动（`lifespan` 调 `sync_notice_events`），按内容哈希 + 抽取器版本（`EXTRACTOR_VERSION`，升级抽取逻辑后递增以触发旧记录自动重抽）幂等；启动期抽取失败只记日志；同步路径采用严格模式，失败后可重试恢复一致性。因不依赖嵌入，即使未配嵌入/LLM，事件查询仍可用。

抽取边界（评测可见 `scripts/eval_events.py`）：只抽日粒度；月粒度区间（“2026.9-2027.1”）、新闻式时间状语先行（“6月15日下午，…”）、网页表格转文本的跨行时间表（如选课阶段表）不在覆盖范围，由语义检索兜底。

### 追踪事件（今日面板用）

恢复话题使用公共接口 `create_restored_topic(username, name, backup_id, index)`，由当前用户、备份 SHA256 和话题序号派生稳定 UUID5，名称添加“（恢复）”。同一备份重试复用话题 ID 和现有名称，返回 `created` 标志；不覆盖原话题，不修改表结构。对话正文由服务层通过 LangGraph 官方 checkpoint API 写入仅含用户/助手文字的新话题，已有 checkpoint 则跳过。

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
| `index_manager.py` | `RAGSystem`：ChromaDB 集合管理、维度守卫、安全替换、MD5 去重 |
| `keyword_retriever.py` | `BM25Retriever`：rank_bm25 + jieba 分词（jieba 缺失时正则回退） |
| `query.py` | 检索门面：单例管理、检索出口统一附来源头、入库统一入口；空结果时 jieba 关键词缩减重试一次（检索自愈）；`reset_caches` 同时失效 query_engine 的检索器/BM25 缓存 |
| `query_engine.py` | RAG 管线：向量检索 → 空召回关键词重试 → BM25 候选并集排名融合 → 重排序 → LLM 生成 |
| `events.py` | 通知事件时间索引：确定性正则抽取截止日/发生时间（span·instant）/发布日/类别/适用对象/地点，存入 `events.db`（抽取器版本 `EXTRACTOR_VERSION` 控制旧记录自动重抽），供 `get_upcoming_events` / `get_upcoming_starts` 按时间查询（不依赖 LLM，离线可用） |
| `auth.py` | 话题 / 工具偏好 / 追踪事件 CRUD（SQLite，锚定项目根 `users.db`）。本地单用户形态，无登录函数 |
| `data/` | 校园通知 `.txt` 源数据（公共索引可从这里全量重建）。统一格式：文件名 `{通知ID}_{标题}.txt`，文档头三行 `来源：<URL>` / `标题：<标题>` / 空行，之后为正文（段间无空行，正文只含通知内容，无站点导航/页脚噪声）。主体由 `scripts/sync_ustc_columns.py` 采集（主站服务类通知、教务处教学/信息通知、研究生院通知、网络信息中心公告等）。当前共 323 篇：7 个为 git 跟踪的手写种子，其余为未跟踪文件（数据未加忽略规则，提交时自行 `git add campus_rag/data/`）。改动数据源后需重跑 `--reindex` 重建公共索引；`events.db` 会在启动时自动重抽 |

> 数据治理说明（2026-09）：语料做过一轮"格式清洗 + 去重"。格式清洗剥离站点导航/面包屑/发布元信息/版权页脚/相关文章列表与 HTML 空格残留，可随时用 `python scripts/clean_data_files.py`（幂等，支持 `--dry-run`）复跑；同一轮删除了 8 个分页列表帧、3 个跨来源镜像重复（保留对应原始通知）与 1 个抓取损坏残片，校验后语料为 323 篇。改动或补充 txt 后需对公共索引重跑 `--reindex`。

## 检索管线

```
用户问题
  ├── 向量检索 (ChromaDB: public + user_{id})
  ├── BM25 关键词检索（读取对应公共/个人集合的当前分块）
  ├── RRF 排名融合（保留不同来源）
  ├── 重排序 (qwen3-reranker，API 调用 /rerank 端点；不可用时保留融合排名，60 秒后重试)
  └── 返回带来源的片段；仅 *_answer 接口继续调用 LLM 生成回答
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
- **维度守卫**：公共或个人集合的向量维度与当前嵌入模型不一致时均保留数据并报错。查询不会因维度不匹配或缺少 URL 元数据删除集合；应恢复原嵌入模型，或备份后显式重建。
- **写路径安全**：个人更新、公共按来源更新和全量同步都先写新再删旧，不把模型初始化缓存当作网络可用性保证。集合维度变化需要单独处理，不通过全量同步删除集合来绕过。

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
# 输出配置、真值覆盖、逐字段 P/R 与偏差明细；调整抽取正则后重跑验证。
python scripts/eval_events.py
# 可选逐字段质量门槛（0–1，默认 0，仅强制完整覆盖）：
python scripts/eval_events.py --min-precision 0.8 --min-recall 0.8

# 检索评测：复用生产 search_keyword_nodes，默认 BM25 离线模式。
# 输出 Hit@K、MRR@10、各必需来源的 Recall@K、负例误召回率、分组指标与耗时。
# expect 每个子串代表一个必需来源；空列表表示库内无答案，检索报错独立记录。
# --hybrid 使用生产混合检索（需嵌入服务）；--vector 保留为其兼容别名。
# --no-rerank 可关闭混合检索重排序。日期/答案正确性需另行人工或模型审查，
# 不能由来源命中率推断；人工审查案例见 tests/answer_review_cases.json。
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --hybrid --no-rerank

# 快速冒烟（需嵌入/LLM API 可达）
python -c "from campus_rag import search_notices; print(search_notices('今年暑假有什么活动？'))"
python -c "from campus_rag import search_notices_answer; print(search_notices_answer('今年暑假有什么活动？'))"
```

嵌入或 LLM 不可用时，依赖网络的用例会自动跳过（不视为失败）。

事件评测只读语料，不连接数据库或调用模型。`--truth`、`--data-dir` 可指定独立真值与语料，`--today YYYY-MM-DD` 可指定抽取参考日期（默认 `2026-08-15`）；报告记录这些配置以便复现。真值中的每篇通知必须有非空语料，缺失/空白文档逐项列出，无真值语料单独报告并跳过。覆盖不完整时只报告已匹配样本指标，不能作为完整基线；不应通过删减真值掩盖缺失。

字段值错误 `MM` 同时计入精度和召回的分母：`P = TP / (TP + FP + MM)`，`R = TP / (TP + FN + MM)`；分母为零按 1 计，空字段双方一致计为 `OK`，不增加 `TP`。门槛针对每个字段独立检查。退出码 `0` 表示覆盖完整且达到指定门槛，`1` 表示缺失样本、零匹配或质量未达标，`2` 表示输入/参数无效。默认不设抽取质量下限，因此默认成功不代表抽取全部正确。离线守护测试：`python -m pytest tests/test_event_evaluation.py -q`，指标测试使用临时语料，另有覆盖测试只读核对仓库真值样本是否存在且非空，不访问数据库。

2026-09-17 事件基线：经来源 URL 和正文核对，将 10 个旧真值文件名对齐现有 `ID_标题.txt` 命名，全部预期字段保持不变，覆盖恢复至 17/17（100%）。在参考日期 `2026-08-15` 下，六字段精度均为 100%；`category`、`publish_date`、`event_end` 召回为 100%，`deadline` 为 83.3%（5/6），`event_start` 为 85.7%（6/7），`location` 为 88.9%（8/9）。仍有三处漏抽：本科选课通知的跨行表格截止日，以及毕业思政课新闻的活动日期和地点；保留这些真值暴露现有解析边界，不以修改预期值制造成功。默认门槛退出 0 不代表无偏差。

2026-09-13 本轮离线 BM25 基线：41 题（38 正例、3 无答案负例），Hit@1 为 84.2%，Hit@5/Recall@5 均为 100%，MRR@10 为 0.902；3 个负例中 2 个仍返回候选。该小样本结果只衡量当前语料的来源召回，不能证明最终回答准确率，也不能代表在线混合检索。新增负例揭示了常见词/错误年份仍会召回资料的边界，需用答案审查案例继续验证模型是否正确说明证据不足。

检索集现有 56 题，开发集 49 题、固定留出集 7 题；未标注 `split` 的题目归开发集，留出按问题划分，并非来源隔离。`tests/answer_review_cases.json` 现有 15 条人工答案审查用例，涵盖年份、人群、跨来源对比、附件和二维码目标缺失；这些是审查标准，不表示已验证真实模型回答。

```powershell
# 在项目根目录执行；审计不初始化检索或调用服务。
.venv/Scripts/python.exe scripts/eval_retrieval.py --audit-only
.venv/Scripts/python.exe scripts/eval_retrieval.py --split development --output tests/retrieval_baseline_development.json
# 开发调参完成后再评估留出集，输出需使用尚不存在的新文件。
.venv/Scripts/python.exe scripts/eval_retrieval.py --split holdout --output tests/retrieval_baseline_holdout.json
```

脚本先检查必需来源有非空文本，缺失时返回 2 并阻止检索。JSON 记录模式、分组、Python 版本、语料/真值 SHA256、建索引及逐题耗时、实际来源、错误和分类指标；拒绝覆盖已有报告，后续运行请更换结果文件名。离线模式不使用生成模型；混合模式的嵌入/重排序配置未记录，需另行核对，且本地文本覆盖审计不证明向量库已经同步。检索错误返回 1；正常完成不代表每题都正确或达到任何质量门槛。回归：`python -m pytest tests/test_retrieval_evaluation.py -q`。

2026-09-17 开发集离线 BM25 基线保存在 `tests/retrieval_baseline_development.json`：49 题（45 正例、4 负例），来源缺失 0、检索错误 0；Hit@1 为 86.7%，Recall@1 为 84.4%，Hit@5/Recall@5 均为 100%，MRR@10 为 0.917；4 个负例中 3 个仍召回候选。留出集仅做来源审计，尚未执行查询；未调用真实生成模型。旧基线与本次题集不同，不应将分数差异直接归因为检索质量提升。

## 统一检索管线

检索两路分别执行：向量服务或索引初始化失败（包括冷启动维度探测）时，从现有目标集合只读加载分块执行 BM25；关键词读取或检索失败时保留向量结果。单路失败会在返回文字中标明降级，即使剩余一路没有命中也保留说明；两路均失败则明确报错，不显示为空资料。降级不创建、修改或删除集合，不放宽入库维度检查。个人检索始终只读取指定用户集合。

`retrieve_notice_nodes` / `retrieve_user_nodes` 提供同管线节点结果，支持 `top_k`、`rerank` 和可选 `warnings: list[str]`；调用方应展示收集到的降级说明。关键词降级首次读取整个已有集合，不依赖嵌入服务；缺失集合视为空语料，存储读取错误继续报告失败。

`search_keyword_nodes(query, *, user_id=None, data_dir=None, top_k=10)` 复用生产 BM25，默认只读公共集合，指定 `user_id` 时只读该用户集合；评测可显式传入 `data_dir` 使用同一加载、切块、分词和匹配规则。个人集合与语料目录不能同时指定。

`create_keyword_search(*, user_id=None, data_dir=None)` 返回同一只读快照的可复用查询函数（参数 `query, top_k=10`），供离线批量评测只建一次索引；语料变化后须重新创建。评测单独报告建索引耗时，不将重复建索引成本混入每题热查询时间。

已确认的实现约定：Agent 检索工具只返回带来源的片段，由 Agent 生成最终回答；保留 `*_answer` 接口供独立调用。公共与个人检索共用向量召回、BM25 排名融合及可选重排序。

BM25 从当前 ChromaDB 集合读取分块，保留节点身份、来源和链接。写入前后均使关键词缓存失效（包括失败路径）；缓存最多保留 64 个索引。跨进程修改需重置缓存或重启；与写入重叠的请求不保证事务快照。

两路候选取并集，按 `sum(1 / (60 + rank))` 融合，rank 从 1 开始，避免直接比较不同尺度的分数。算法参考 [Elastic RRF 文档](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)。空查询和无关键词匹配不会产生 BM25 噪声结果。

验证关注来源保留、删除/等量替换后的缓存一致性、失败降级以及工具内部 LLM 调用次数；实际首字时间、总耗时及端到端质量需要在线模型评测。

本轮对抗性回归位于 `tests/test_integrity_regressions.py`，新增代码集中在共享召回、缓存失效和重排序响应校验，以及对应的故障测试；未增加新模块。关键词缓存首次构建需要读取并分词整个集合，后续查询复用；大语料的内存与冷启动耗时仍需专项测量。纯搜索现在也可能调用已配置的重排序服务，其耗时不能等同于纯本地检索。
`backup_document_matches(source, content, chunks)` 使用入库相同的分块规则核对恢复副本完整性，包含重叠片段与序号检查，不初始化嵌入服务或 LLM。
`group_user_document_chunks(data)` 为资料列表和备份共用原文合并入口：按父文档与字符坐标消除经过正文核对的重叠，保留不同文档和不同位置的重复文字；缺坐标、坐标冲突时保守保留片段，无法恢复分块时已丢弃的原始空白，不宣称字节级还原。个人资料去重以来源及整份文档的分块序列为依据，同时处理批内重复，不丢弃不同文档共享的片段。
