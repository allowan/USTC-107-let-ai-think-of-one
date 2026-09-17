# server — FastAPI 后端

校历仅支持上传 UTF-8 iCalendar（`.ics`/`.ical`）。当前支持全天、非重复事件，教学周标题如“秋季学期第一周”或“春季学期第2教学周”；不支持的定时、重复规则与 DURATION 事件明确报错。展开折行、按排他 DTEND 展开多日休假，周日起点转换为周一；同日备注合并，停课与补课冲突时拒绝导入。仅选择提交的 semester，跨年秋季按首周年份命名。

主服务（端口 8000）：路由/服务分层架构，SSE 流式对话，本地单用户（无 JWT）。

## 架构分层

| 层 | 位置 | 职责 |
|---|---|---|
| 入口 | `server.py`（根目录）/ `server/main.py` | uvicorn 启动 shim，缺依赖时给出激活虚拟环境的指引 |
| 应用工厂 | `server/__init__.py` | `create_app()`：路由注册、CORS、前端静态文件挂载（`frontend/dist` 存在时） |
| 生命周期 | `server/lifespan.py` | 启动时先 best-effort 同步通知事件时间索引（`sync_notice_events`，纯正则不依赖嵌入），再初始化 ChatService（未配 LLM Key 时降级不阻断启动），关闭时收尾 agent 连接 |
| 依赖注入 | `server/deps.py` | `get_user()` 恒返回 `local_user`（本地单用户，无认证） |
| 路由 | `server/routes/` | 参数校验、调用 service、返回响应——禁止写业务逻辑 |
| 服务 | `server/services/` | 业务编排，委托 `campus_rag` / `main.py` |

### services

| 服务 | 职责 |
|---|---|
| `chat_service.py` | Agent 生命周期（默认/按用户缓存，跨天自动重建以刷新 prompt 中的当前日期）、SSE 事件流、话题删除时清理 checkpoint；工具消息失配时保留历史并提示失败；未配 LLM Key 时保持懒加载，课表/个人数据 API 不受影响 |
| `auth_service.py` | 话题 CRUD（委托 `campus_rag.auth`） |
| `rag_service.py` | 检索与个人数据管理（委托 `campus_rag.query`）；`get_digest()` 聚合“最近新通知 + 临近/进行中事件”（委托 `campus_rag.get_notice_digest`，基于 `events.db` 时间索引） |
| `schedule_service.py` | 本地结构化课表与校历存储（SQLite `schedule.db`，按用户+学期隔离，连接用完即关）；计算当前教学周、周日期范围和当日特殊安排；`current_semester()` 按今天日期推断当前学期（中科大三学期制，秋季跨年） |
| `academic_calendar.py` | 解析上传的 iCalendar 教学周、休假和补课安排，校验所选学期周次连续性 |
| `ustc_schedule.py` | 解析用户提供的教务课表 HTML/结构化 JSON（不接触账号密码与 Cookie） |
| `sync_service.py` | 从 Sync Server 拉取公共通知（增量优先、全量兜底），版本号持久化于 `data/sync_state.json` |
| `news_service.py` | 实时抓取五个校站首页头条（主站服务通知/教务处/网络信息中心/研究生院/图书馆），5 分钟内存缓存，抓取失败回退旧缓存并标记 stale/error；并发抓取，单站超时 12 秒 |
| `file_import.py` | 个人文件解析：上传的 TXT/Markdown/CSV/JSON/PDF/DOCX 提取为可编辑文本（不保存原文件；10 MB / 20 万字符上限；扫描版 PDF 提示先 OCR） |

## API 总览（端口 8000）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 轻量存活检查，仅返回 `status: ok`、`checks: {service: true}`，不构建 Agent、不请求模型或数据库 |
| POST | `/api/health/diagnostics` | 用户主动诊断 LLM / ChromaDB；会产生一次模型请求，线程池并行探测，最多等待 10 秒；失败或超时返回 `degraded` 和对应 `checks: false`。未结束的探测由后续请求复用，避免超时后反复创建后台任务；不返回底层异常或凭据 |
| GET | `/api/topics` | 话题列表 |
| POST | `/api/topics` | 创建话题 |
| PUT | `/api/topics/{id}` | 重命名话题 |
| DELETE | `/api/topics/{id}` | 删除话题及对话记录（含 checkpoint） |
| POST | `/api/topics/{id}/summarize` | 自动生成话题标题 |
| GET | `/api/topics/{id}/history` | 获取话题对话历史 |
| POST | `/api/chat/stream` | SSE 流式对话（`{"content","topic_id"}`），事件：`thinking` / `tool_use` / `token` / `error` / `done`；客户端断开连接（前端“停止生成”/切页）即中止模型生成 |
| GET | `/api/personal-data` | 列出个人数据（按来源聚合，按 `chunk_index` 还原顺序）；存储故障返回 503，不伪装空列表 |
| POST | `/api/personal-data` | 添加个人数据 |
| POST | `/api/personal-data/parse-file` | 解析上传文件（TXT/MD/CSV/JSON/PDF/DOCX）为文本供编辑后入库（仅限本地来源） |
| POST | `/api/personal-data/import-schedule` | 将已导入的本地课表写入个人知识库供检索（仅限本地来源） |
| GET | `/api/news?refresh=` | 五个校站首页头条聚合（实时抓取，5 分钟缓存；`refresh=true` 强制刷新） |
| PUT | `/api/personal-data/{source}` | 编辑个人数据 |
| DELETE | `/api/personal-data/{source}` | 删除个人数据 |
| GET | `/api/schedule` | 获取本地课表（可按学期筛选） |
| POST | `/api/schedule/preview` | 只读校验并预览结构化课表、覆盖范围与提醒（仅限本地来源） |
| POST | `/api/schedule/preview-ustc` | 只读解析并预览教务 HTML/JSON（仅限本地来源） |
| POST | `/api/schedule/import` | 用结构化数据替换指定学期课表（仅限本地来源） |
| POST | `/api/schedule/import-ustc` | 解析用户粘贴/导出的教务课表 HTML/JSON 并替换该学期（仅限本地来源） |
| GET | `/api/schedule/calendar?semester=&on_date=` | 获取校历；`on_date` 可选，返回教学周状态、周范围和当日特殊安排 |
| PUT | `/api/schedule/calendar` | 保存校历（第一周周一、1–30 周、最多 100 个特殊日期；仅限本地来源） |
| POST | `/api/schedule/calendar/import-ics` | multipart：file 为 iCalendar 文件，semester 为目标学期；10 MB 上限，仅限本地来源 |
| GET | `/api/schedule/reminders` | 按当前校历周次合并课表，返回今日/明日课程及特殊安排 |
| GET | `/api/search/notices?q=` | 搜索公共通知（纯检索，不经 LLM） |
| GET | `/api/search/my-data?q=` | 搜索个人数据（纯检索，不经 LLM） |
| GET | `/api/digest?days=7` | 校园信息摘要：最近新通知 + 临近截止/进行中与即将开始事件（基于 `events.db`，不依赖嵌入/LLM；days 0–365） |
| GET | `/api/digest/tracked` | 列出用户追踪的事件（今日面板顶部固定展示） |
| POST | `/api/digest/tracked` | 追踪一条事件（body：`source` 必填 + `title/category/date_kind(deadline|start)/date_value/url`） |
| DELETE | `/api/digest/tracked/{source}` | 取消追踪（未追踪返回 404） |
| GET | `/api/settings` | 获取 LLM 配置 |
| PUT | `/api/settings` | 更新 API Key / Base URL（忽略空值，原子写回） |
| POST | `/api/settings/model` | 按分组切换模型 |
| GET | `/api/settings/tools` | 获取 Agent 工具开关状态 |
| PUT | `/api/settings/tools` | 更新工具开关 |
| GET | `/api/sync/status` | 本地/远程版本差异 |
| POST | `/api/sync/now` | 立即触发同步 |

交互式文档：`http://localhost:8000/api/docs`。

> `python server.py` 默认关闭热重载。新增或修改路由后必须重启后端；否则旧进程的路由表不会变化，
> 前端请求新路径可能返回 `405 Method Not Allowed`。开发期间可改用
> `uvicorn server:app --reload --port 8000`。

## 关键约定

- **回答证据**：沿用 `astream(stream_mode="messages")`，从成功工具消息的 `artifact` 发出 `evidence` SSE 事件（content 为 `{evidence: [...], warnings: [...]}`）。卡片字段为 `id/source/title/url/published_at/excerpt/kind`，类别区分官方、个人、公开网页及学生评价。仅转发白名单字段和 HTTP(S) 链接，每轮最多 40 个片段，每片段最多 2000 字。卡片表示本轮实际检索资料，并不宣称模型每句话均已核验；降级说明单独展示。工具 artifact 由现有 checkpoint 保存，历史接口在对应助手回合返回相同可选字段；无 artifact 的旧历史保持兼容，不迁移数据库，文字备份仍只包含可见正文。
- **回答核对**：Agent 提示词要求核对证据年份、学期和适用人群，区分发布/开始/截止日期；无相符证据时说明不足，冲突来源并列给出。此约束仍需用 `tests/answer_review_cases.json` 审查真实回答，来源命中测试不能代替答案正确性测试。

- **thread_id 契约**：`user-{username}-topic-{topic_id}`，话题删除 / 历史加载 / 对话写入三处共用，`tests/test_server_api.py::TestThreadIdContract` 守护。
- **话题删除顺序**：先删除 checkpoint，再删除话题元数据；checkpoint 清理失败时返回 503 并保留可见话题，避免接口报告成功后留下无法访问的私人历史。清理操作可重复执行，元数据删除失败时再次删除即可收敛。
- **路径参数禁止二次解码**：starlette 路由层已自动解码一次，路由内再 `unquote()` 会损坏字面含 `%` 的参数。
- **阻塞调用进线程池**：检索/入库含嵌入 API 调用，`async` 路由中一律 `asyncio.to_thread`；同步长任务同理（见 `sync_service.sync`）。
- **SSE 历史保护**：检测到 checkpoint 中 tool_calls 与 tool messages 不匹配时停止本次生成并明确提示历史已保留，不自动删除或重试，不回显原始异常内容。用户可先备份该话题并新建话题继续，原话题的工具记录需要另行核对修复。
- **设置变更失效链**：更新配置/切换模型 → `clear_agent_cache()`（含默认 agent）；更新工具开关 → 仅失效该用户 agent。
- **连接生命周期**：缓存失效后旧 Agent 的连接延迟到使用它的流结束再关闭；构建期间发生设置变更时，丢弃旧配置构建结果并重试。同一话题的并发生成被拒绝，避免 checkpoint 相互覆盖。
- **同步一致性**：同一进程串行执行同步；按来源替换更新通知，成功后原子写回版本号。请求取消时等待已启动的同步任务收尾，避免后台写入与下一次同步交错。
- **课表写入口仅限本地来源**：`/api/schedule/import*`、`PUT /api/schedule/calendar` 与 `/api/personal-data/import-schedule` 统一经 `ensure_local_origin` 校验 Origin（无 Origin 或 localhost/127.0.0.1 才放行）。
- **校历边界**：第一周必须从周一开始；特殊日期必须落在教学周范围内，同一天仅允许一项；调课/补课必须指定所依据的课程星期。未配置校历时课表查询明确降级为全部周次，不推测当前周。
- **iCalendar 导入**：原始文件不落盘，不执行文件中的链接或附件；重复导入保留已保存学期。校正接口中首周日期和周数可省略，沿用已保存值。
- **课程提醒合并规则**：今日与明日分别按实际校历日期选择学期（重叠时采用最近开始的学期），无覆盖校历才回退月份推测；再定位教学周并按课程 `weeks` 和星期筛选；节假日/停课清空当日课程，调课/补课改用指定星期课程。今日页面读取该结果，不重复实现日期算法。
- **追踪事件存 `users.db`**：`tracked_events` 表（username+source 主键，重复追踪即更新），CRUD 在 `campus_rag/auth.py`，与话题/工具偏好同库。
- **事件窗口语义**：`get_notice_digest` 的 upcoming 合并两类——`deadline` 型（`event_start <= end 且 deadline >= today`）与 `start` 型（时间窗相交：`event_start <= window_end 且 COALESCE(event_end, event_start) >= today`）。后者会把“已开始未结束”的展览/施工带出来并标记 `ongoing=true`，前端据此显示“进行中”而非负数剩余天数。
- **事件失败语义**：事件库查询失败必须向 `/api/digest` 返回稳定的 503，Agent 工具提示“事件数据暂时不可用”，不得伪装成“没有即将发生的事件”。空列表只表示查询成功且确实无数据。追踪 CRUD 全部进入线程池；来源、标题、类别、日期和 URL 在写库前校验长度与格式，日期统一保存为 `YYYY-MM-DD`。
- **聊天错误脱敏**：普通模型或工具链异常只向 SSE 返回稳定错误文案，日志记录异常类型和 thread 标识，不记录供应商异常正文，避免请求内容或凭据随异常泄露。checkpoint 工具消息失配继续使用专门的历史保留提示。
- **相对时间解析**：`main.py` 构建 agent 时在 system prompt 注入当天日期与三学期制映射（仅作无校历时的回退）；`get_my_schedule` 与今日/明日提醒统一调用 `ScheduleService.resolve_semester()`，优先选择覆盖所查日期且最近开始的本用户校历，无覆盖才按月份推断。未导入所选学期时明确报告已导入学期列表，不返回其他学期课表；显式指定学期仍按用户选择查询。

## 对话执行预算

每次 SSE 请求的处理预算为 180 秒（含 Agent 初始化与工具等待），最多 6 次模型调用、12 次工具调用，并以 40 个图执行步骤兜底。工具超额后返回工具错误供模型收尾；模型次数、图步数或总时限耗尽时发送明确的 `error`，不发送成功 `done`、不自动重新提交。已收到的文字和已有 checkpoint 保留；超时发生在工具执行中时，不能保证已经开始的同步 I/O 或写入已撤销，用户应先核对结果。预算仅限制当前请求，不限制话题一生的调用次数，不变更 checkpoint 存储路径或数据库结构。

模型 HTTP 请求使用 45 秒超时、最多 1 次 SDK 重试；该超时不能替代整个对话的总预算。离线回归：`python -m pytest tests/test_chat.py tests/test_chat_limits.py tests/test_chat_evidence.py -q`。

## 课表导入校验

所有课表替换（结构化 API、教务 HTML/JSON、Agent 工具）在服务层完整校验后才进入写入事务；任何一项失败都保留指定用户、学期的原课表。校验要求学期和课程名非空、星期为 1–7 整数、节次为 1–13 整数并严格升序且不重复、周次为正整数；兼容纯数字字符串，拒绝布尔值、小数和非法字符。钟点时间必须成对提供，使用 HH:MM 且结束晚于开始。空节次、无安排课程和只有钟点时间的安排仍可导入。

`validate_schedule_import()` 返回带课程序号、名称及安排序号的全部问题，不修改输入或写库。校验失败的导入 API 返回 HTTP 400，`detail.message` 提示原有课表未修改，`detail.errors` 提供错误列表；请求结构错误仍由参数层返回 422。JSON 解析保留原始安排值，不再静默过滤错误节次、周次或星期。旧异常记录不自动迁移，仍可查看并重新导入修正。

独立预览接口 `POST /api/schedule/preview` 和 `POST /api/schedule/preview-ustc` 只解析、校验并查询覆盖范围，不修改课表或校历；原导入接口继续只负责保存。旧后端不识别新增预览路径时返回 404/405，不会误执行写入。预览成功返回 `{payload: {semester, courses}, course_count, meeting_count, existing_meeting_count, errors, warnings}`。服务校验问题通过 HTTP 200 的 `errors` 展示，无法解析或请求结构错误仍返回 400/422；预览也必须符合本地来源限制。

无错误的预览 payload 可直接提交 `/api/schedule/import` 确认保存，保存时重新校验。数字字符串转为整数，节次端点展开为与存储一致的连续范围，周次去重排序；不修复非法值。预览提示缺少星期/节次、缺少周次及重复课程安排，重复识别包含教师，重复记录仍保留。`meeting_count` 为预计存储记录数（无安排课程计一条待定记录），`existing_meeting_count` 只统计当前用户目标学期即将被替换的记录。

已保存的结构化 `weeks` 是查询与展示的权威来源，`raw_schedule` 仅作追溯，不在读取时重解析覆盖周次；旧错误记录需要重新导入修复，不自动修改数据库。未提供钟点时间但节次命中现有内置默认表时，预览明确显示该默认时间并提示核对，确认保存后与课表查询一致。

## 个人文字备份

`GET /api/backup/catalog` 列出可选话题与资料；`POST /api/backup/export` 接收 `topic_ids`、`document_ids`，下载版本 1 的 JSON 备份（最大20 MB）。范围只有话题名、user/assistant可见文字和个人资料分块按顺序拼接的文字，不导出配置、原始数据库、内部工具状态、向量、公共通知或原始PDF/Word附件。选中内容读取失败则整体失败，不生成残缺备份；资料服务失败仍可单独备份对话。

备份服务按固定字段白名单构造结果。配置和环境中的密钥值只用于内存脱敏匹配，不序列化；正文中的常见令牌、密钥赋值和私钥块也会替换。任意未标识的私人文本不能保证自动识别，用户仍需核对所选内容。文件含格式版本、生成时间和 SHA-256 完整性校验。导出不调用模型/嵌入服务；对话读取使用只读 SQLite 快照及 LangGraph 公共接口，不更改原 checkpoint 文件或结构。

## 测试

备份恢复通过 `POST /api/backup/preview` 上传文件预览，再调用 `POST /api/backup/restore` 上传同一文件并提交 `confirmed_checksum`。仅接受版本1字段白名单，校验文件大小（20 MB）、重复字段、版本、角色和SHA-256；预览和校验失败均不写业务数据，校验和用于损坏检测，不作为身份认证。

恢复只创建新副本：话题ID由当前用户、备份校验和和序号派生，使用LangGraph官方API写入纯文本，已有checkpoint跳过；资料追加恢复标识作为新来源，通过 `campus_rag.query` 重新入库，已有恢复来源仅在全部分块与预期一致时跳过；残留片段或已修改副本报告失败并保留原样，需要用户核对。正文再次脱敏。不改原话题、资料或数据库结构，不执行原数据库文件替换，因此不需要覆盖前备份。逐项返回 restored/skipped/failed，部分失败允许重试；不宣称跨 SQLite/Chroma 的整体事务。个人资料需要嵌入服务，对话无需LLM。已配置密钥不导出、不恢复，原始附件不在范围内。

备份回归：`pytest tests/test_backup.py tests/test_backup_sources.py tests/test_backup_restore.py -q`，使用替身或临时数据库，覆盖恢复后继续对话及重复恢复。

教务课表导入支持多段周次（如 `1~7,9~11周`）、分段单双周（如 `5~7(单),16周`），钟点范围保留为准确时间而非节次。旧版已存错误记录须重新导入原课表，不自动迁移用户数据库。

```bash
pytest tests/test_server_api.py -v   # 路由契约/编码往返/状态机，离线可运行（RAG 用 stub）
```


### Agent 检索调用

校园通知与个人数据工具统一返回混合检索后的原文片段、来源和链接，由 Agent 组织回答。保留普通工具和 raw 工具的名称以兼容已有偏好，两者使用相同检索管线，同一查询无需重复调用。工具内部不再额外调用总结 LLM；Agent 的规划、多跳查询仍可能产生多次模型调用。搜索接口同样使用该纯检索管线；SSE 协议不变。
- 资料更新/删除与取消事件追踪将来源作为完整标识处理，支持名称中的斜杠及 URL；路径仅解码一次，保留字面 `%2F`。回归：`pytest tests/test_adversarial_api.py -q`。
- 本地单用户访问边界：启动器仅监听 `127.0.0.1`，HTTP 请求的 Host 与浏览器 Origin 必须精确匹配 localhost、127.0.0.1 或 IPv6 回环地址；拒绝伪装域名与外站请求。无 Origin 的本机命令行请求仍可使用，不增加登录或修改密钥配置。
- 教务周次解析在展开范围前检查单条安排的累计数量（最多 1000 项），拒绝超大范围，防止小输入导致巨量内存分配；保留正常间断周和单双周。
- 个人资料列表与备份共用原文坐标合并，避免重叠片段在编辑/导出时累积重复；无坐标的旧资料保留原拼接。仅新增公共合并入口与回归测试，不迁移存储或修改真实资料。
