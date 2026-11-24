# 网关黑盒验收

先按交付说明启动和初始化演示栈，确保 `TICKETFLOW_DEMO=true`。以下命令从仓库根目录执行。

```sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build --wait
python deploy/local.py seed
cd tests
uv sync --locked
uv run --locked pytest -q -s
```

需要 Python 3.14 和 uv。测试默认访问 `http://127.0.0.1:8080`，从 `deploy/.accounts.local.json` 读取演示账号口令。可以用环境变量覆盖网关地址、凭据文件和各账号的口令。

| 变量 | 用途 |
| --- | --- |
| `TICKETFLOW_GATEWAY_URL` | 网关源地址，支持 HTTP 或 HTTPS |
| `TICKETFLOW_GATEWAY_MOCK` | 默认按真实模型验收。仅当目标栈为 `MOCK_LLM=true` 且采用默认交付分段延迟时设为 `1`，追加 Mock 固定草稿和相对耗时断言 |
| `TICKETFLOW_ACCOUNTS_FILE` | 本地 JSON 文件路径，内容是账号到口令的映射 |
| `TICKETFLOW_REQUESTER_PASSWORD` | `tf_requester` 的口令 |
| `TICKETFLOW_AGENT_PASSWORD` | `tf_agent` 的口令 |
| `TICKETFLOW_AGENT_OTHER_PASSWORD` | `tf_agent_other` 的口令 |
| `TICKETFLOW_ADMIN_PASSWORD` | `tf_admin` 的口令 |

测试通过网关创建一张标题以 `Gateway acceptance` 开头的工单，两条并发请求使用同一版本接单。工单留在演示库中便于核对，重复运行会另建一张。

同一来源反复登录可能触发网关后的登录限流。夹具会显示 HTTP 状态和 `Retry-After`，可以等窗口结束后重跑。

两种模式均校验 SSE 协议、回答落库、草稿字段、分类和长度。SSE 用例记录完整首个 `delta` 帧与 `done` 帧的到达时间，pytest 的 `-s` 参数会显示这两个值及帧序。启用 Mock 专属断言时，首个 `delta` 须在总耗时的一半前到达，草稿须回显固定内容。

CI 仅在本目录运行依赖锁、Ruff 格式和 lint 门禁。

```sh
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
```
