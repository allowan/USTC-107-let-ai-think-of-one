# sync_server — 公共通知同步服务端

独立进程（端口 8001），向客户端分发公共通知，支持版本号增量同步。主服务不依赖它：未启动时客户端同步页显示离线，其余功能不受影响。

## 结构

| 位置 | 职责 |
|---|---|
| `main.py` | FastAPI 入口（端口 8001） |
| `database.py` | SQLite 存储 + 全局版本号管理 |
| `deps.py` | 管理端点的 admin token 依赖 |
| `routes/sync.py` | 客户端同步端点（公开） |
| `routes/admin.py` | 通知管理端点（需 admin token） |
| `services/` | 通知管理与同步数据逻辑 |
| `static/admin.html` | 管理后台页面 |
| `data/` | 通知 `.txt` 源文件目录 |

## API

### 客户端同步（公开）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/sync/version` | 当前版本号 |
| GET | `/api/sync/changes?since=` | 增量变更（upsert + deleted_sources） |
| GET | `/api/sync/full` | 全量文档 |

### 管理后台（需 admin token）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/notices` | 通知列表 |
| POST | `/api/admin/notices` | 添加通知 |
| GET | `/api/admin/notices/{source}/content` | 获取通知原文 |
| PUT | `/api/admin/notices/{source}` | 编辑通知 |
| DELETE | `/api/admin/notices/{source}` | 删除通知 |
| GET | `/api/admin/stats` | 系统统计 |
| GET | `/admin` | 管理后台 HTML 页面 |

## 配置与启动

```bash
# 配置（可选）：sync_server/settings.json（端口、admin token 等）
cd sync_server && python main.py
```

客户端地址由主服务的环境变量 `SYNC_SERVER_URL` 指定（默认 `http://127.0.0.1:8001`）。

## 同步流程（客户端视角）

```
客户端 /api/sync/now
  → 查询远程版本号（离线即报错返回）
  → 本地版本落后且有本地版本 → 拉增量 /changes?since=
  → 增量不可用或强制 → 拉全量 /full（先写新分块，成功后移除旧分块）
  → 成功后原子持久化本地版本号（data/sync_state.json）
```

增量结果按来源折叠为最后一次有效更新，保留删除标记以兼容已有客户端；客户端对同批删除后重建的来源直接安全替换。版本号和文档/变更在同一个 SQLite 读事务中读取，保证对应同一快照。同步路由使用线程池执行数据库访问，不阻塞事件循环。
