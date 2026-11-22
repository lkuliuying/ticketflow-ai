# TicketFlow AI 服务

服务使用 Python 3.14 和 uv 0.12.5 或更高版本。健康检查 `GET /ai/v1/health` 无需 token。Redis 正常时返回 `200` 和 `{"status":"ok","redis":"ok"}`，故障时返回 `503` 和 `{"code":503,"error":"AUTH_REDIS_UNAVAILABLE","detail":"认证 Redis 不可用"}`。

`POST /ai/v1/tickets/analyze` 和 `POST /ai/v1/tickets/suggest-reply/stream` 共用 `{"ticket_id":"UUID"}` 请求和 Bearer access token。每次调用由 DRF 检查工单可见性与处理权限。分析成功返回工单 ID、版本、分类、建议优先级、摘要与标签。流式回复按顺序发出 `meta`、`delta` 和 `done`，等待增量时发出 `ping`（`{}`）。生成的内容由客服确认后在工单页采纳或发送。

HTTP 错误统一返回 `{code, error, detail}`。`code` 是与 HTTP 状态码一致的整数，`error` 是机器可读标识，`detail` 是可读说明。例如令牌无效时返回 `{"code":401,"error":"UNAUTHORIZED","detail":"需要有效的 Bearer access token"}`。

SSE 建流前的失败沿用 HTTP 错误信封。建流后的失败以 `error` 事件结束，携带 `{code, error, detail, retryable}`。分析与 SSE 字段见 [工单 AI 契约](../backend-drf/docs/schema/ticketflow-ai.schema.json)。分析缓存使用 `ticketflow:ai:analysis:` 前缀。缓存读写异常时回源，鉴权 Redis 故障时拒绝请求。

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
| `JWT_LEEWAY_SECONDS` | `0` | 与 DRF 使用同一签发和到期时间容差，单位秒。交付栈默认 30 |
| `AUTH_REDIS_URL` | `redis://127.0.0.1:6379/1` | 包含 DRF `DEFAULT_CACHE_ID` 的认证 Redis URL。默认逻辑库是 1，覆盖时请在 URL 中显式写出库号 |
| `AUTH_REDIS_TIMEOUT` | `0.5` | 认证 Redis 单次操作的总预算，单位秒 |
| `DRF_BASE_URL` | `http://127.0.0.1:8896` | DRF 内网地址，须能访问 `/api/tickets/{id}/ai-context` |
| `HTTP_CONNECT_TIMEOUT` | `1.0` | HTTP 连接超时，单位秒 |
| `HTTP_READ_TIMEOUT` | `3.0` | HTTP 读写各阶段超时，单位秒 |
| `DRF_TOTAL_TIMEOUT` | `5.0` | 工单上下文 HTTP 调用的总预算，包含排队与重试，单位秒 |
| `HTTP_MAX_CONNECTIONS` | `32` | 每个进程的 DRF 与模型提供方各有独立连接池，每个池的总连接数与空闲连接数均受此值限制。DRF 以连接池限制并发 |
| `UPSTREAM_CONCURRENCY` | `16` | 每个进程同时执行的模型分析和流式生成上限 |
| `UPSTREAM_SLOT_TIMEOUT` | `1.0` | 等待模型并发额度或 HTTP 池连接的超时，单位秒 |
| `DRF_MAX_RETRIES` | `2` | 连接失败、连接超时和 5xx 的额外尝试次数，范围 0–5 |
| `LLM_TIMEOUT` | `30` | 分析模型调用总预算及兼容提供方的 HTTP 读写超时，单位秒 |
| `STREAM_TIMEOUT` | `90` | 整条流式生成的总预算，单位秒 |
| `STREAM_PING_INTERVAL` | `10` | 流式心跳间隔，单位秒 |
| `ANALYSIS_CACHE_TTL` | `600` | 分析结果 TTL，单位秒 |
| `MOCK_LLM` | `true` | 使用确定性的 Mock 提供方 |
| `MOCK_LLM_MODE` | `normal` | 支持 `normal`、`slow`、`timeout`、`error`。慢模式等待至少两个心跳间隔 |
| `MOCK_FIRST_DELAY` | `0.15` | Mock 分析和流式首段延迟，单位秒 |
| `MOCK_CHUNK_DELAY` | `0.05` | Mock 段间延迟，单位秒 |
| `MOCK_CHUNKS` | `8` | Mock 回复分段数，范围 1–100 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | 兼容服务 API 根地址，服务追加 `/chat/completions` |
| `LLM_MODEL` | `gpt-4o-mini` | 兼容服务模型名 |
| `LLM_API_KEY` | — | 关闭 Mock 时必填 |

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

真实 Redis 用例需设置 `AUTH_TEST_REDIS_URL` 后运行同一套测试。例如启动 DRF 的测试栈后，将它设为 `redis://127.0.0.1:56379/1`。这些用例使用随机令牌和键，验证撤销状态及分析缓存的读写，并清理各自写入的数据。
