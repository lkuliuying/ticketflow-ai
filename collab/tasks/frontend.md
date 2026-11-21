# 前端任务书（Claude）

工作目录 `frontend/`，遵循 `frontend/AGENTS.md`。菜单种子已指向
`ticketflow/tickets/index` 和 `ticketflow/knowledge/index`，页面放在 `src/views/ticketflow/` 下。

## FE-01 工单 API 层与列表页

分支：`fe/ticket-list`

- `src/api/ticketflow/tickets.ts`：继承 `BaseApi`，补 `transition`、`assign`、`comments`、
  `timeline`、`aiMetadata`、`dashboard`。`create` 每次提交生成 `Idempotency-Key`，
  同一次弹窗内重试复用同一个键。
- 列表页走 RePlusPage + 后端元数据：状态、优先级用标签渲染，`sla_state` 高亮
  （`DUE_SOON` 警告色、`OVERDUE` 危险色），筛选支持 `sla` 和 `q`。
- 新建工单表单：标题、描述、分类、优先级；409 提示幂等冲突，429 提示稍后重试。

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
