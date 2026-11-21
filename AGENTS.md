# TicketFlow AI 工作区约定

- 后端工作目录为 `backend-drf/`，遵循该目录的 `AGENTS.md`。
- 前端工作目录为 `frontend/`，遵循该目录的 `AGENTS.md`。
- 接口契约、数据范围和阶段边界见 `backend-drf/docs/plans/ticketflow-phase-1.md`。
- Git 与跨服务工作流位于仓库根目录。
- 多代理分工：Claude 负责总指导与 `frontend/`，Codex 负责 `backend-drf/` 开发与测试，Gemini 负责评审。任务书、分支约定和交接流程见 `collab/README.md`，开始工作前先读。
