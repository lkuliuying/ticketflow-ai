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
- 前端 `check:hook-length` 目前因上游文件 `src/views/system/notice/components/markdown/useMarkdownUpload.ts`
  失败，与二开无关，暂不处理。

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

| 编号 | 任务 | 执行 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| BE-01 | 测试环境与全量门禁基线 | Codex | — | 待开始 |
| BE-02 | 前端所需的契约补口 | Codex | — | 待开始，**阻塞 FE-02 / FE-03** |
| BE-03 | Phase 2 测试补全 | Codex | BE-01 | 待开始 |
| BE-04 | Phase 2 遗留问题修复 | Codex | BE-01 | 待开始 |
| FE-01 | 工单 API 层与列表页 | Claude | — | 进行中 |
| FE-02 | 工单详情：流转、指派、回复、时间线 | Claude | BE-02 | 待开始 |
| FE-03 | 知识库列表、详情、编辑与转存 | Claude | BE-02 | 待开始 |
| FE-04 | 看板与异步导出入口 | Claude | FE-01 | 待开始 |
| FE-05 | 词条、单测与 E2E 冒烟 | Claude | FE-01..04 | 待开始 |

后端任务书见 [tasks/backend.md](tasks/backend.md)，前端任务书见 [tasks/frontend.md](tasks/frontend.md)。
Phase 3（FastAPI）和 Phase 4b（AI 面板）在本迭代评审通过后再下发。

## CLI 调度（Claude 执行）

Claude 直接通过命令行调用另外两个代理，用户不需要手动转交：

```powershell
python collab/bin/codex_task.py BE-02                       # Codex 在 ..\ticketflow-ai-be 执行任务
python collab/bin/codex_task.py BE-02 --resume "修复评审阻断项"  # 继续上一次 Codex 会话
python collab/bin/review.py BE-02 be/contract-gaps --repo ..\ticketflow-ai-be   # agy 评审
```

- Codex：`codex exec`，沿用用户 `~/.codex/config.toml`（workspace-write 沙箱、自动审批复核），
  额外可写目录只有 `collab/reports/`。日志在 `collab/reports/<任务号>.log`。配置里的默认模型
  `gpt-6.2-sol` 在 ChatGPT 账号的 CLI 下会报 `model_not_found`，脚本显式使用 `gpt-6.1-sol`。
- Antigravity：`agy` 以 plan 模式运行，评审材料由脚本拼好经 stdin 传入，**不授予任何文件或终端权限**。
  可用模型里没有 Gemini 4 Neon，当前使用 `gemini-3.8-flash-high`（在 `review.py` 的 `MODEL` 中修改）。

## 启动提示词（手动使用时）

给 Codex：

> 你是 TicketFlow 的后端开发与测试负责人。先读仓库根目录的 `AGENTS.md`、`collab/README.md`
> 和 `collab/tasks/backend.md`，在 `F:\Program\ticketflow-ai-be` worktree 中按任务书顺序执行，
> 每个任务一个 `be/` 分支，完成后按约定写 `collab/reports/<任务号>.md`。不要修改 `frontend/`。

给 Gemini（Antigravity）：

> 你是 TicketFlow 的代码评审。先读 `collab/README.md` 和 `collab/review/README.md`，
> 评审 `collab/reports/` 中尚无对应评审文件的任务，按清单输出到 `collab/reviews/<任务号>.md`。
> 只读代码，不修改、不提交。
