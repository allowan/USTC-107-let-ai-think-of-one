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
| `components/Schedule/UstcScheduleImportModal.tsx` | 粘贴/上传教务课表 HTML、JSON、CSV 并导入 |
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
| `error` | 处理失败，渲染为错误气泡 |
| `done` | 流结束 |

前端解析约定：逐行 `JSON.parse` 单独容错（坏行跳过不杀流）；流结束时 flush 解码器残余；切换话题或组件卸载时主动 `abort`。回答中的 Markdown 由 `react-markdown` + `remark-gfm` 渲染（表格包裹在 `.chat-markdown-table` 横向滚动容器中，样式见 `index.css`）。“停止生成”按钮通过 `AbortController` 中止 fetch，后端检测到客户端断开即停止模型生成。

## 开发命令

```bash
npm install
npm run dev        # 开发（端口 3000，/api 代理到 127.0.0.1:8000）
npx tsc --noEmit   # 类型检查
npm run build      # 生产构建到 dist/（后端检测到 dist/ 会静态挂载到 /）
```

## 注意事项

- 课表每天固定 13 节：上午 1–5 节、下午 6–10 节、晚上 11–13 节。缺失或异常的星期、节次（越界、非整数、结束早于开始）不进入网格，保留在下方待核对列表并展示已有原始安排，避免异常数据撑大课表。
- 课表周次选择旁的“全部周次”显示所选学期全部安排；重叠安排并排显示。周次标注保留间断周，不将其误写为连续范围。
- 旧版导入曾截断多段周次、忽略单双周并误读钟点时间；升级后请重新导入受影响学期的教务课表（不是校历），仅刷新不会修复已存数据。
- PWA 由 `vite-plugin-pwa` 生成（`registerType: autoUpdate`）；manifest 由插件注入，不要在 `index.html` 手写 manifest link（会双 link 冲突）。
- 后端会静态挂载 `frontend/dist`（存在时）。**只改源码不重新 `npm run build` 的话，通过端口 8000 访问的仍是旧构建**——这是“新功能看不到”的最常见原因；开发调试请用 `npm run dev`（端口 3000）。
- 不要为 `/api/*` 配置 workbox runtimeCaching——NetworkFirst 会在后端恢复后回源陈旧缓存。
- useEffect 必须带完整依赖数组；组件卸载需清理异步副作用（abort/取消标志）。
