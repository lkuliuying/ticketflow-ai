# TicketFlow AI 服务

服务使用 Python 3.14 和 uv 0.12.5 或更高版本。当前提供 `GET /ai/v1/health`、可供路由注入的联合鉴权依赖，以及调用 DRF 工单上下文的客户端。健康检查无需 token。Redis 正常时返回 `200` 和 `{"status":"ok","redis":"ok"}`，故障时返回 `503` 和 `{"code":503,"error":"AUTH_REDIS_UNAVAILABLE","detail":"认证 Redis 不可用"}`。

HTTP 错误统一返回 `{code, error, detail}`。`code` 是与 HTTP 状态码一致的整数，`error` 是机器可读标识，`detail` 是可读说明。例如令牌无效时返回 `{"code":401,"error":"UNAUTHORIZED","detail":"需要有效的 Bearer access token"}`。

后续 SSE 建流失败沿用同一 HTTP 错误信封。建流后以 `error` 事件携带 `{code, error, detail, retryable}`，其中 `code` 取该错误对应的整数状态码。

## 本地启动

从 [`.env.example`](.env.example) 复制出 `.env`，或直接设置同名环境变量。将 `JWT_SIGNING_KEY` 填为 DRF 的 `SIMPLE_JWT.SIGNING_KEY`，部署时向两边显式注入同一个密钥。使用 `backend-drf/compose.test.yml` 的 Redis 时，将 `AUTH_REDIS_URL` 设为 `redis://127.0.0.1:56379/1`。

```sh
uv sync --locked
uv run uvicorn app.main:app --port 8897
```

从本机访问 `http://127.0.0.1:8897/ai/v1/health`，OpenAPI 文档位于 `/docs`。

## 配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `JWT_SIGNING_KEY` | 必填 | 与 DRF 共享的 HS256 签名密钥 |
| `AUTH_REDIS_URL` | `redis://127.0.0.1:6379/1` | 包含 DRF `DEFAULT_CACHE_ID` 的认证 Redis URL。默认逻辑库是 1，覆盖时请在 URL 中显式写出库号 |
| `AUTH_REDIS_TIMEOUT` | `0.5` | 认证 Redis 单次操作的总预算，单位秒 |
| `DRF_BASE_URL` | `http://127.0.0.1:8896` | DRF 内网地址，须能访问 `/api/tickets/{id}/ai-context` |
| `HTTP_CONNECT_TIMEOUT` | `1.0` | HTTP 连接超时，单位秒 |
| `HTTP_READ_TIMEOUT` | `3.0` | HTTP 读写各阶段超时，单位秒 |
| `DRF_TOTAL_TIMEOUT` | `5.0` | 工单上下文 HTTP 调用的总预算，包含排队与重试，单位秒 |
| `HTTP_MAX_CONNECTIONS` | `32` | 每个进程 HTTP 连接池的总连接数与空闲连接数上限 |
| `UPSTREAM_CONCURRENCY` | `16` | 每个进程同时执行的上游请求上限 |
| `UPSTREAM_SLOT_TIMEOUT` | `1.0` | 等待上游并发额度或 HTTP 池连接的超时，单位秒 |
| `DRF_MAX_RETRIES` | `2` | 连接失败、连接超时和 5xx 的额外尝试次数，范围 0–5。退避期间释放并发额度 |

## 容器

在本目录构建镜像。通过 `.env` 传入配置，使用从容器可达的 `AUTH_REDIS_URL` 和 `DRF_BASE_URL`。例如 Docker Desktop 上可通过 `host.docker.internal` 访问宿主端口，或使用同一 Docker 网络里的服务地址。

```sh
docker build -t ticketflow-ai-service .
docker run --rm --env-file .env -p 127.0.0.1:8897:8897 ticketflow-ai-service
```

## 测试

```sh
uv run python -m pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy
```

真实 Redis 用例需设置 `AUTH_TEST_REDIS_URL` 后运行同一套测试。例如启动 DRF 的测试栈后，将它设为 `redis://127.0.0.1:56379/1`。该用例使用随机令牌和键，并清理自己写入的数据。
