# 前端任务书（Claude）

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

