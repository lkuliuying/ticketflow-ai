"""汇总三个代理的实时状态：任务书、运行记录、Codex 日志、报告、评审与 git。

所有数据都从本机文件和 git 读取，不调用任何代理。供 server.py 的 /api/state 使用。
"""

import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLAB = ROOT / "collab"
REPORTS = COLLAB / "reports"
REVIEWS = COLLAB / "reviews"
TASKS = COLLAB / "tasks"
ACTIVE_SECONDS = 120

STAGES = ["待开始", "阻塞", "执行中", "待评审", "评审中", "需修改", "已通过", "已合并"]
AGENTS = {
    "claude": {"name": "Claude", "role": "总指导 · 前端", "model": "claude-opus-5-5", "tool": "Claude Code"},
    "codex": {"name": "Codex", "role": "后端 · 测试", "model": "gpt-6.2-sol", "tool": "codex exec"},
    "gemini": {"name": "Gemini", "role": "代码评审", "model": "gemini-4-neon-high", "tool": "agy --mode plan"},
}
EXECUTOR = {"Claude": "claude", "Codex": "codex", "Gemini": "gemini"}


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _git(*args: str, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _is_ancestor(commit: str, head: str) -> bool:
    """commit 是否在 head 的历史里（git merge-base --is-ancestor 以退出码表达结果）。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, head],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return f'"{pid}"' in out


# ---------------------------------------------------------------- 任务书与看板


def _board() -> list[dict]:
    """读取 collab/README.md 的迭代看板表格。"""
    rows = []
    for line in _read(COLLAB / "README.md").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"[A-Z]{2,3}-\d{2}", cells[0]):
            task_id, title, executor, depends, status = cells
            deps = [] if depends in ("—", "-", "") else re.findall(r"[A-Z]{2,3}-\d{2}(?:\.\.\d{2})?", depends)
            rows.append({"id": task_id, "title": title, "executor": executor, "depends": deps, "board_status": status})
    return rows


def _expand(deps: list[str]) -> list[str]:
    result = []
    for dep in deps:
        match = re.fullmatch(r"([A-Z]{2,3})-(\d{2})\.\.(\d{2})", dep)
        if match:
            prefix, start, end = match.group(1), int(match.group(2)), int(match.group(3))
            result.extend(f"{prefix}-{n:02d}" for n in range(start, end + 1))
        else:
            result.append(dep)
    return result


def _briefs() -> dict[str, dict]:
    """从任务书中取每个任务的小节、分支与要点。"""
    briefs: dict[str, dict] = {}
    for path in TASKS.glob("*.md"):
        text = _read(path)
        for match in re.finditer(r"^## ([A-Z]{2,3}-\d{2}) (.+?)$(.*?)(?=^## |\Z)", text, re.S | re.M):
            body = match.group(3)
            branch = re.search(r"分支：`([^`]+)`", body)
            points = [p.strip("- ").strip() for p in re.findall(r"^(?:- |\d+\. )(.+)$", body, re.M)]
            briefs[match.group(1)] = {
                "heading": match.group(2).strip(),
                "branch": branch.group(1) if branch else None,
                "points": [re.sub(r"\*\*|`", "", p)[:160] for p in points[:10]],
            }
    return briefs


# ---------------------------------------------------------------- 运行记录与日志


def _runs() -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    for path in sorted(REPORTS.glob("*.run*.json")):
        try:
            run = json.loads(_read(path))
        except json.JSONDecodeError:
            continue
        run["alive"] = run.get("status") == "running" and _alive(run.get("pid"))
        if run.get("status") == "running" and not run["alive"]:
            run["status"] = "lost"
        runs.setdefault(run.get("agent", "?"), []).append(run)
    for items in runs.values():
        items.sort(key=lambda r: r.get("started", ""))
    return runs


def parse_codex_log(path: Path) -> dict:
    """把 codex exec 的文本日志解析成消息、命令和补丁。"""
    if not path.exists():
        return {}
    lines = _read(path).splitlines()
    messages, commands, patched = [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "codex" and i + 1 < len(lines):
            j = i + 1
            chunk = []
            while j < len(lines) and lines[j] and not lines[j].startswith("hook:"):
                chunk.append(lines[j])
                j += 1
            if chunk:
                messages.append(" ".join(chunk)[:400])
            i = j
            continue
        if line == "exec" and i + 1 < len(lines):
            cmd = re.sub(r'^"[^"]*pwsh\.exe"\s+-Command\s+', "", lines[i + 1])
            cmd = re.sub(r"\s+in [A-Z]:\\S*$", "", cmd).strip("'\"")
            cmd = cmd.replace("\\\\", "\\").replace("'\"'", "'").replace("\"'", "")
            result = {"cmd": cmd[:220], "status": "running", "ms": None, "output": []}
            k = i + 2
            while k < len(lines) and lines[k] not in ("exec", "codex"):
                outcome = re.match(r"\s*(succeeded|exited (-?\d+)|failed)\D*?(\d+)ms", lines[k])
                if outcome:
                    result["status"] = "ok" if outcome.group(1) == "succeeded" else "fail"
                    result["ms"] = int(outcome.group(3))
                    k += 1
                    while k < len(lines) and lines[k] and not lines[k].startswith("hook:") and len(result["output"]) < 6:
                        result["output"].append(lines[k][:200])
                        k += 1
                    break
                k += 1
            commands.append(result)
            i += 2
            continue
        if line.startswith("diff --git "):
            name = line.split(" b/", 1)[-1]
            if name not in patched:
                patched.append(name)
        i += 1
    for command in commands[:-1]:
        if command["status"] == "running":
            command["status"] = "unknown"
    header = {}
    for key in ("workdir", "model", "sandbox", "reasoning effort", "session id"):
        found = next((l.split(":", 1)[1].strip() for l in lines[:40] if l.startswith(key + ":")), None)
        header[key.replace(" ", "_")] = found
    errors = [l[:240] for l in lines if l.startswith("ERROR:")][-3:]
    tokens = None
    for k, l in enumerate(lines):
        if l == "tokens used" and k + 1 < len(lines):
            tokens = lines[k + 1].strip()
    mtime = path.stat().st_mtime
    return {
        "header": header,
        "messages": messages[-8:],
        "last_message": messages[-1] if messages else "",
        "commands": commands[-14:],
        "command_total": len(commands),
        "command_failed": sum(1 for c in commands if c["status"] == "fail"),
        "patched": patched[-40:],
        "errors": errors,
        "tokens": tokens,
        "updated": _iso(mtime),
        "active": time.time() - mtime < ACTIVE_SECONDS,
        "size": path.stat().st_size,
    }


# ---------------------------------------------------------------- 报告与评审


def _review(task: str) -> dict | None:
    path = REVIEWS / f"{task}.md"
    if not path.exists():
        return None
    text = _read(path)
    rounds = []
    for block in re.split(r"\n---\n", text):
        title = re.search(r"评审 · 第 (\d+) 轮", block)
        if not title:
            continue
        stamp = re.search(r"<!-- (.+?) · (.+?) -->", block)
        verdict = re.search(r"结论[:：]\s*\**\s*(APPROVE|REQUEST_CHANGES)", block)
        issues = []
        for row in re.findall(r"^\|\s*(阻断|一般|建议|无)\s*\|(.+)$", block, re.M):
            cells = [c.strip() for c in row[1].strip().strip("|").split("|")]
            if row[0] != "无":
                issues.append({"level": row[0], "where": cells[0] if cells else "", "what": (cells[1] if len(cells) > 1 else "")[:220]})
        suggestions = re.findall(r"^- (.+)$", block.split("建议（不阻断）")[-1], re.M) if "建议（不阻断）" in block else []
        reviewed = re.search(r"分支[:：]\s*\S+\s*@\s*([0-9a-f]{7,40})", block)
        rounds.append({
            "round": int(title.group(1)),
            "sha": reviewed.group(1) if reviewed else None,
            "time": stamp.group(1) if stamp else None,
            "model": stamp.group(2) if stamp else None,
            "verdict": verdict.group(1) if verdict else None,
            "issues": issues,
            "suggestions": [s[:200] for s in suggestions[:5]],
        })
    return {"rounds": rounds, "updated": _iso(path.stat().st_mtime), "mtime": path.stat().st_mtime}


def _report(task: str) -> dict | None:
    path = REPORTS / f"{task}.md"
    if not path.exists():
        return None
    text = _read(path)
    branch = re.search(r"分支[^`\n]*`([^`]+)`", text)
    commit = re.search(r"@ `?([0-9a-f]{7,40})`?", text)
    unfinished = text.split("未完成或未验证")[-1] if "未完成或未验证" in text else ""
    return {
        "updated": _iso(path.stat().st_mtime),
        "mtime": path.stat().st_mtime,
        "branch": branch.group(1) if branch else None,
        "commit": commit.group(1) if commit else None,
        "unverified": [l.strip("- ").strip()[:200] for l in unfinished.splitlines() if l.startswith("- ")][:6],
        "chars": len(text),
    }


# ---------------------------------------------------------------- git


def _git_state() -> dict:
    branches = []
    fmt = "%(refname:short)|%(objectname:short)|%(committerdate:iso-strict)|%(subject)"
    for line in _git("for-each-ref", "refs/heads", f"--format={fmt}").splitlines():
        name, sha, date, subject = (line.split("|", 3) + ["", "", "", ""])[:4]
        counts = _git("rev-list", "--left-right", "--count", f"main...{name}").split()
        behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
        branches.append({"name": name, "sha": sha, "date": date, "subject": subject, "ahead": ahead, "behind": behind})
    worktrees = []
    block: dict = {}
    for line in _git("worktree", "list", "--porcelain").splitlines() + [""]:
        if not line and block:
            path = Path(block.get("worktree", ""))
            dirty = _git("status", "--short", cwd=path).splitlines()
            block["dirty"] = len(dirty)
            block["dirty_files"] = [d[3:] for d in dirty[:30]]
            worktrees.append(block)
            block = {}
        elif line:
            key, _, value = line.partition(" ")
            block[key] = value.replace("refs/heads/", "") if key == "branch" else value
    commits = []
    log_fmt = "%h|%ad|%(trailers:key=Co-Authored-By,valueonly,separator=;)|%D|%s"
    for line in _git("log", "--all", "--date=iso-strict", f"--format={log_fmt}", "-40").splitlines():
        sha, date, coauthor, refs, subject = (line.split("|", 4) + [""] * 5)[:5]
        commits.append({"sha": sha, "date": date, "author": _author(coauthor), "refs": refs, "subject": subject})
    current = _git("branch", "--show-current").strip()
    return {"branches": branches, "worktrees": worktrees, "commits": commits, "current": current}


# ---------------------------------------------------------------- 汇总


def _stage(task: dict, branch: dict | None, runs: list[dict], log: dict, done: set[str]) -> str:
    rounds = (task["review"] or {}).get("rounds") or []
    verdict = rounds[-1]["verdict"] if rounds else None
    report = task["report"]
    review_running = any(r.get("alive") and r.get("kind") == "review" for r in runs)
    executing = any(r.get("alive") and r.get("kind") == "task" for r in runs) or bool(log.get("active"))
    if verdict == "APPROVE" and branch is not None and branch["ahead"] == 0 and report:
        return "已合并"
    # 只搭环境、不产出代码的任务不走评审，看板标为已完成即视为走完流水线
    if task["board_status"].startswith(("已完成", "已合并")):
        return "已合并"
    if review_running:
        return "评审中"
    if executing:
        return "执行中"
    # 评审结论只对它评审的那个提交有效：分支没有新提交就沿用结论，有新提交则需要重新评审
    reviewed_sha = rounds[-1].get("sha") if rounds else None
    head = (branch or {}).get("sha") or ""
    current = bool(reviewed_sha and head and (head.startswith(reviewed_sha) or reviewed_sha.startswith(head)))
    # 多个任务共用一个分支时，后续任务的提交会让前一个任务的评审提交不再是分支头；
    # 看板已标记评审通过且评审提交仍在分支历史里，就沿用该结论
    if not current and reviewed_sha and task["board_status"].startswith("评审通过"):
        current = _is_ancestor(reviewed_sha, head or "HEAD")
    if report and verdict and (current or (not reviewed_sha and task["review"]["mtime"] >= report["mtime"])):
        return "已通过" if verdict == "APPROVE" else "需修改"
    if report:
        return "待评审"
    if any(dep not in done for dep in task["depends"]):
        return "阻塞"
    if branch is not None and branch["ahead"] > 0:
        return "执行中"
    if task["board_status"].startswith("进行中"):
        return "执行中"
    return "待开始"


def collect() -> dict:
    git = _git_state()
    branches = {b["name"]: b for b in git["branches"]}
    briefs = _briefs()
    runs = _runs()
    tasks = []
    for row in _board():
        brief = briefs.get(row["id"], {})
        task = {**row, "depends": _expand(row["depends"]), **brief,
                "report": _report(row["id"]), "review": _review(row["id"])}
        task["branch"] = task.get("branch") or (task["report"] or {}).get("branch")
        task["agent"] = EXECUTOR.get(row["executor"], "claude")
        task["log"] = parse_codex_log(REPORTS / f"{row['id']}.log") if task["agent"] == "codex" else {}
        task["runs"] = [r for items in runs.values() for r in items if r.get("task") == row["id"]]
        tasks.append(task)
    done = set()
    for _ in range(3):
        for task in tasks:
            task["stage"] = _stage(task, branches.get(task["branch"] or ""), task["runs"], task["log"], done)
            if task["stage"] in ("已通过", "已合并"):
                done.add(task["id"])
    tasks.extend(_off_board_tasks({t["id"] for t in tasks}, runs))
    for task in tasks:
        task["branch_info"] = branches.get(task["branch"] or "")
        task.pop("log_raw", None)
    return {
        "now": _iso(time.time()),
        "stages": STAGES,
        "agents": _agents(tasks, runs, git),
        "tasks": tasks,
        "git": git,
        "events": _events(tasks, git),
    }


def _off_board_tasks(board_ids: set[str], runs: dict[str, list[dict]]) -> list[dict]:
    """看板之外仍在运行的调度（全量测试、修复、排查等临时任务）：补成任务卡，
    让总览、仓库内部和侧栏都能看到；运行结束后不再出现，结论看对应报告。"""
    extra: dict[str, dict] = {}
    for agent, items in runs.items():
        for run in items:
            task_id = run.get("task")
            if not run.get("alive") or not task_id or task_id in board_ids:
                continue
            reviewing = run.get("kind") == "review"
            entry = extra.setdefault(task_id, {
                "id": task_id,
                "title": (run.get("detail") or task_id).splitlines()[0][:40],
                "executor": "Codex",
                "depends": [],
                "board_status": "临时任务",
                "agent": "codex",
                "branch": None,
                "report": _report(task_id),
                "review": _review(task_id),
                "log": parse_codex_log(REPORTS / f"{task_id}.log"),
                "runs": [],
            })
            entry["runs"].append(run)
            # 评审进行中优先显示在评审仓，否则在执行方流水线上
            entry["stage"] = "评审中" if reviewing or entry.get("stage") == "评审中" else "执行中"
            if agent == "claude":
                entry["executor"], entry["agent"] = "Claude", "claude"
    return list(extra.values())


def _agents(tasks: list[dict], runs: dict, git: dict) -> dict:
    agents = {key: {**meta, "id": key} for key, meta in AGENTS.items()}
    claude_status = {}
    try:
        claude_status = json.loads(_read(REPORTS / "claude.status.json"))
    except json.JSONDecodeError:
        pass
    agents["claude"].update(
        state=claude_status.get("state", "idle"),
        activity=claude_status.get("activity", ""),
        task=claude_status.get("task"),
        updated=claude_status.get("updated"),
        notes=claude_status.get("notes", []),
        checkout=git["current"],
    )
    codex_tasks = [t for t in tasks if t["agent"] == "codex"]
    live = next((t for t in codex_tasks if t["log"].get("active") or any(r.get("alive") for r in t["runs"])), None)
    latest = live or max(codex_tasks, key=lambda t: t["log"].get("updated") or "", default=None)
    log = latest["log"] if latest else {}
    task_id = latest["id"] if latest else None
    # 看板之外的临时任务（全量测试、修复、排查等）也有调度记录：进程还活着就按运行中显示
    off_board = next((r for r in reversed(runs.get("codex", [])) if r.get("alive")), None)
    if not live and off_board:
        task_id = off_board.get("task")
        log = parse_codex_log(REPORTS / f"{task_id}.log")
    if log.get("header", {}).get("model"):
        agents["codex"]["model"] = f"{log['header']['model']} · {log['header'].get('reasoning_effort') or ''}".strip(" ·")
    agents["codex"].update(
        state="running" if live or off_board else ("error" if log.get("errors") and not log.get("messages") else "idle"),
        task=task_id,
        activity=log.get("last_message", ""),
        log=log,
        runs=runs.get("codex", []),
    )
    reviewed = [t for t in tasks if t["review"]]
    last = max(reviewed, key=lambda t: t["review"]["mtime"], default=None)
    review_runs = runs.get("gemini", [])
    running = next((r for r in review_runs if r.get("alive")), None)
    last_round = last["review"]["rounds"][-1] if last and last["review"]["rounds"] else None
    agents["gemini"].update(
        state="running" if running else "idle",
        task=(running or {}).get("task") or (last["id"] if last else None),
        activity=(f"正在评审 {running['task']}" if running else
                  f"{last['id']} 第 {last_round['round']} 轮：{last_round['verdict']}" if last_round else "等待评审任务"),
        last_round=last_round,
        runs=review_runs,
        reviewed=len(reviewed),
        total_rounds=sum(len(t["review"]["rounds"]) for t in reviewed),
    )
    return agents


def _events(tasks: list[dict], git: dict) -> list[dict]:
    events = []
    for commit in git["commits"][:20]:
        events.append({"time": commit["date"], "kind": "commit", "agent": commit["author"],
                       "text": f"{commit['sha']} {commit['subject']}"})
    for task in tasks:
        for run in task["runs"]:
            events.append({"time": run.get("started"), "kind": "dispatch", "agent": run.get("agent"),
                           "text": f"调度 {run.get('agent')} 执行 {task['id']}" if run.get("kind") == "task"
                           else f"调度评审 {task['id']}"})
            if run.get("ended"):
                events.append({"time": run["ended"], "kind": "finish", "agent": run.get("agent"),
                               "text": f"{task['id']} {run.get('kind')} 结束，退出码 {run.get('exit_code')}"})
        if task["report"]:
            events.append({"time": task["report"]["updated"], "kind": "report", "agent": task["agent"],
                           "text": f"{task['id']} 完成报告更新"})
        for rnd in (task["review"] or {}).get("rounds", []):
            if rnd["time"]:
                stamp = datetime.strptime(rnd["time"], "%Y-%m-%d %H:%M").astimezone().isoformat(timespec="seconds")
                events.append({"time": stamp, "kind": "review", "agent": "gemini",
                               "text": f"{task['id']} 第 {rnd['round']} 轮 {rnd['verdict']}"
                                       f"（阻断 {sum(1 for i in rnd['issues'] if i['level'] == '阻断')}）"})
    events = [e for e in events if e["time"]]
    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:40]


def _author(coauthor: str) -> str:
    """按 Co-Authored-By 判断提交来自哪个代理；没有署名的是用户本人或上游。"""
    lowered = coauthor.lower()
    if "codex" in lowered:
        return "codex"
    if "claude" in lowered:
        return "claude"
    return "human"


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2)[:4000])
