# TicketFlow AI

TicketFlow AI 是基于 xadmin 的智能工单与知识库协作平台。

| 目录 | 内容 |
| --- | --- |
| [backend-drf](backend-drf/) | Django / DRF 业务、权限、Celery 任务和后端测试 |
| [frontend](frontend/) | xadmin-client 的 Vue 3 / Element Plus 界面 |
| `service-fastapi/` | Phase 3 的异步 AI 服务 |
| `deploy/` 和 `tests/` | Phase 5 的统一入口、验收和压测 |

以 [Phase 1 设计评审](backend-drf/docs/plans/ticketflow-phase-1.md) 为实现基线。后端的开发与测试命令在 `backend-drf/` 执行，前端命令在 `frontend/` 执行。

## Phase 2 后端启动与验证

后端底座依赖 Linux 文件锁。在 Windows 上从 WSL 或 Docker 运行。开发配置沿用 [config_example.yml](backend-drf/config_example.yml)，`XADMIN_APPS` 包含 `tickets` 和 `knowledge`。首次启动前填写数据库、Redis 和站点配置。若需要按工单分类路由到其他部门，在配置中填写部门 UUID。

```bash
cd backend-drf
bash ops/dev_up.sh --backend-only --hot
docker compose exec server python manage.py load_init_json --check
docker compose restart server celery-worker celery-heavy celery-beat
curl -fsS http://127.0.0.1:8896/api/common/api/health
```

种子会建立默认支持部门以及工单提交人、处理人和管理员角色。默认角色也可提交工单和阅读已发布的知识库。为处理人设置对应部门，即可用不同角色账号验证数据隔离。

默认 SLA 时限分别为 P0 2 小时、P1 8 小时、P2 24 小时、P3 72 小时，距截止 30 分钟开始记录预警。

```bash
docker compose -f compose.test.yml up -d --wait
uv sync --all-groups
uv run pytest tests/integration/tickets tests/unit/system/test_seed_ownership.py -n 0
```

### 面试复盘

- **工单并发流转**。行锁串行化写操作，版本号判定客户端读到的状态是否过时。状态、版本和审计日志在同一事务提交。
- **建单幂等**。Redis 记录短时占位与完成结果，PostgreSQL 唯一约束是并发和缓存丢失后的防重依据。调用方可用同一个键重试。
- **查询与授权**。角色决定可执行动作，QuerySet 统一限制数据范围。详情预取可见的日志与评论，导出任务按照提交人的当前权限重放筛选。
- **SLA 任务**。Beat 每分钟触发扫描，告警用工单、SLA 轮次和告警类型做唯一约束。重新打开的工单开始新的 SLA 轮次。

底座来源为 [xadmin-server](https://github.com/nineaiyu/xadmin-server) 和 [xadmin-client](https://github.com/nineaiyu/xadmin-client)。上游许可证保留在各组件目录。
