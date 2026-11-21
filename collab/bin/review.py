"""调用 Antigravity（agy）对一个任务分支做只读评审。

评审材料（完成报告、任务书、评审清单、设计文档、分支 diff）由本脚本拼好后经
stdin 交给 agy，agy 以 plan 模式运行且不需要任何文件或终端权限。结论写入
collab/reviews/<任务号>.md，复审时追加新的一轮。

用法：
    python collab/bin/review.py BE-02 be/contract-gaps [--repo F:\\Program\\ticketflow-ai-be]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from runlog import track

ROOT = Path(__file__).resolve().parents[2]
COLLAB = ROOT / "collab"
DESIGN = ROOT / "backend-drf" / "docs" / "plans" / "ticketflow-phase-1.md"
MODEL = "gemini-4-neon-high"
DIFF_LIMIT = 400_000


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else f"（缺少 {path.name}）"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def task_brief(task: str) -> str:
    """从任务书中截取该任务的小节。"""
    name = "backend.md" if task.startswith("BE-") else "frontend.md"
    text = read(COLLAB / "tasks" / name)
    match = re.search(rf"^## {re.escape(task)}\b.*?(?=^## |\Z)", text, re.S | re.M)
    return match.group(0) if match else text


def build_prompt(task: str, branch: str, repo: Path, round_no: int, previous: str) -> str:
    commits = git(repo, "log", "--oneline", f"main..{branch}")
    stat = git(repo, "diff", "--stat", f"main...{branch}")
    diff = git(repo, "diff", f"main...{branch}")
    if len(diff) > DIFF_LIMIT:
        diff = diff[:DIFF_LIMIT] + "\n…（diff 过长已截断，请在结论中注明未覆盖部分）"
    head = git(repo, "rev-parse", "--short", branch).strip()
    return "\n\n".join(
        [
            "你是 TicketFlow 项目的代码评审。不要调用任何工具，不要写计划文件，"
            "只根据下面提供的材料评审，并严格按《评审清单》的输出格式直接给出 Markdown 结论。"
            f"标题写“# {task} 评审 · 第 {round_no} 轮”，分支写“{branch} @ {head}”。",
            "# 评审清单\n" + read(COLLAB / "review" / "README.md"),
            "# 任务书\n" + task_brief(task),
            "# 执行者完成报告\n" + read(COLLAB / "reports" / f"{task}.md"),
            ("# 之前轮次的评审\n" + previous) if previous else "",
            "# 设计文档（契约基线）\n" + read(DESIGN),
            f"# 分支提交\n{commits}\n# 改动统计\n{stat}",
            f"# 完整 diff（main...{branch}）\n```diff\n{diff}\n```",
        ]
    )


def run_agy(prompt: str) -> str:
    message = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False)
    result = subprocess.run(
        [
            "agy",
            "--mode",
            "plan",
            "--model",
            MODEL,
            "--print-timeout",
            "15m",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "-p=",
        ],
        input=message + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=COLLAB,
    )
    for line in reversed(result.stdout.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "result":
            outcome = event["result"]
            if outcome.get("status") != "SUCCESS" or not outcome.get("response"):
                sys.exit(f"agy 评审失败：{outcome.get('error') or '无输出'}")
            return outcome["response"]
    sys.exit(f"agy 没有返回结果：\n{result.stderr[-2000:]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("branch")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()

    target = COLLAB / "reviews" / f"{args.task}.md"
    previous = target.read_text(encoding="utf-8") if target.exists() else ""
    round_no = previous.count("评审 · 第") + 1
    with track("gemini", args.task, "review", f"{args.branch} 第 {round_no} 轮") as record:
        response = run_agy(build_prompt(args.task, args.branch, args.repo, round_no, previous))
        record["exit_code"] = 0

    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(("\n\n---\n\n" if previous else "") + f"<!-- {stamp} · {MODEL} -->\n{response.strip()}\n")
    found = re.search(r"结论[:：]\s*\**\s*(APPROVE|REQUEST_CHANGES)", response)
    verdict = found.group(1) if found else "未识别（请人工查看）"
    print(f"{args.task} 第 {round_no} 轮：{verdict} → {target}")


if __name__ == "__main__":
    main()
