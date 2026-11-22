# TicketFlow 本地部署

需要运行 Linux 容器的 Docker Engine 或 Docker Desktop、Docker Compose v2 和宿主机 Python 3。首次构建需要访问容器镜像仓库、Debian 软件包源、PyPI 和 npm。镜像在容器里安装 Node 24 和 pnpm 11。以下命令在仓库根目录执行。

Docker Desktop 在 Windows 上未加入 PATH 时，先在 PowerShell 执行：

```powershell
$env:Path = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:Path
```

## 配置和启动

```sh
python deploy/local.py env
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps -a
```

首条命令按 `.env.example` 生成 `deploy/.env`，并填入随机密钥。已有 `.env` 时直接使用它。保留这份文件，以便重启后继续访问数据库和现有会话。`SECRET_KEY` 与 `JWT_SIGNING_KEY` 分开，DRF 和 FastAPI 共用 `JWT_SIGNING_KEY`。自定义 `REDIS_PASSWORD` 时使用字母、数字、下划线和连字符，以便在 Redis 连接 URL 中使用。

交付栈也为 DRF 和 FastAPI 共用 `JWT_LEEWAY_SECONDS`，默认 30 秒。签发时间的超前量和到期时间的宽限期都受此值限制。可在 `deploy/.env` 中设置为非负整数，设为 0 时严格按当前时钟验证。

`LOGIN_THROTTLE_RATE` 控制登录与登录能力查询共用的每 IP 额度。新生成的 `.env` 将该项留空，演示模式使用 `1000/h`，生产模式使用 `50/h`。填写明确的速率可覆盖默认值，修改后执行 `up -d` 重建服务。

网关镜像用 Vite 生产模式加载 `frontend/.env` 与 `frontend/.env.production` 中的公开构建参数。构建上下文只纳入这两个环境文件。请将密钥留在部署侧的 `deploy/.env`。

默认入口是 `http://127.0.0.1:8080`，可以用 `TF_PORT` 改端口。需要监听其他地址时同时配置 `TF_BIND_HOST` 和 `TF_ALLOWED_HOSTS`（逗号分隔的访问主机名，不带端口），并在生产入口配置 HTTPS。交付栈的 Compose 项目名为 `ticketflow`，网关是唯一发布宿主端口的服务。数据库、Redis 和上传文件分别存放在三个命名卷。

短生命周期的 `init` 服务等待 PostgreSQL 和 Redis 健康后执行 `migrate` 和 `load_init_json`。内置种子在空库上使用一个不可登录的审计用户。等 `init` 以状态码 0 退出后，DRF Web、Worker 和 Beat 才会启动。首次启动后可访问以下地址确认就绪：

- 浏览器首页 `http://127.0.0.1:8080/`
- DRF 健康接口 `http://127.0.0.1:8080/api/common/api/health`
- FastAPI 健康接口 `http://127.0.0.1:8080/ai/v1/health`

网关提供 SPA 回退，经 DRF 转发 `/api/`、`/ws/` 和受鉴权的 `/media/`，经 FastAPI 转发 `/ai/`。FastAPI 经 Compose 内网直连 DRF 的工单上下文，网关对该路径返回 404。AI 默认开启 `MOCK_LLM`，需要实际模型时将其设为 `false`，并配置 `LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_KEY`。

网关对 `/api-docs` 和 `/api-docs/` 下的路径返回 404。Mock 回复默认每隔 0.12 秒发送一段，可通过 `MOCK_CHUNK_DELAY` 调整。

## 演示数据

```sh
sh deploy/seed.sh
```

在 Windows PowerShell 可运行等效命令 `python deploy/local.py seed`。命令将随机口令写入 Git 忽略的 `deploy/.accounts.local.json`，随后创建演示账号和数据。凭据文件应留在本地。重复执行会沿用文件内的口令，已经初始化的数据和账号保持原样。文件与数据库中的口令不一致时，命令会退出并保留现有账号。清空卷后还可用原文件重建同样的演示账号。

| 账号 | 身份及范围 |
| --- | --- |
| `tf_requester` | 提交人，仅看本人提交的工单 |
| `tf_agent` | 工单支持客服，有指派和查询指派候选人的权限 |
| `tf_agent_other` | 网络支持客服，用于演示部门隔离 |
| `tf_admin` | 工单业务管理员，可走完整业务流程 |

样例包括 12 张工单（五种状态、四种优先级、两部门），对外回复、内部备注、两篇已发布知识文章和一篇草稿。演示模式 `TICKETFLOW_DEMO=true` 关闭网页登录验证码、登录临时令牌和依赖该令牌的登录字段加密，便于本机演示。生产应从独立空卷部署，设置 `TICKETFLOW_DEMO=false` 并保持这些登录保护开启，同时将 `CAPTCHA_TICKET_AUDIENCE` 设为该站点的 URL 或唯一部署标识。生产管理员使用 `docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec drf-web python manage.py createsuperuser` 交互创建。

## 日志、停止和升级

```sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs --tail=100 init drf-web drf-worker drf-beat ai gateway
docker compose -f deploy/docker-compose.yml --env-file deploy/.env down
```

`down` 保留数据卷。仅在确认要清除整个交付栈数据时运行 `docker compose -f deploy/docker-compose.yml --env-file deploy/.env down -v`。它会删除该项目的 PostgreSQL、Redis 和上传文件卷。

升级前备份 PostgreSQL、上传文件以及 `.env`，然后在新的代码版本下执行 `down` 和 `up -d --build`。启动依赖保证 `init` 跑完迁移并补齐种子后才启动应用。检查 `init` 退出码和健康接口，再开放流量。

## 常见故障

| 表现 | 检查方式 |
| --- | --- |
| 找不到 Docker 或凭据助手 | 确认 Docker Desktop 已启动，并将上面的目录加入当前终端 PATH。 |
| `8080` 被占用 | 修改 `.env` 的 `TF_PORT`，再执行 `up -d`。 |
| 初始化失败或网关迟迟起不来 | 用 `ps -a` 查看依赖状态，用 `logs init postgres redis` 查看失败明细。已有 PostgreSQL 卷内的密码不会随 `.env` 自动改变。 |
| 登录需要验证码或临时令牌 | 核对是否在演示栈设置了 `TICKETFLOW_DEMO=true`，改 `.env` 后用 `up -d` 重建受影响的容器。 |
| AI 接口无法使用当前会话 | 检查 DRF 和 FastAPI 是否由同一份 `.env` 启动，并在刷新或重新登录后重试。 |
