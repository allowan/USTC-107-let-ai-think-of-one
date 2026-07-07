# USTC-107-let-ai-think-of-one

基于 RAG + Agent 的校园信息智能问答助手（中国科学技术大学"一〇七杯"智能体赛道参赛项目）。

## 功能特性

- **流式对话** — WebSocket 实时流式输出，支持 Markdown 渲染
- **RAG 检索** — 混合检索（向量 + BM25）+ 重排序，精准匹配校园通知
- **多用户隔离** — 每个用户独立的知识库和工作区
- **文件管理** — 工作区文件的上传、预览、删除
- **管理面板** — 用户管理、知识库文档管理、系统状态监控（管理员专属）

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

### 6. 启动前端

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
| `JWT_SECRET` | JWT 签名密钥 | `ustc-campus-ai-secret-2026` |
| `WORKSPACE_ROOT` | 文件工作区路径 | 项目根目录 `workspace/` |

## 默认账户

| 用户名 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 管理员 |

首次启动后端时自动创建。管理员登录后可访问"管理"面板（用户管理、知识库管理、系统状态）。

## 项目结构

```
USTC-107-let-ai-think-of-one/
├── server.py                  # FastAPI 后端入口（HTTP + WebSocket）
├── main.py                    # LangChain Agent 定义和系统提示
├── frontend/                  # React 18 前端
│   └── src/
│       ├── pages/             # 页面组件
│       │   ├── LoginPage.tsx   #   登录 / 注册
│       │   ├── ChatPage.tsx    #   流式对话（WebSocket + Markdown）
│       │   ├── FilesPage.tsx   #   文件管理
│       │   └── AdminPage.tsx   #   管理面板（三 Tab）
│       ├── components/        # 布局组件
│       ├── services/          # API 调用 + Axios 拦截器
│       ├── stores/            # Zustand 状态管理
│       └── types/             # TypeScript 类型定义
├── campus_rag/                # RAG 检索系统
│   ├── data/                  # 校园通知 .txt 数据文件
│   ├── auth.py                # 用户认证（SQLite + bcrypt）
│   ├── index_manager.py       # ChromaDB 索引（公共 + 用户隔离）
│   ├── query.py               # 轻量检索（Agent 工具用）
│   ├── query_engine.py        # 完整 RAG 管线（混合检索 + 重排序）
│   ├── data_loader.py         # 文档加载和 SentenceSplitter 切分
│   ├── keyword_retriever.py   # BM25 关键词检索（jieba 分词）
│   ├── ingest.py              # 运行时文档注入
│   ├── llm_factory.py         # LLM / Embedding 工厂
│   ├── config.py              # LlamaIndex 全局设置
│   ├── .env.example           # 嵌入配置模板
│   └── README.md              # RAG 模块文档
├── tools/                     # Agent 工具
│   ├── file_tool.py           # 11 个文件操作工具（沙箱化 workspace）
│   └── search.py              # 网页抓取工具
├── model/
│   └── config.py              # LLM 初始化（支持热切换模型）
├── tests/                     # 单元测试
├── settings.example.json      # LLM 配置模板（可提交）
├── workspace/                 # 用户文件存储（gitignore）
├── chroma_db/                 # ChromaDB 向量数据库（gitignore）
└── TEST_REPORT.md              # 测试报告
```

## API 总览

### 认证（无需登录）

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |
| GET | `/api/health` | 健康检查 |

### 对话（WebSocket）

| Path | 说明 |
|---|---|
| `/ws/chat?token=<jwt>` | 流式对话，收发 JSON：`{"type":"chat","content":"..."}` |

### 文件（需登录）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/files/list?path=` | 列出目录 |
| GET | `/api/files/read?path=` | 读取文件 |
| POST | `/api/files/write` | 写入文件 |
| DELETE | `/api/files/delete?path=` | 删除文件 |
| POST | `/api/files/upload` | 上传文件（UTF-8 文本） |

### 搜索（需登录）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/search/notices?q=` | 搜索公共通知 |
| GET | `/api/search/my-data?q=` | 搜索个人数据 |

### 管理（需管理员）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/users` | 用户列表（含索引大小） |
| DELETE | `/api/admin/users/{username}` | 删除用户及数据 |
| GET | `/api/admin/notices` | 知识库文档列表（按来源聚合） |
| POST | `/api/admin/notices` | 添加通知到知识库 |
| DELETE | `/api/admin/notices/{source}` | 按来源删除通知及所有分块 |
| GET | `/api/admin/stats` | 系统统计（用户数、文档数、Agent 状态） |

## 测试

### 后端测试

```bash
# 运行单元测试
pytest tests/ -v

# 手动测试 API
# 1. 健康检查
curl http://localhost:8000/api/health

# 2. 登录
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 3. 搜索（用返回的 token 替换）
curl "http://localhost:8000/api/search/notices?q=讲座" \
  -H "Authorization: Bearer <token>"

# 4. 管理员接口
curl "http://localhost:8000/api/admin/stats" \
  -H "Authorization: Bearer <admin_token>"
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
3. 启动前端：`cd frontend && npm run dev`
4. 浏览器打开 `http://localhost:3000`
5. 用 `admin` / `admin123` 登录
6. 测试对话：发送"有什么暑期学校的活动？"
7. 测试文件：上传/预览/删除 .txt 文件
8. 测试管理：侧边栏"管理" → 用户管理 / 知识库管理 / 系统状态

### 测试报告

详细测试记录见 [TEST_REPORT.md](./TEST_REPORT.md)。

## 已知注意事项

- **首次对话较慢**：Agent 和 RAG 索引采用懒加载，首次调用时需要初始化（约 5-10 秒）
- **嵌入模型**：本地 Ollama 的 `nomic-embed-text` 首次加载需几十秒；切换为云端嵌入可避免此问题
- **数据文件格式**：`campus_rag/data/` 下的通知文件必须以 `.txt` 结尾，否则会被跳过
- **文档分块**：每篇通知会被 `SentenceSplitter` 切分为多个 1024 字符的块，管理面板按文件名聚合显示
- **Windows 代理**：如果系统配置了 HTTP 代理，httpx 可能误用导致 Ollama 连接 502，`llm_factory.py` 已内置清除逻辑
- **ChromaDB 持久化**：向量数据存储在项目根目录的 `chroma_db/`，删除后重启服务会自动从 `data/` 重新索引

## 待实现

- [ ] 真正的 RAG Answer 模式（检索结果经 LLM 总结后再传给 Agent，而非原始文本）
- [ ] 对话历史持久化
- [ ] 用户个人信息修改
- [ ] 知识库文档在线编辑
- [ ] Docker 部署支持
