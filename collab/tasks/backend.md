# 后端任务书（Codex）

迭代 2 的任务（BE-01~BE-04、IT-01、CI-01、CI-03）已完成；迭代 3 的 SV-01、SV-02 在文末。

工作目录 `backend-drf/`，遵循 `backend-drf/AGENTS.md`。契约基线是
[Phase 1 设计评审](../../backend-drf/docs/plans/ticketflow-phase-1.md)。顺序：BE-02 优先（阻塞前端），
BE-01 可并行；BE-03、BE-04 在 BE-01 之后。

通用完成标准：

- 新行为有守护测试，缺陷修复先写复现用例；在真实 PG + Redis 测试栈下跑过。
- 提交前跑完 `backend-drf/AGENTS.md` 第六节门禁，报告里贴结果。
- 改了种子：`load_init_json --check` 0 error，`sync_menu_permissions --dry-run` 缺口 0。
- 改了响应结构：先改 `docs/schema/`，报告里写明前端需要同步的字段。

---

## BE-01 测试环境与全量门禁基线

分支：`be/test-baseline`

本机是 Windows，`docker` 不在 Git Bash 的 PATH 中。在 WSL2 或 Docker Desktop 下：

1. 起 `compose.test.yml`，跑 `uv run pytest -n auto` 全量，以及
   `uv run pytest tests/integration/tickets tests/unit/system/test_seed_ownership.py -n 0`。
2. 跑完整门禁清单和覆盖率（CI 要求 `--cov-fail-under=85`）。
3. 查看 GitHub Actions 上 `main` 最近一次推送触发的 Test / Lint 结果（`gh run list --branch main`），
   工作流已改为在 `backend-drf` 下执行，这是第一次实跑。
4. 修复因 Monorepo 迁移导致的失败（路径、工作目录、缓存键等）。与本次二开无关的上游既有失败
   只记录、不修。

完成标准：报告列出每条命令和结果；所有迁移相关失败已修复或说明原因。

---

## BE-02 前端所需的契约补口

分支：`be/contract-gaps`。**前端 FE-02 / FE-03 依赖本任务，请优先做。**

1. **当前用户能力**。`GET /api/tickets/{id}` 增加 `viewer` 对象，前端据此决定显示哪些操作，
   不在前端重算权限：

   ```json
   "viewer": {
     "can_handle": true,
     "can_assign": true,
     "can_comment_internal": true,
     "can_archive": false
   }
   ```

   - `can_handle` 即 `TicketAccess.can_handle`。
   - `can_assign` = `can_handle` 且持有 `assign:TicketFlowTickets` 权限点。
   - `can_comment_internal` = `can_handle`。
   - `can_archive` = 能从该工单转存知识库草稿：状态为 `CLOSED`、`can_handle`、持有知识库创建权限、
     且尚未转存过。
   - `available_transitions` 保留不变。

2. **指派候选人**。新增 `GET /api/tickets/{id}/assignees?q=`：返回可被指派该工单的活跃用户
   （客服或管理员角色；非管理员只返回本部门成员），最多 20 条，字段
   `{pk, username, nickname, department_name}`。权限点与 `assign` 动作同级登记。

3. **知识库当前用户能力**。`GET /api/knowledge/articles/{id}` 增加
   `viewer: {can_edit, can_publish}`；列表响应的顶层或每行给出 `can_create_standalone`
   （是否可创建不关联工单的文章），二选一，写进契约即可。

4. **菜单目录**。新增 `TicketFlow` 目录菜单（`menu_type` 为目录），把“工单”“知识库”两个页面
   挂到它下面，排序工单在前。前端路由组件路径保持 `ticketflow/tickets/index`、
   `ticketflow/knowledge/index` 不变。

5. 更新 `docs/schema/ticketflow.schema.json` 和 `openapi.json`，补集成测试：三种角色下 `viewer`
   的取值、候选人的部门范围、看不到的工单返回 404。

完成标准：报告里给出新增字段的示例响应，方便前端直接对接。

---

## BE-03 Phase 2 测试补全

分支：`be/phase2-tests`（从 `be/ci-hang` 切出，已包含 BE-04、CI-03 的改动与共享夹具 `seeded_module`）。

先盘点 BE-02 / BE-04 / CI-03 已补的用例，只补仍然缺失的场景，避免重复。按下面补齐，优先覆盖权限和并发：

- **知识库权限组合**：requester / agent / admin 分别对 DRAFT、PUBLISHED、ARCHIVED 的列表、
  详情、PATCH；非创建者、非管理员拿不到 `source_ticket_id`；客服只能从可处理的 CLOSED 工单转存，
  同一工单第二次转存返回 409。
- **工单 API**：同一幂等键相同请求返回 200 和原工单，不同请求返回 409，缺失键返回 400；
  过期版本返回 409；看不到返回 404、看得到但无动作返回 403；对外回复写入 `first_response_at`，
  内部备注不写；requester 看不到内部备注和 `internal` 日志。
- **时间线**：超过 20 条时第一页和 `/timeline` 分页的顺序、总数一致。
- **看板**：写入工单后缓存失效；不同用户的范围互不串。
- **导出**：`export-async` 在任务里按提交者当前权限重放筛选（降级角色后导出范围随之缩小）。
- **ai-context**：无 `can_handle` 返回 403；只返回 PUBLISHED 文章片段；字段权限裁掉必要字段时返回 403。
- **查询计数**：列表和详情用固定数据量断言查询次数，防止 N+1。
- **限流**：超限返回 429 并带 `Retry-After`；Redis 不可用返回 503。

完成标准：上述场景都有用例；覆盖率不低于 85%。

---

## BE-04 Phase 2 遗留问题修复

分支：`be/phase2-fixes`

1. **知识维护角色**：新增 `ticketflow_kb_editor` 角色，拥有草稿审阅、发布、归档权限，
   不再与 `ticketflow_admin` 共用。`ticketflow_admin` 仍保留全部权限。同步种子、授权和测试。
2. **浏览计数**：只有 PUBLISHED 文章的详情访问计入 `view_count`。
3. **知识检索性能**：`references_for` 当前对正文做 `icontains` 全表扫描。为 `title` 和
   `body_markdown` 增加 `pg_trgm` GIN 索引（扩展创建按迁移纪律放在链首、失败只告警），
   用 `EXPLAIN` 验证命中。
4. **门禁误报**：`check_menu_titles.py` 会扫到 `backend-drf/tmp/` 下的第三方缓存。
   让门禁脚本排除 `tmp/`，不要依赖手动删除目录。
5. **Renovate**：`renovate.json` 已随迁移进入子目录，根目录缺少配置。在根目录补一份覆盖
   `backend-drf/`（uv）和 `frontend/`（pnpm）的配置，保留原有分组和调度规则。

6. **筛选项标签**（联调发现）：`TicketFilter.sla` 的选项是 `(state, state)`，前端下拉显示 `OVERDUE` 等英文原值。
   给 `ON_TRACK` / `DUE_SOON` / `OVERDUE` / `MET` 配中文标签（正常 / 即将超时 / 已超时 / 按时完成），
   并检查 `assignee_id`、`department_id` 筛选的 label 是否需要中文名。

决定：**分类暂时保持 `TextChoices`**，不迁移到业务字典。在设计文档的已知限制里写一句即可。

完成标准：每项都有对应测试或验证命令输出。

---

## IT-01 联调环境（BE-02 + FE-01）

分支：`be/contract-gaps`。**本任务只起环境、造数据，不改业务代码**；发现缺陷先记进报告，只有阻塞联调时才在该分支修复并说明。

Claude 会在主检出起前端 dev server（`:8848`），它把 `/api`、`/media`、`/api-docs` 代理到 `http://127.0.0.1:8896`，`/ws` 代理到 `ws://127.0.0.1:8896`。

1. **后端开发栈**：在 `F:\Program\ticketflow-ai-be\backend-drf` 的代码上起一个可从宿主访问的后端，入口 `http://127.0.0.1:8896`，
   HTTP 与 `/ws` 都要通。方式自选（`docker-compose.yml` 开发栈，或复用 BE-02 用过的 `nineaiyu/xadmin-server:5.0.2` 镜像挂载代码），
   用一个**独立的开发库**，不要动测试栈的数据库，也不要依赖测试设置（`settings_real` 等）。容器以后台方式常驻，报告里写清楚如何停止与重启。
   Celery worker / beat 能起就起；起不了要写明影响（异步导出、SLA 扫描不可用）。
2. **初始化**：`migrate`、`load_init_json`，`config.yml` 的 `XADMIN_APPS` 包含 `tickets`、`knowledge`。
3. **联调账号**（只用于本机开发库）：
   - `tf_requester`：普通提交人；
   - `tf_agent`：客服，属于默认支持部门，授予指派相关的两个权限点；
   - `tf_agent_other`：客服，属于另一个部门，用于验证部门隔离；
   - `tf_admin`：工单业务管理员（非超级用户）。
   密码随机生成，只写进报告 `collab/reports/IT-01.md`（该目录不进 Git），不要写进代码、种子或提交。
4. **样例数据**：约 12 张工单，覆盖 5 种状态、P0–P3、SLA 的 `ON_TRACK` / `DUE_SOON` / `OVERDUE` / `MET`，
   分属两个部门，部分已指派；若干对外回复和内部备注；2 篇已发布文章、1 篇草稿；至少 1 张已关闭且未转存的工单。
   造数据走服务层或 API，保证版本号、日志和 SLA 字段一致。
5. **自检**：`/api/common/api/health` 返回正常；四个账号都能经 `/api/identity/login/basic` 登录（如登录需要验证码，写明联调时如何通过，
   例如开发库关闭登录验证码的配置项）；用 `tf_agent` 请求一张工单详情，贴出 `viewer` 和 `available_transitions`。

完成标准：报告给出访问地址、四个账号及其角色/部门、数据清单（每张工单的号、状态、优先级、SLA、部门、处理人）、
启停命令、自检的实际输出，以及已知限制。

---

## CI-01 让 GitHub CI 在 Monorepo 下转绿（后端）

分支：`be/ci-green`（从最新 `main` 切出）。

GitHub 上首次运行 `Unit Tests`（run 44876442261）结果为 **21 failed / 7890 passed**，失败清单原文在
`F:\Program\ticketflow-ai\collab\reports\CI-01.ci-failures.txt`。没有功能缺陷，都是 Monorepo 迁移与新增
`tickets` / `knowledge` 应用后，上游守护测试未同步：

1. **工作流路径（8 项）**：`test_server_params`、`test_coverage_gate`、`test_dependency_manifest`、`test_kernel_release`
   在 `backend-drf/.github/workflows/` 下找文件，实际已在仓库根目录 `.github/workflows/`。让这些测试按 Monorepo 布局解析
   路径（后端根目录的上一级），单仓布局时仍能工作更好；不要复制工作流文件。
2. **新应用登记（12 项）**：AI 工具审计未登记缺口（`api/tickets`、`api/knowledge/articles` 的读写端点需按既有分级登记）、
   种子角色清单（`ticketflow_requester` / `ticketflow_agent` / `ticketflow_admin`）、字段权限种子角色引用、
   各角色菜单规模快照、模块数量（21 → 23）、`generate_module` 发现逻辑、种子计划顺序与覆盖计数、`init_config` 脚本行数等。
   **按各守护的设计意图正式登记或更新快照，不要放宽或删除守护本身**；每一项在报告里写清楚改的是登记、快照还是代码。
3. **导航菜单标题（1 项）**：目录与页面菜单（`menu_type` 0 / 1）的 `title` 必须是 i18n key。统一为：
   - `TicketFlow` → `menus.ticketflow`
   - `TicketFlowTickets` → `menus.ticketflowTickets`
   - `TicketFlowKnowledge` → `menus.ticketflowKnowledge`
   前端词条由 Claude 在 CI-02 补齐（zh：TicketFlow / 工单 / 工单知识库）。按钮级权限点（`menu_type` 2）的标题保持中文。

不在本任务范围：前端 `check-menu-permissions` 报的 `assignees:TicketFlowTickets` 无前端消费（CI-02 处理）。

完成标准：在 Linux 容器里跑 `uv run pytest -n auto` 全量通过（或只剩与本次无关、且在上游同样失败的用例，逐条说明），
`--cov-fail-under=85` 满足，第六节门禁通过；报告附上全量结果的统计行。

---

## CI-03 修复 CI 中 Unit Tests 卡死（关闭 BE-01）

分支：`be/ci-hang`（从 `be/phase2-fixes` 切出，因为 BE-04 也改了 `test_viewer_contract.py`，避免合并冲突）。

GitHub `Unit Tests`（run 44880995609）在全量约 48% 处卡住：两次尝试都触发 faulthandler 600s 转储后 Abort，第三次整体超时。
栈与上下文在 `F:\Program\ticketflow-ai\collab\reports\CI-03.ci-hang.txt`。卡点：

```
tests/integration/tickets/test_viewer_contract.py:29  users 夹具 → call_command("load_init_json")
  → identity/builtin.py:135 sync_builtin_roles → :150 _fill_builtin_role_fields
  → system/services/permission_sync/apply.py:303 fill_field_permissions
  → system/services/permission_sync/audit.py:64 audit_field_permissions   ← psycopg 等待查询返回
```

同一进程里还有 psycopg_pool 的 worker 线程。初步判断：`load_init_json` 的某段查询走了与测试事务不同的连接，
等待测试事务尚未提交的行锁，形成同进程自锁；本地四 worker 没有复现卡死，但出现过 `Cannot release a lock that's no longer owned`。

要求：

1. 先在 Linux 容器里按 CI 口径复现（`tests/settings_real.py`、xdist、真实 PG + Redis），确认根因（连接池、跨连接查询、锁等待），
   不要只靠加超时或跳过用例。
2. 修复方向优先改测试夹具（例如改为会话级只装载一次种子、或不在事务内调用整条 `load_init_json`，只建所需角色与授权），
   若根因在 `load_init_json` / 权限同步对连接的使用方式，说明影响面后再改。
3. 全量 `uv run pytest -n auto`（CI 同口径）通过，且 `tests/integration/tickets` 在 `-n 4` 下连续跑 3 次不再卡住。
4. 报告附根因分析与复现、修复前后的关键输出。

### BE-04 第 1 轮评审跟进（CI-03 完成后在同一分支处理）

1. `knowledge/migrations/0003_article_trigram_indexes.py`：回滚时先检查索引是否存在（或 `DROP INDEX IF EXISTS`），
   覆盖“无 `pg_trgm` 权限时正向迁移跳过建索引”的环境。
2. 根目录 `renovate.json`：并入 `frontend/renovate.json` 的 4 条 `packageRules`（用 `matchFileNames: ["frontend/**"]` 限定）
   与 `postUpdateOptions`，后端规则限定到 `backend-drf/**`；删除 `backend-drf/renovate.json`。`frontend/renovate.json` 由 Claude 删除。
   Django 规则说明里的 `docs/adr` 改为 `backend-drf/docs/adr`。
3. `TicketFilter.sla` 补 `label="SLA 状态"`，`q` 补 `label="关键字"`。

---

# 迭代 3：FastAPI 异步 AI 服务（Phase 3）

两个任务在同一分支 `be/ai-service`（从最新 `main` 切出）上顺序完成，SV-02 在 SV-01 评审通过后开始。
代码放在仓库根目录 `service-fastapi/`（任务书明确允许改这个目录、根目录 `.github/workflows/` 中新增的服务工作流，
以及 `backend-drf/` 里为联调所需的最小配置）。设计依据是 Phase 1 设计评审的“API 契约”“JWT 联合鉴权”
“FastAPI 与前端接线”三节，契约以那里为准；有必须偏离的地方，先在报告里写明理由。

通用要求：

- 独立依赖锁：`service-fastapi/pyproject.toml` + `uv.lock`，与 `backend-drf` 互不引用。Python 版本与后端一致。
  依赖控制在 FastAPI、uvicorn、httpx、redis（asyncio）、pydantic v2 / pydantic-settings、PyJWT 这一级，测试用 pytest、
  pytest-asyncio（或 anyio）、respx 或 httpx `MockTransport`。
- 目录：`app/api`（路由）、`app/core`（配置、lifespan、鉴权、错误）、`app/schemas`（Pydantic 模型）、`app/services`
  （DRF 客户端、提供方、缓存）。单文件 ≤ 500 行、单函数 ≤ 100 行，沿用后端的这条约定。
- 配置全部来自环境变量（`pydantic-settings`），不写死密钥；提供 `service-fastapi/.env.example`（只放占位值）。
- 测试用真实 Redis（后端测试栈 `compose.test.yml` 的 56379，或服务自己的 compose），DRF 用 `MockTransport` / respx 模拟；
  `ruff format --check`、`ruff check`、`mypy`（strict 或接近 strict）、`pytest` 全部通过，报告贴结果。
- 根目录 `.github/workflows/` 新增一个只在 `service-fastapi/**` 变化时触发的工作流：`uv sync --locked`、ruff、mypy、
  pytest（带 Redis service）。不要改动现有后端和前端工作流的行为。
- 源码、注释、测试名里不写任务编号。

## SV-01 FastAPI 骨架、联合鉴权与健康检查

分支：`be/ai-service`

1. **应用与 lifespan**：`app/main.py` 创建应用，lifespan 内建立整个进程复用的 `httpx.AsyncClient`（分别设置连接、
   读取、总超时与连接池上限）、`redis.asyncio` 客户端（连 DRF 认证用的同一个逻辑库，由配置 `AUTH_REDIS_URL` 指定，
   语义对应 DRF 的 `DEFAULT_CACHE_ID`，默认 1）以及上游并发信号量（容量可配），关闭时释放。路由前缀 `/ai/v1`。
2. **鉴权依赖 `get_current_user`**：完全按设计文档“JWT 联合鉴权”实现：
   - PyJWT 固定 `algorithms=["HS256"]`，校验 `aud="x"`、`iss="server"`、`exp`、`iat`、`jti`、`user_id`，`token_type == "access"`，
     leeway 0；签名密钥来自 `JWT_SIGNING_KEY`（与 DRF 的 `SIMPLE_JWT.SIGNING_KEY` 同值）。缺少 `sid` 的旧 token 允许通过。
   - 一次 `MGET` 读取三个撤销键：`black_access_token_{user_id}_{md5(raw_token)}`、`user_token_revoked_{user_id}`
     （存在有效时间戳且 `iat <= revoked_at` 时拒绝）、`session_token_revoked_{sid}`（有 `sid` 时）。
     先读 `backend-drf/packages/xadmin-common/common/core/auth/authentication.py` 和 `common/cache/storage.py`，
     **按 DRF 实际写入的值格式解析**（Django 缓存的序列化方式、键是否带前缀和版本），并在报告里写明依据。
   - 认证 Redis 超时或异常返回 503；任一校验失败返回 401。
3. **错误信封**：建流前的所有错误统一为 `{code, error, detail}`（`code` 为 HTTP 状态码整数，`error` 为机器可读标识），HTTP 状态码按设计文档（401 / 403 / 404 / 422 / 503 / 504）。
   重写 FastAPI 默认的 422 和 HTTPException 输出，`detail` 为字符串。
4. **`GET /ai/v1/health`**：不需要 token，Redis `PING` 正常返回 200 `{status: "ok", redis: "ok"}`，否则 503。
5. **DRF 上下文客户端**：`services/drf.py` 用同一个 `AsyncClient` 转发用户原始 Bearer token 调用
   `GET {DRF_BASE_URL}/api/tickets/{id}/ai-context`，把 DRF 的 401 / 403 / 404 / 429 / 5xx 映射到服务的 `{code, detail}`
   （429 透传 `Retry-After`），连接失败或超时返回 503 / 504。只对短暂连接错误和 5xx 做有上限的带抖动指数退避，
   等待期间不占用上游信号量。解析为 Pydantic 模型（工单 `id/title/description/category/priority/version`、
   `categories`、`references[{article_id, title, excerpt}]`）。本任务先实现并测试客户端，SV-02 的接口再用它。
6. **测试**：用测试内签发的 token 覆盖：合法 access 通过；refresh token、过期、`iat` 在未来、错误 `aud` / `iss`、
   错误算法（包括 `none`）、缺 `jti` 都 401；三个撤销键各自生效；Redis 不可达返回 503；health 正常与 Redis 断开；
   DRF 客户端的状态码映射与重试次数。
7. **启动方式**：`uv run uvicorn app.main:app --port 8897` 可在宿主机启动；提供 `service-fastapi/Dockerfile`
   （多阶段、非 root）。README 写清环境变量。

完成标准：上述测试与门禁通过；报告给出各错误路径的示例响应和撤销键值格式的依据。

## SV-02 工单分析、流式回复、提供方与联调常驻

分支：`be/ai-service`（接着 SV-01 的提交继续）

在 SV-01 的基础上：

1. **提供方抽象**：`LLMProvider` 协议，两个方法：`analyze(context) -> AnalysisDraft`、`stream_reply(context) -> AsyncIterator[str]`。
   - `MockProvider`（`MOCK_LLM=true`，默认）：结果由工单文本确定性生成（分类从 `categories` 中选、优先级 P0–P3、
     摘要与 2–5 个标签，长度在 Pydantic 限制内），可配置首字延迟、段间延迟、段数，以及 `MOCK_LLM_MODE=normal|slow|timeout|error`
     模拟慢响应、超时和上游错误。用 `asyncio.sleep`，不阻塞事件循环。
   - `OpenAICompatibleProvider`：OpenAI 兼容的 chat completions（`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`），分析用 JSON 输出
     再经 Pydantic 校验，流式解析上游 SSE。没有密钥时不可选；CI 和联调只跑 Mock，但要有用 `MockTransport` 模拟上游的单测。
   - 两种提供方共用同一套验权、信号量、超时与错误映射，提供方之外的代码不区分 Mock。
   - 模型输入只包含 `ai-context` 返回的工单文本和知识片段；提示词放在单独模块并带 `PROMPT_VERSION`。
2. **`POST /ai/v1/tickets/analyze`**，请求 `{ticket_id: UUID}`：
   - 鉴权 → 调 DRF `ai-context`（缓存命中时也必须先调，以确认授权）→ 查缓存 → 未命中时在信号量内调提供方 → Pydantic v2 校验 →
     写缓存 → 返回 `{ticket_id, ticket_version, category, suggested_priority, summary, tags}`。
   - 校验：`category` 必须在本次上下文的 `categories` 内，`suggested_priority` ∈ P0–P3，`summary` 有长度上限，`tags` 为去重后的
     有限个短字符串（上限与 DRF `POST /api/tickets/{id}/ai-metadata` 的校验一致，先读 DRF 序列化器）。提供方返回不合法时返回 502 或 503
     （在报告里说明选择），不写缓存。
   - 缓存键绑定：用户 ID、规范化文本摘要（标题 + 描述 + 分类，去除空白与格式差异后哈希）、分类词表版本（对 `categories` 取哈希）、
     模型名、`PROMPT_VERSION`；TTL 默认 600 秒；只缓存校验通过的结果；响应里的 `ticket_id`、`ticket_version` 用本次上下文的值。
     缓存 Redis 故障时直接回源，不影响分析。
   - 等待信号量与调用提供方分别有超时预算：等不到槽位返回 503，提供方超时返回 504。
3. **`POST /ai/v1/tickets/suggest-reply/stream`**，请求 `{ticket_id: UUID}`，`text/event-stream`：
   - 建流前（鉴权、DRF 上下文、等待槽位）的错误按 `{code, error, detail}` JSON 返回对应状态码，不开流。
   - 帧格式 `event: <name>\ndata: <json>\n\n`，事件顺序：`meta`（`{ticket_id, ticket_version, references: [article_id...]}`）→
     零到多个 `delta`（`{text}`）→ `done`（`{finish_reason}`）；建流后失败以 `error`（`{code, error, detail, retryable}`，`code` 为整数）结束；
     等待但没有增量超过心跳间隔（可配，默认 10 秒）时发 `ping`。
   - 响应头带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。
   - 客户端断开时停止生成、关闭上游响应并**释放信号量**；整条流有总时长上限。第一段正文发出之前允许对上游做一次重试，之后不重试。
4. **测试**：分析的缓存命中 / 未命中 / 键随文本、用户、词表、提示词版本变化 / DRF 拒绝时缓存不生效；非法提供方输出不入缓存；
   信号量占满时的 503；提供方超时 504；SSE 帧序（含 ping、error 结尾）；**客户端中途断开后信号量计数恢复**（用断言而不是 sleep 猜测）；
   OpenAI 兼容提供方的 JSON 解析与流式解析。
5. **联调常驻**（不改 DRF 业务代码）：在本机起一个常驻的 FastAPI（`MOCK_LLM=true`），地址 `http://127.0.0.1:8897`，
   使用联调环境 `ticketflow-local` 的 DRF（`http://127.0.0.1:8896`）与其 Redis 认证库，`JWT_SIGNING_KEY` 与联调 DRF 一致
   （必要时在联调环境的 `config.yml` 显式配置同一个 `JWT_SIGNING_KEY` 并重启 DRF；只改联调配置，不提交密钥）。
   方式自选（加入 `ticketflow-local` 的 compose 网络，或宿主机进程常驻），报告写清启停命令。
   Mock 的首字延迟和段间延迟在联调时设成肉眼可见的值（例如首字 600ms、段间 120ms、约 20 段）。
6. **联调自检**（贴实际输出）：
   - 用 `tf_agent` 经 `/api/identity/login/basic` 登录取得 access，`curl -N` 调分析与流式接口，贴响应和帧序；
   - refresh token 调用返回 401；`/api/identity/logout` 之后原 access 返回 401；对该用户执行“踢下线”（撤销全部 token）后返回 401；
   - `tf_requester` 对自己提交的工单调用返回 403（不具备处理权限），看不到的工单返回 404；
   - 停掉联调 Redis 或改错地址时 health 与鉴权返回 503（验证后恢复）。

完成标准：上述测试与门禁通过，联调常驻可用；报告附帧序样例与自检输出，写明前端需要的接口细节（地址、事件字段）。
