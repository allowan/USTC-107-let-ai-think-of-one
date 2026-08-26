# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

本地单用户客户端：无登录、无用户系统，所有数据（对话历史、个人知识库、向量索引）保存在本机。

## 功能特性

- **多轮对话** — SSE 流式输出 + LangGraph 检查点持久化，支持 Markdown 渲染
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
# LLM 配置（API Key 必填）
cp settings.example.json settings.json   # 编辑填入 api_key

# 嵌入与重排序配置（校园网关，需校园网/VPN）
cp campus_rag/.env.example campus_rag/.env   # 编辑填入 EMBED_* / RERANK_* Key

# 联网搜索（可选）：在 campus_rag/.env 中配置 TAVILY_API_KEY，或设 WEBSEARCH_PROVIDER=ddg 免 Key
```

各配置项的完整说明见各模块 README：[LLM 配置](model/README.md)、[嵌入/重排序/联网搜索配置](campus_rag/README.md)。

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

### 4. 测试

```bash
pytest tests/ -v              # 后端单元测试（检索/LLM 相关用例需要对应 API 可达）
cd frontend && npx tsc --noEmit   # 前端类型检查
```

## 注意事项

- **首次对话较慢**：Agent 和 RAG 索引采用懒加载，首次调用需初始化（约 5-10 秒）
- **嵌入模型切换需重建向量库**：公共集合维度不匹配时会自动从 `campus_rag/data/` 重建；个人集合需重新导入
- **校园网关需校园网/VPN**：嵌入与重排序默认走 `api.llm.ustc.edu.cn`，非校园网环境不可达
- **配置分离**：LLM 配置在 `settings.json`，嵌入/重排序/联网搜索在 `campus_rag/.env`，请勿混写；环境变量优先级高于配置文件
- **密钥安全**：`settings.json`、`campus_rag/.env`、`users.db`、`chroma_db/`、`data/` 均已加入 `.gitignore`，禁止提交密钥
- **数据文件格式**：`campus_rag/data/` 下仅识别 `.txt` 文件；通知文件名前缀为通知 ID，用于源链接提取
- **Sync Server 可选**：未启动时同步功能显示离线，其余功能不受影响
- **DeepSeek V4 端点**：`deepseek-v4-*` 需 `/beta` 路径，`llm_factory.py` 检测到 `api.deepseek.com` 时自动补齐后缀
- **路径参数含 `%`**：个人数据来源（source）可含字面 `%`，前端已 `encodeURIComponent`，后端路由禁止二次解码

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

- [x] **联网搜索工具** — 已集成 Tavily / DuckDuckGo（`web_search` + `fetch_url` 两步配合）
- [ ] **知识图谱工具** — 基于 Neo4j 或 NetworkX 构建课程依赖、教师关系等结构化知识
- [ ] **邮件/通知推送工具** — Agent 代用户订阅关键词，匹配新通知时推送提醒
- [ ] **日程解析工具** — 从通知中提取时间、地点、事件，自动生成日历事件
- [ ] **图片/多模态支持** — 结合多模态 LLM 解析通知中的海报图片
