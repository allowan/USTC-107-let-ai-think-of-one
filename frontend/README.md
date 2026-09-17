# frontend — React 前端

校历入口仅接受用户选择的 `.ics`/`.ical` 文件，提交当前课表学期，不依赖本地固定路径；失败显示后端具体原因。保留可选首周日期与教学周数校正。

React 18 + Vite 6 + TypeScript 5 + Ant Design + Zustand 的单页应用，通过 Vite 代理（开发）或后端静态挂载（生产）访问后端 `/api`。

## 页面与组件

| 位置 | 职责 |
|---|---|
| `pages/DigestPage.tsx` | 今日面板（默认首页 `/today`）：校历驱动的今日/明日课程提醒 + 我追踪的事件 + 即将截止/进行中与即将开始 + 最近发布 |
| `pages/NewsPage.tsx` | 最新消息（`/news`）：实时抓取五个校站首页头条（主站服务通知/教务处/网络信息中心/研究生院/图书馆），按发布时间排序，来源状态（ok/stale/error）展示，手动刷新 |
| `pages/ChatPage.tsx` | SSE 流式对话（fetch + ReadableStream 解析）、Markdown 渲染（GFM 表格、带 favicon 的链接）、生成中可点“停止生成”中止流、首轮对话自动摘要生成话题标题 |
| `pages/PersonalDataPage.tsx` | 个人知识库管理（按来源聚合、增删改、将已导入课表同步进个人数据） |
| `pages/SchedulePage.tsx` | 校历驱动的本地课表周视图：默认当前教学周、手动周次切换、今日/明日课程和特殊日期提醒；未配置校历时显示全部周次 |
| `pages/SyncPage.tsx` | 公共通知同步状态与手动触发 |
| `components/Schedule/UstcScheduleImportModal.tsx` | 粘贴/上传教务课表 HTML、JSON 并导入 |
| `components/Schedule/ScheduleImportPreviewModal.tsx` | 两个导入入口共用：课程预览、校验问题、缺失信息提示与同学期覆盖确认 |
| `components/Schedule/AcademicCalendarModal.tsx` | iCalendar 文件导入；已有校历不覆盖；首周日期、教学周数和特殊安排校正 |
| `components/Schedule/ImportExistingScheduleModal.tsx` | 从已导入的学期中选择并同步到个人知识库 |
| `components/Layout/AppLayout.tsx` | 侧边栏（菜单 + 话题列表：重命名/删除）+ 顶栏；后端离线时错误提示可点击重试 |
| `components/Layout/SettingsModal.tsx` | 全局设置（API Key/Base URL/模型切换）与工具开关 |
| `services/api.ts` | axios 封装（baseURL `/api`，全量同步关闭超时）；含 digest 摘要与 tracked 追踪两组接口 |
| `stores/topicStore.ts` | Zustand 话题状态（列表、激活话题、加载/错误态） |
| `utils/markdownLinks.ts` | 裸链接渲染辅助：把中文标点等尾随符号移出链接 |
| `types/index.ts` | 前后端契约的 TypeScript 类型 |

## SSE 协议（与 `POST /api/chat/stream` 对应）

每行 `data: {"type": ..., "content": ...}`，type 取值：

| type | 含义 |
|---|---|
| `thinking` | 开始思考（占位状态） |
| `tool_use` | Agent 调用了某个工具（显示工具名） |
| `token` | 回答正文增量，追加进当前 assistant 气泡 |
| `evidence` | 本轮工具实际返回的证据片段与降级说明，合并进当前助手回合；不解析模型回答生成来源 |
| `error` | 处理失败，渲染为错误气泡 |
| `done` | 流结束 |

前端解析约定：按换行解析 `data: ` JSON；只有收到 `done` 或明确的 `error` 才视为服务端已结束处理。提前 EOF 会保留已收到的文字并提示回答可能不完整，不自动重发；切换话题或组件卸载时主动 `abort`。回答中的 Markdown 由 `react-markdown` + `remark-gfm` 渲染（表格包裹在 `.chat-markdown-table` 横向滚动容器中，样式见 `index.css`）。“停止生成”按钮通过 `AbortController` 中止 fetch，后端检测到客户端断开即停止模型生成。

进入或切换话题时，历史加载成功后才允许发送（包括 Enter）。加载失败显示重新加载入口并保留草稿；旧话题的迟到响应不会替换新话题历史。离线交互回归：`node --test tests/test_chat_frontend.cjs`（项目根目录）。

助手回合可展开“本轮检索资料”，核对标题、来源、发布日期、最多 2000 字的原文片段及原文链接；官方通知、个人资料、网页和学生评价分别标注。未提供日期显示“发布日期未知”。这些资料是工具实际返回的证据，不代表逐句核验；旧话题没有证据时不补造卡片。工具失败不生成证据，降级信息即使无命中也展示。

## 开发命令

```bash
npm install
npm run dev        # 开发（端口 3000，/api 代理到 127.0.0.1:8000）
npm run test:chat   # 历史、断流与证据卡片
npm run test:sync   # 同步状态失败与重试
npm run test:calendar # 日历转义、日期与确认下载
npx tsc --noEmit   # 类型检查
npm run build      # 生产构建到 dist/（后端检测到 dist/ 会静态挂载到 /）
```

## 注意事项

- 今日面板“导出追踪日历”先预览标题和日期，再下载所选事件的 `.ics` 文件；纯浏览器生成，不写服务端或自动订阅日历。仅导出有合法日期的追踪项为当天全天事件，不猜具体截止时刻、不设置自动提醒；源文件属于快照，日期变更需核对原文后重新导出。文本转义、UTF-8 折行与排他结束日期遵循 [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html)。最多一次 1000 项，重复来源去重，稳定 UID 不代表所有日历客户端都支持自动更新。
- 今日面板的通知、追踪、课程提醒独立加载和报错，单个区域失败或缓慢不会阻止其他区域展示。失败区域保留旧结果并提示可能过期；没有成功数据时不显示“暂无事件”。重试可恢复；切换时间范围或离开页面后，旧请求不会覆盖新结果。追踪状态未知或加载失败时暂禁追踪操作与日历导出。
- 追踪倒计时按本地日历日计算；当天显示“今天”，过去日期显示“已截止/已开始 N 天”，已知仍在持续的事件显示“进行中”，无效日期不生成倒计时。离线回归：`node --test tests/test_digest_frontend.cjs tests/test_calendar_frontend.cjs`（项目根目录）。
- 个人资料首次加载显示读取状态，只有成功返回空列表才显示“暂无个人数据”。请求失败持续展示原因与重试入口；已有资料保留但标为旧结果，刷新成功前暂停编辑/删除。刷新和离开页面后迟到的旧响应不会覆盖当前状态。回归：`node --test tests/test_personal_data_frontend.cjs`（项目根目录）。
- 设置中的“连接诊断”仅在点击后请求 LLM 与资料库探测，会发起一次模型请求；健康检查只表示本地 HTTP 服务可达，不表示所有模型和资料功能可用。诊断失败保留错误与重试入口。

- 同步状态请求失败显示“状态获取失败”和重新获取入口；若已有成功快照，保留数据并标记为上次状态，禁止按过期状态发起同步。首次未取得状态显示“未知”，只有成功返回 `server_online=false` 才显示同步服务离线。

- “个人备份”（`/backup`）按勾选项导出对话和个人资料文字；不导出配置、原始数据库或原始附件。已配置密钥和可识别凭据在正文中脱敏，未标识的私人文本需自行核对。导出为含版本及完整性校验的 JSON，资料不可读时可单独选择对话重试。新增 `BackupPage` 集中承载备份操作，不混入模型设置。
- 同一页面支持选择备份→校验预览→确认恢复。恢复创建新副本，已有恢复副本跳过；失败项保留结果并可重试。资料重新入库需要当前嵌入服务，确认界面说明远程服务会接收文字；对话恢复不调用模型。恢复后刷新话题列表。前端交互回归：`npm run test:backup`。

- 两个课表导入入口均先请求独立的只读预览接口（`/api/schedule/preview`、`/api/schedule/preview-ustc`），再由用户确认保存；升级后须重启后端。预览显示学期、课程安排及将被替换的已有安排数量；校验错误禁止确认，缺失信息和重复安排给出提醒。返回修改或取消预览不会改动数据；教务导入保留输入内容供修正，文件导入可重新选择文件。保存失败保留预览供重试，保存时服务端再次完整校验。
- 课表文件导入会展示后端返回的课程和安排序号校验错误。CSV 支持引号、字段内逗号/换行、节次和周次范围（如 `1-3;5`），空值保持待定；非法数字、缺少课程名、列数不符和混合学期会明确拒绝，不静默丢弃。可选 `semester` 列指定学期，缺省沿用“导入课表”。文件大小上限为 5 MB。
- 课表导入前端回归检查：`npm run test:schedule`，覆盖 CSV 解析和导入错误展示，无需模型或后端服务。
- 课表每天固定 13 节：上午 1–5 节、下午 6–10 节、晚上 11–13 节。缺失或异常的星期、节次（越界、非整数、结束早于开始）不进入网格，保留在下方待核对列表并展示已有原始安排，避免异常数据撑大课表。
- 课表周次选择旁的“全部周次”显示所选学期全部安排；重叠安排并排显示。周次标注保留间断周，不将其误写为连续范围。
- 旧版导入曾截断多段周次、忽略单双周并误读钟点时间；升级后请重新导入受影响学期的教务课表（不是校历），仅刷新不会修复已存数据。
- PWA 由 `vite-plugin-pwa` 生成（`registerType: autoUpdate`）；manifest 由插件注入，不要在 `index.html` 手写 manifest link（会双 link 冲突）。
- 后端会静态挂载 `frontend/dist`（存在时）。**只改源码不重新 `npm run build` 的话，通过端口 8000 访问的仍是旧构建**——这是“新功能看不到”的最常见原因；开发调试请用 `npm run dev`（端口 3000）。
- 不要为 `/api/*` 配置 workbox runtimeCaching——NetworkFirst 会在后端恢复后回源陈旧缓存。
- useEffect 必须带完整依赖数组；组件卸载需清理异步副作用（abort/取消标志）。
- 课表底部待核对安排采用响应式卡片展示：数量汇总、星期/节次原因标签、课程信息分组；原始安排支持键盘展开查看，窄屏自动单列。
