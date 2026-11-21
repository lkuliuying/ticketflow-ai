"""后端 CI 守护测试使用的源码和工作流路径。"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MONOREPO_WORKFLOWS = BACKEND_ROOT.parent / ".github" / "workflows"
WORKFLOW_DIR = (
    MONOREPO_WORKFLOWS
    if BACKEND_ROOT.name == "backend-drf" and MONOREPO_WORKFLOWS.is_dir()
    else BACKEND_ROOT / ".github" / "workflows"
)
