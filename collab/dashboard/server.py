"""代理指挥台的本地服务：静态页面 + /api/state 实时状态。

只监听 127.0.0.1。用法：
    python collab/dashboard/server.py [--port 8765]
"""

import argparse
import json
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import state

HERE = Path(__file__).resolve().parent
CACHE_SECONDS = 2.0
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "body": b""}


def snapshot() -> bytes:
    with _lock:
        if time.time() - _cache["at"] > CACHE_SECONDS:
            try:
                data = state.collect()
            except Exception as exc:  # 采集失败时把原因交给页面展示，而不是让页面空白
                data = {"error": f"{type(exc).__name__}: {exc}"}
            _cache["body"] = json.dumps(data, ensure_ascii=False).encode("utf-8")
            _cache["at"] = time.time()
        return _cache["body"]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE / "web"), **kwargs)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/api/state":
            body = snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        if "/api/state" not in (args[0] if args else ""):
            super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"代理指挥台：http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
