# 网关黑盒验收

先按交付说明启动和初始化演示栈。确保 `TICKETFLOW_DEMO=true`、`MOCK_LLM=true`，并使用默认的 Mock 分段延迟。以下命令从仓库根目录执行。

```sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build --wait
python deploy/local.py seed
cd tests
uv sync --locked
uv run --locked pytest -q -s
```

需要 Python 3.14 和 uv。测试默认访问 `http://127.0.0.1:8080`，从 `deploy/.accounts.local.json` 读取三个演示账号的口令。可以用环境变量覆盖网关地址、凭据文件和各账号的口令。

| 变量 | 用途 |
| --- | --- |
| `TICKETFLOW_GATEWAY_URL` | 网关源地址，支持 HTTP 或 HTTPS |
| `TICKETFLOW_ACCOUNTS_FILE` | 本地 JSON 文件路径，内容是账号到口令的映射 |
| `TICKETFLOW_REQUESTER_PASSWORD` | `tf_requester` 的口令 |
| `TICKETFLOW_AGENT_PASSWORD` | `tf_agent` 的口令 |
| `TICKETFLOW_AGENT_OTHER_PASSWORD` | `tf_agent_other` 的口令 |

测试通过网关创建一张标题以 `Gateway acceptance` 开头的工单，两条并发请求使用同一版本接单。工单留在演示库中便于核对，重复运行会另建一张。

同一来源反复登录可能触发网关后的登录限流。夹具会显示 HTTP 状态和 `Retry-After`，可以等窗口结束后重跑。

SSE 用例从发起请求开始计时，在完整的首个 `delta` 帧和 `done` 帧到达时分别记录时间，并断言前者小于后者的一半。pytest 的 `-s` 参数会显示这两个值及帧序。

CI 仅在本目录运行依赖锁、Ruff 格式和 lint 门禁。

```sh
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
```
