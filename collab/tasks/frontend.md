# 前端任务书（Claude）

FE-01~FE-07、DOC-01 已完成；**迭代 5 的 FE-08~FE-10 在文末。**

工作目录 `frontend/`，遵循 `frontend/AGENTS.md`。菜单种子已指向
`ticketflow/tickets/index` 和 `ticketflow/knowledge/index`，页面放在 `src/views/ticketflow/` 下。

## FE-01 工单 API 层与列表页

分支：`fe/ticket-list`

- `src/api/ticketflow/tickets.ts`：继承 `BaseApi`，补 `transition`、`assign`、`comments`、
  `timeline`、`aiMetadata`、`dashboard`。`create` 为每份待提交内容生成 `Idempotency-Key`：
  未成功的同一份内容重试（含重开弹窗）复用同一个键，成功后释放，超过服务端 24 小时保留期作废。
  键跟随内容而不是弹窗，因为改过内容再用旧键只会得到服务端 409。
- 列表页走 RePlusPage + 后端元数据：状态、优先级用标签渲染，`sla_state` 高亮
  （`DUE_SOON` 警告色、`OVERDUE` 危险色）。筛选项来自后端 `search-fields`，由 `TicketFilter`
  生成，已包含 `sla` 和 `q`，前端不需要重映射。
- 新建工单表单：标题、描述、分类、优先级。409 / 429 由 http 拦截器展示服务端 `detail`
  （429 走框架的限流策略），不另写文案。

## FE-02 工单详情（依赖 BE-02）

- 详情抽屉或独立页：基本信息、SLA 状态、可执行流转按钮（来自 `available_transitions`）。
- 指派：候选人来自 `/assignees`，提交带 `version`。
- 回复框：`viewer.can_comment_internal` 为真时可选内部备注。
- 时间线：首屏用详情里的第一页，滚动或翻页调用 `/timeline`。
- 任何写操作收到 409 时提示“工单已变更”，并重新加载详情。

## FE-03 知识库（依赖 BE-02）

- 列表、详情（Markdown 渲染必须经过净化，防 XSS）、新建与编辑、状态切换。
- 从已关闭工单转存：`viewer.can_archive` 为真时在工单详情显示入口，预填标题、正文和分类。

## FE-04 看板与导出

- 工单页顶部看板：按状态、优先级、SLA 计数，点击计数联动筛选。
- 异步导出：沿用底座下载中心。

## FE-05 词条、单测与 E2E

- zh / en 词条对称；API 层与格式函数补 vitest。
- E2E 冒烟：建单 → 接单 → 提交验收 → 确认关闭 → 转存草稿。
- 提交前跑 `frontend/AGENTS.md` 第六节的全部门禁。

## FE-06 认证接口与后端 HEAD 对齐

联调发现导入的 xadmin-client v5.0.2 落后于后端 HEAD。登录能力探测已在 FE-01 修复，剩余：

- 登录验证码：前端 `ReImageVerify` 用 `GET /api/identity/auth/captcha`，后端已改为独立的 captcha 应用，
  开启 `SECURITY_LOGIN_CAPTCHA_ENABLED` 后登录会失败。按后端 captcha 协议改造或从上游 xadmin-client 同步对应实现。
- `registerAuth`（`GET /api/identity/register`）无组件调用，确认后删除。
- 以后端 `openapi.json` 为准，对 `src/api` 再做一次全量比对（含 `BaseApi` 动态拼接的路径）。

## CI-02 CI 前端侧：assignees 消费与菜单词条

分支：`fe/ci-green`。

- `ticketApi.assignees(pk, q)` 对接 `GET /api/tickets/{id}/assignees`，消除 `check-menu-permissions` 报的无前端消费；补单测。
- `locales` 增加 `menus.ticketflow`、`menus.ticketflowTickets`、`menus.ticketflowKnowledge`（zh / en 对称），
  与 CI-01 改为 i18n key 的菜单标题配套。


## FE-07 工单 AI 面板（迭代 3，依赖 SV-02）

分支：`fe/ai-panel`。接口见 Phase 1 设计评审的 FastAPI 契约与 SV-02 完成报告。

- 开发代理：`vite.config.ts` 增加 `/ai` → `http://127.0.0.1:8897`（HTTP，不缓冲）。生产由 Nginx 转发，前端只用相对路径 `/ai/v1/...`。
- API 层 `src/api/ticketflow/ai.ts`：`analyze(ticketId)` 走 axios（`/ai/v1/tickets/analyze`，错误信封 `{code, error, detail}`，`code` 为 HTTP 状态码整数）；
  `streamReply(ticketId, handlers, signal)` 复用 `src/utils/sse.ts` 的 `postSse`，按 `meta` / `delta` / `done` / `error` / `ping` 分发。
  缺少 `done` 就结束的流按中断处理。
- 详情抽屉右侧 AI 面板，只在 `viewer.can_handle` 为真时显示：
  - **分析**：显示建议分类、优先级、摘要、标签，“一键采纳”调用 `POST /api/tickets/{id}/ai-metadata`，带分析结果里的 `ticket_version`；
    409 时提示工单已变更并重新加载详情，分析结果标记为过期。采纳后刷新详情。
  - **流式回复**：点“生成回复”逐帧追加正文，生成中可“停止”（AbortController），切换工单或关闭抽屉时自动取消；
    `done` 后可“填入回复框”，填入对外回复编辑区，发送仍由用户点击。`error` 帧显示 `detail`，`retryable` 时提供重试。
    显示引用的知识文章（`meta.references`）。
  - 401 走既有登录过期处理；403 / 404 / 429 / 503 / 504 显示服务端 `detail`。
- 单测：帧分发（含半帧、`ping`、缺 `done`、`error`）、采纳请求带版本、停止后不再追加正文。
- 词条 zh / en 对称；跑 `frontend/AGENTS.md` 第六节门禁。
- 联调：在 `:8848` 用 `tf_agent` 走通分析 → 采纳、生成 → 停止 → 重新生成 → 填入回复 → 发送；用 `tf_requester` 确认面板不出现。

## FE-05 E2E 冒烟（迭代 4，依赖 DP-01）

分支：`fe/e2e-smoke`

上游 E2E 编排（`scripts/e2e-run.mjs`）会在 `:18896` 自起一套后端，本机 Windows 无法直接使用。TicketFlow 冒烟改为针对**运行中的交付栈**：

- 新增 `playwright.ticketflow.config.ts`（无 `webServer`，`baseURL` 取 `TF_E2E_BASE_URL`，默认 `http://127.0.0.1:8080`），
  `e2e/ticketflow/*.e2e.ts`，口令从 `deploy/.accounts.local.json` 读取（文件不进 Git）。
- 主流程：提交人建单 → 客服接单 → 提交验收 → 提交人确认解决 → 客服转存知识库草稿；中途在 AI 面板分析、采纳、生成回复并填入发送。
- 用例幂等（唯一标题）、只用 chromium；`package.json` 增加 `test:e2e:ticketflow` 脚本。
- 词条 zh / en 对称、单测与门禁照旧。

## DOC-01 交付文档（迭代 4）

分支：`fe/docs`

- 根目录 `README.md` 重写：项目简介、架构图（Mermaid：网关、DRF、FastAPI、Celery、PG、Redis）、技术要点（面试复盘：并发与幂等、
  联合鉴权、可见的流式、查询优化与压测数据）、快速开始（指向 `deploy/README.md`）、多代理协作方式。
- 运维手册要点汇总到 `deploy/README.md` 的链接；压测数据引用 `docs/development/压测报告.md`。
- 迭代 4 验收说明 `docs/development/迭代4验收说明.md`。

---

# 迭代 5：遗留问题清零

## FE-08 工单详情跟进后端契约、AI 面板引用与人机校验收尾（依赖 BE-05、SV-03）

分支：`fe/viewer-fixes`

- `pnpm sync:contract` 同步 BE-05 的 `viewer.can_reply`。回复框的显示条件改为只看 `viewer.can_reply`，删掉
  `TicketDetail.vue` 里用 `submitter_id === 当前用户` 推断的逻辑。
- 指派区只按 `viewer.can_assign` 显示；BE-05 之后已关闭工单不再显示指派区。确认对已关闭工单指派返回 409
  时走现有“工单已变更”提示并重新加载。
- AI 面板：SV-03 把流式 `meta.references` 改成 `[{article_id, title}]`。`TicketAiPanel.vue` 显示引用文章标题列表，
  点击在知识库中打开对应文章，不再只显示“引用了 N 篇”。zh / en 词条对称。
- `ReHumanCheck`：组件卸载时（例如在 PoW 计算过程中路由跳走）调用 `cancel`，中止正在进行的 PoW，补单测。
- 联调环境验证：已关闭工单无指派区；提交人、处理人、无关用户三种身份下回复框的显示与后端一致；AI 面板显示引用标题。

## FE-09 E2E 健壮性

分支：`fe/e2e-hardening`。来自 FE-05 评审的不阻断建议：

- `e2e/ticketflow/support.ts` 的 `choose`：现在在所有可见下拉框里按文字取第一个选项，页面上同时展开过多个
  下拉框或有同名选项时会点错。改为定位当前 `el-select` 自己弹出的下拉层（通过 `aria-controls` 或 popper 的关联），
  只在其中选择。
- `openTicket`：只在列表第一屏按标题查找。改为先用列表关键字筛选（`q`）定位到该工单再打开，与列表数据量无关。
- 在交付栈上跑 `main-flow.tf.ts` 连续 3 次全部通过（`TF_E2E_CHANNEL=chrome`，账号来自
  `deploy/.accounts.local.json`）。注意登录限流：只登录必需的次数，不写循环探测。

## FE-10 前端门禁清零

分支：`fe/gates`

- Windows 下全量 vitest 有 4 条既有失败：1 条路径分隔符，3 条是测试与后端 HEAD 的词表 / WebSocket 动作契约漂移。
  逐条定位。路径分隔符问题修测试（用 `path.posix` 或统一 `/`）；契约漂移以后端 `openapi.json` 和词表为准修前端，
  确实是上游底座的问题就从上游 xadmin-client 同步对应模块，报告逐条写明原因和修法。
- `check:hook-length` 因上游文件 `useMarkdownUpload.ts` 失败：按 `scripts/check-hook-length.mjs` 的
  “存量只减不增”规则，把它以当前行数登记进存量基线（它是上游文件，不在本项目里拆）。同步删掉 `collab/README.md`
  本机环境备注里关于这条失败的说明。
- 完成后 `frontend/AGENTS.md` 第六节门禁全部通过，Windows 下全量 vitest 0 失败，报告贴输出。

## FE-11 前端品牌：TicketFlow 标识、登录页与工作台首页

分支：`fe/branding`。后端配套任务 BE-07（站点标题种子与已部署库迁移）。

- **名称**：站点标题统一为 `TicketFlow`，副标题“智能工单与知识库协作平台”。`index.html` 的 `<title>`、
  `public/platform-config.json` 的 `Title` 同步修改。
- **标识**：新做 `public/logo.svg`、`public/favicon.ico` 和登录页头像标识，浅色扁平风格，与侧栏、登录页一致。
- **页脚与登录页版权**：署名改为 TicketFlow，链接指向本项目仓库；`src/config/site.ts` 的仓库、文档、演示
  链接改成本项目，保留“基于 xadmin 二次开发”的致谢（上游许可证要求保留来源）。
- **登录页插画**：换成工单流转主题的扁平插画，不出现人物。
- **关于页**：简介改为 TicketFlow 的介绍；保留平台信息和依赖列表；相关链接改为本项目。
- **首页**：`/welcome` 现在是 xadmin 的系统运营仪表盘（登录统计、操作日志），业务角色看不到有意义的数据。
  改成 TicketFlow 工作台：问候语与日期、快捷入口（新建工单、我的工单、知识库）、状态与 SLA 计数
  （`GET /api/tickets/dashboard`，后端已按身份限定范围）、最近工单（列表接口按更新时间取前几条，点击进入
  工单页并打开详情）、最新知识文章（已发布）。不依赖角色判断，数据范围交给后端。
- **其他文案**：zh / en 词条里面向用户的 xAdmin 字样（站点标题占位符、OAuth 授权提示等）一并替换。
  开发者向的注释、日志前缀、上游仓库地址常量以外的代码标识不改。
- 门禁：`frontend/AGENTS.md` 第六节全部通过，新增页面有单测；在联调环境或交付栈上用三个演示账号核对首页。

## FE-12 角色界面适配

分支：`fe/roles`，依赖 BE-08。口径见 [迭代 6 角色改造方案](../../docs/development/迭代6角色改造方案.md)。

- 工单页按身份：技术员有“处理中 / 历史”切换（`assignment=current|history`），管理员有“待分配”入口与计数
  （`assignment=unassigned`、看板 `assignment` 字段）；员工保持“我的工单”。
- 详情：`viewer.read_only` 时显示“只读（已转交）”提示，隐藏全部操作区与 AI 面板；当前处理人有“退回重派”按钮
  （原因必填，走 `/return`，冲突沿用“工单已变更”提示）；指派区只对管理员显示，候选显示技能组。
- 文案：部门 → 技能组（列表列、筛选、详情、指派候选）；角色显示名跟随后端。
- 首页工作台按身份调整计数卡与快捷入口（员工：新建工单、AI 助手入口位先预留；技术员：处理中、即将超时、已超时；
  管理员：待分配、SLA 风险、全部工单）。身份判断以接口返回的 `assignment` 键与权限位为准，不硬编码角色名。
- 登录页：后端关闭注册后不显示注册入口（核对现有能力探测逻辑是否已覆盖）。
- 单测覆盖身份分支；在交付栈用三个演示账号核对（需要用户登录时在报告里写明）。

## FE-13 评价界面

分支：`fe/ratings`，依赖 BE-09。

- 员工确认解决后弹出评价对话框（可跳过）；详情里 `viewer.can_rate` 时显示“评价”按钮，已评价显示评价卡片。
- 评价表单：是否解决、满意度星级、处理人星级、标签多选、文字（计数提示）。
- 技术员“我的评价”页（汇总卡 + 评价列表）、管理员“评价统计”页（整体汇总 + 按技术员表格，可下钻明细）。
- 词条 zh / en 对称；单测覆盖表单校验与弹出时机。

## FE-14 账号与技能组管理

分支：`fe/accounts`，依赖 BE-10。

- “账号管理”：RePlusPage 列表；新建 / 编辑表单（角色三选一，选技术员时技能组必填）；停用 / 启用、重置密码确认框。
- “技能组”：列表、新建 / 编辑、启停；分类路由配置（每个分类选一个技能组）。
- 后端 409（停用约束）显示后端给出的原因。

## FE-15 AI 助手与 AI 反馈

分支：`fe/assistant`，依赖 BE-11、SV-05。

- “AI 助手”页：左侧会话列表（新建、改名、删除），右侧对话区；流式显示回答（复用现有 SSE 工具，支持停止、断线提示），
  引用文章可点开详情；每条回答点赞 / 点踩，点踩弹出原因与补充。
- “转人工提单”：调用草稿接口预填新建工单表单，提交时带 `assistant_session_id`，成功后提示并可跳转到工单。
- 工单详情：有关联会话时显示“查看 AI 对话”，只读展示。
- 管理员“AI 反馈”页：统计卡、被点踩回答列表（展开看问题、回答、原因）、转人工会话列表（可跳到工单）。
- 首页工作台员工的“AI 助手”快捷入口接上。
