"""调用 Codex CLI 在后端 worktree 中执行一个任务。

Codex 在 workspace-write 沙箱里工作，可写范围是 worktree 和 collab/reports/。
它在任务分支上提交，不推送、不合并。完成报告写到 collab/reports/<任务号>.md，
运行日志写到 collab/reports/<任务号>.log。

用法：
    python collab/bin/codex_task.py BE-02 [--worktree F:\\Program\\ticketflow-ai-be] [--extra "补充说明"]
    python collab/bin/codex_task.py BE-02 --resume "根据评审修复阻断问题"
"""

import argparse
import subprocess
from pathlib import Path

from runlog import track

ROOT = Path(__file__).resolve().parents[2]
COLLAB = ROOT / "collab"
REPORTS = COLLAB / "reports"
# 用户配置里的默认模型在 ChatGPT 账号的 CLI 下不可用，这里显式指定
MODEL = "gpt-6.1-sol"
DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"

ENVIRONMENT = f"""本机环境：
- Windows 11。Docker Desktop 已运行，但 docker 不在 PATH，用完整路径 `{DOCKER}`；也可在 WSL 发行版 Ubuntu 里操作。
- 后端底座依赖 Linux 文件锁，集成测试优先在 WSL 或容器里跑；Windows 下可用于 ruff、mypy 和静态门禁。
- 主检出的 Windows 虚拟环境在 `{ROOT / "backend-drf" / ".venv"}`，worktree 里没有 .venv，可自行 `uv sync --all-groups`。
- 测试栈：在 `backend-drf/` 下 `docker compose -f compose.test.yml up -d --wait`（PG 55433 / Redis 56379）。"""


def build_prompt(task: str, extra: str) -> str:
    return f"""你是 TicketFlow 项目的后端开发与测试负责人。总指导是 Claude，评审是 Gemini。

先读这些文件（主检出中的协作文档，用绝对路径读取）：
- {COLLAB / "README.md"}：分工、分支与交接约定
- {COLLAB / "tasks" / "backend.md"}：后端任务书，本次只做其中的 {task}
- 当前工作目录下的 AGENTS.md 与 backend-drf/AGENTS.md：代码、迁移、种子、测试和提交约定
- backend-drf/docs/plans/ticketflow-phase-1.md：契约基线

执行要求：
1. 只做 {task}，只改 backend-drf/（以及任务书明确提到的根目录文件），不要改 frontend/。
2. 在当前分支上工作并提交，提交信息遵循 backend-drf/AGENTS.md 的提交纪律，结尾加一行
   `Co-Authored-By: Codex <noreply@openai.com>`。不要推送，不要切到或修改 main。
3. 源码、注释、测试名、种子里不要出现任务编号。
4. 跑完任务书要求的测试与门禁。环境原因跑不了的命令，如实写明原因，不能写成通过。
5. 完成后把报告写到 {REPORTS / (task + ".md")}，内容包括：分支名和提交哈希、改动摘要、
   新增或变更的接口示例响应、执行过的命令及结果（失败原样贴关键输出）、未完成或未验证的部分。

{ENVIRONMENT}
{("补充说明：" + extra) if extra else ""}"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--worktree", type=Path, default=ROOT.parent / "ticketflow-ai-be")
    parser.add_argument("--extra", default="")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--resume", help="继续上一次 Codex 会话并发送这条指令")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    common = ["-m", args.model, "-C", str(args.worktree), "--add-dir", str(REPORTS), "-o", str(REPORTS / f"{args.task}.last.md")]
    if args.resume:
        command = ["codex", "exec", *common, "resume", "--last", args.resume]
    else:
        command = ["codex", "exec", *common, build_prompt(args.task, args.extra)]
    detail = args.resume or args.extra or "按任务书执行"
    with track("codex", args.task, "task", detail) as record, (REPORTS / f"{args.task}.log").open(
        "a", encoding="utf-8"
    ) as log:
        code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
        record["exit_code"] = code
    print(f"codex 退出码 {code}，日志 {REPORTS / (args.task + '.log')}")


if __name__ == "__main__":
    main()
