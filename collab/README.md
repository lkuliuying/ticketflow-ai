# TicketFlow 多代理协作约定

本目录记录三个代理的分工、任务书和交接方式。代码约定仍以各目录的 `AGENTS.md` 和
[Phase 1 设计评审](../backend-drf/docs/plans/ticketflow-phase-1.md)为准。

## 角色

| 角色 | 代理 | 负责 | 不负责 |
| --- | --- | --- | --- |
| 总指导 + 前端 | Claude Code | 拆分任务、定契约边界、`frontend/` 开发与测试、合并到 `main` | 不改 `backend-drf/` 的业务代码 |
| 后端 + 测试 | Codex | `backend-drf/`（以及 Phase 3 起的 `service-fastapi/`）的实现、迁移、种子、契约文件和测试 | 不改 `frontend/` |
| 评审 | Antigravity · Gemini | 按 [评审清单](review/README.md) 审查分支，输出结论 | 不改代码、不提交 |

用户是最终决策人：合并到 `main`、推送远端、调整阶段范围都需要用户确认。

## 分支与工作目录

两个写代码的代理不共用同一个检出，避免互相覆盖未提交的改动。

| 代理 | 工作目录 | 分支命名 |
| --- | --- | --- |
| Claude | `F:\Program\ticketflow-ai`（主检出） | `fe/<主题>` |
| Codex | `F:\Program\ticketflow-ai-be`（git worktree） | `be/<主题>` |
| Gemini | 只读，按需 `git diff main...<分支>` | — |

首次创建 Codex 的工作目录：

```powershell
git -C F:\Program\ticketflow-ai worktree add ..\ticketflow-ai-be -b be/contract-gaps main
```

- 一个任务一个分支，从最新 `main` 切出；提交遵循各目录 `AGENTS.md` 的提交纪律。
- 任务编号（如 `BE-02`）只出现在本目录、分支说明和报告里，**不写进源码、注释、测试名或种子**
  （后端 `check_ledger_ids.py` 的规则同样适用）。
- 改接口响应结构：Codex 先改 `backend-drf/docs/schema/`，再改代码；Claude 在前端跑
  `pnpm sync:contract` 跟进。

## 本机环境备注

- 全局 pnpm 是 10.32，前端要求 pnpm 11：前端命令用 `npx -y pnpm@11 <命令>`，不要升级全局版本。
- Git Bash 里没有 `docker`，后端测试栈在 WSL2 或 Docker Desktop 下运行。

## 交接流程

```text
Claude 写任务书 (collab/tasks/)  →  执行者在分支上实现并自测
  →  执行者写完成报告 (collab/reports/<任务号>.md)
  →  Gemini 评审 (collab/reviews/<任务号>.md)
  →  REQUEST_CHANGES：执行者修复后更新报告，重新评审
  →  APPROVE：Claude 汇总给用户，用户确认后合并到 main
```

- `collab/tasks/`、`collab/review/README.md` 和本文件进 Git，由 Claude 维护。
- `collab/reports/` 和 `collab/reviews/` 是本机交接文件，已 gitignore。Codex 在 worktree 里工作时，
  用绝对路径 `F:\Program\ticketflow-ai\collab\reports\` 写报告。
- 完成报告必须包含：分支名和提交、改了什么、跑了哪些命令及结果（原样贴失败输出）、
  没做或没验证的部分。没跑过的测试不能写成通过。

## 当前迭代

迭代 6：按用户试用反馈逐项迭代，角色改造口径见[迭代 6 角色改造方案](../docs/development/迭代6角色改造方案.md)。迭代 2~5 已合并到 `main`（迭代 5 于 2026-11-23 合并，验收见
[迭代 5 验收说明](../docs/development/迭代5验收说明.md)）。

| 编号 | 任务 | 执行 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| SV-04 | 模型思考模式开关（接入 DeepSeek）与超时透传 | Codex | — | 评审通过，已集成 |
| BE-07 | 后端品牌：站点标题种子与已部署库迁移、用户可见 xAdmin 字样 | Codex | — | 评审通过，已集成 |
| FE-11 | 前端品牌：标识、登录页、关于页、工作台首页 | Claude | BE-07（标题） | 评审通过，已集成 |
| BE-08 | 三角色、技术员范围（当前 + 历史只读）、指派历史、自动派单、退回重派、关闭注册 | Codex | — | 评审通过，已集成 |
| BE-09 | 工单评价 | Codex | BE-08 | 评审通过，已集成 |
| BE-10 | 账号与技能组管理 | Codex | BE-08 | 评审通过，已集成 |
| BE-11 | AI 知识问答（DRF：会话、消息、反馈、内网上下文） | Codex | BE-08 | 评审通过，已合入 main |
| SV-05 | AI 知识问答（FastAPI：流式对话、转人工草稿） | Codex | BE-11 | 评审通过，已合入 main |
| FE-12 | 角色界面适配 | Claude | BE-08 | 评审通过，已合入 main |
| FE-13 | 评价界面 | Claude | BE-09 | 评审通过，已合入 main |
| FE-14 | 账号与技能组管理页面 | Claude | BE-10 | 评审通过，已合入 main |
| FE-15 | AI 助手与 AI 反馈页面 | Claude | BE-11、SV-05 | 评审通过，已合入 main |

| AGY-01 | 用户分支 `ticketflow-ai-agy` 后端修复（测试失败、WS 授权、内部令牌、契约、媒体与迁移） | Codex | — | 评审通过，已集成到 fe/agy-fixes |
| AGY-02 | 用户分支 `ticketflow-ai-agy` 前端修复（建单失败提示、视频按需加载、补拉分页、契约跟进） | Claude | AGY-01 | 评审通过，待合入 ticketflow-ai-agy |

后端任务书见 [tasks/backend.md](tasks/backend.md)，前端任务书见 [tasks/frontend.md](tasks/frontend.md)，
迭代 6 的任务在任务书末尾。集成分支 `integration/iter6`：各任务评审通过后合入，验收通过后由用户确认合并到 `main`。

## CLI 调度（Claude 执行）

Claude 直接通过命令行调用另外两个代理，用户不需要手动转交：

```powershell
python collab/bin/codex_task.py BE-02                       # Codex 在 ..\ticketflow-ai-be 执行任务
python collab/bin/codex_task.py BE-02 --resume "修复评审阻断项"  # 继续上一次 Codex 会话
python collab/bin/review.py BE-02 be/contract-gaps --repo ..\ticketflow-ai-be   # agy 评审
```

- Codex：`codex exec`，沿用用户 `~/.codex/config.toml`（workspace-write 沙箱、自动审批复核），
  额外可写目录只有 `collab/reports/`。日志在 `collab/reports/<任务号>.log`。使用 `gpt-6.2-sol` + xhigh，
  它要求 codex CLI 0.171 及以上（更旧的版本会报 `model_not_found`）。脚本优先用 PATH 上的 `codex`；
  版本不够时改用 Codex 桌面应用自带的 `codex.exe`，再不行退回 `gpt-6.1-sol`。
- Antigravity：`agy`（1.5.13）以 plan 模式运行，模型 `gemini-4-neon-high`，评审材料由脚本拼好经 stdin
  传入，**不授予任何文件或终端权限**。模型在 `review.py` 的 `MODEL` 中修改，可选值见 `agy models`。

## 代理指挥台（3D 仓库）

```powershell
python collab/dashboard/server.py --port 8765   # 打开 http://127.0.0.1:8765
```

- **总览**：扁平低多边形的仓库区。Claude、Codex、Gemini 各一座封闭仓库（屋脊状态灯：运行中绿、异常红、空闲灰），
  标签显示当前任务和库内各阶段数量，三座仓库摆成三角形，中央是 main 归档库（抽屉按最近提交着色，新提交弹出并撒纸屑）。
  仓库之间用传送带连成环：任务书、完成报告、退回修改、评审结论、提交评审、合并。代理运行时对应车道流动数据包；
  任务换了负责的代理时，一个阶段色货箱沿传送带运到下一座仓库。总览里不显示任务卡片。
- **分支堆场**：main 之外每个分支一个集装箱。领先 main 的分支是彩色高箱（fe/ 橙、be/ 绿、integration/ 灰蓝，领先越多越高，
  当前检出的分支有描边和“当前检出”标记），已合入的分支是前排一排小灰箱。点击集装箱查看分支详情（领先 / 落后、工作目录、关联任务）。
- **仓库内部**：点击仓库（或在面板里选中代理、选中任务）进入该仓库内部。货架放等待中的任务，流水线上是正在处理的任务
  （工作站状态灯、压头随运行上下），出货区是送出的任务（Claude：待合并；Codex：已送评审；Gemini：已放行 / 已退回，半透明）。
  卡面为阶段色底白字。顶栏“返回总览”或 Esc 回到总览。
- 左侧代理面板、右侧详情面板和底部事件流都可以收起，偏好保存在浏览器本地；窄于 1300 px 时默认收起左侧面板。
  镜头按可见区域自动适配，拖动后“复位”回到默认视角，“巡航”自动旋转。
- 代码在 `collab/dashboard/web/`：`scene.js`（两种视图、镜头、拾取、切换）、`warehouse.js`（总览仓库建筑与通用工具）、
  `belt.js`（传送带、数据包、货箱、main 归档库、卡面纹理）、`branches.js`（分支堆场）、`interior.js`（仓库内部）、
  `hud.js`（面板）、`theme.js`（配色与文案）。
- 数据全部来自本机：`collab/README.md` 看板、任务书、`collab/reports/`（报告、Codex 日志、
  `*.run-*.json` 调度记录、`claude.status.json`）、`collab/reviews/` 和 git，每 3 秒刷新，只监听 127.0.0.1。
- `codex_task.py` 与 `review.py` 每次调度都会写运行记录；Claude 切换工作时更新 `claude.status.json`。

## 启动提示词（手动使用时）

给 Codex：

> 你是 TicketFlow 的后端开发与测试负责人。先读仓库根目录的 `AGENTS.md`、`collab/README.md`
> 和 `collab/tasks/backend.md`，在 `F:\Program\ticketflow-ai-be` worktree 中按任务书顺序执行，
> 每个任务一个 `be/` 分支，完成后按约定写 `collab/reports/<任务号>.md`。不要修改 `frontend/`。

给 Gemini（Antigravity）：

> 你是 TicketFlow 的代码评审。先读 `collab/README.md` 和 `collab/review/README.md`，
> 评审 `collab/reports/` 中尚无对应评审文件的任务，按清单输出到 `collab/reviews/<任务号>.md`。
> 只读代码，不修改、不提交。
