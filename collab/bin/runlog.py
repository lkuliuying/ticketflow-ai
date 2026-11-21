"""调度运行记录：每次调用 Codex 或 agy 时写一份 collab/reports/<任务号>.run-<时间>.json。

代理指挥台据此判断哪个代理正在运行、运行了多久、以什么退出码结束。
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from collections.abc import Iterator

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def track(agent: str, task: str, kind: str, detail: str = "") -> Iterator[dict]:
    """记录一次运行；调用方把子进程退出码写进 record["exit_code"]。"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    path = REPORTS / f"{task}.run-{kind}-{started:%Y%m%d-%H%M%S}.json"
    record = {"agent": agent, "task": task, "kind": kind, "detail": detail, "pid": os.getpid(),
              "started": _now(), "status": "running", "exit_code": None}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    try:
        yield record
    finally:
        record["ended"] = _now()
        record["status"] = "done" if record.get("exit_code") == 0 else "failed"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
