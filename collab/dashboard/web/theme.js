// 场景与界面共用的颜色、阶段与文案。

export const AGENT_COLORS = {
  claude: "#f2a65a",
  codex: "#4fd1a5",
  gemini: "#6aa8ff",
  human: "#c9d3e6"
};

export const STAGE_COLORS = {
  待开始: "#7d8aa3",
  阻塞: "#c46b84",
  执行中: "#f2c14e",
  待评审: "#b48cff",
  评审中: "#6aa8ff",
  需修改: "#ff6b6b",
  已通过: "#4fd1a5",
  已合并: "#9be37b"
};

export const STAGE_HINT = {
  待开始: "任务书已下发，等待执行者领取",
  阻塞: "依赖的任务尚未通过评审",
  执行中: "执行者正在分支上实现与自测",
  待评审: "完成报告已提交，等待 Gemini",
  评审中: "agy 正在只读评审分支 diff",
  需修改: "评审给出阻断项，退回执行者",
  已通过: "评审 APPROVE，等待用户确认合并",
  已合并: "已合入 main"
};

export const STATE_LABEL = {
  running: "运行中",
  idle: "空闲",
  error: "异常",
  waiting: "等待中"
};

export const STAGE_OWNER = {
  待开始: "claude",
  阻塞: "claude",
  执行中: null,
  待评审: "gemini",
  评审中: "gemini",
  需修改: null,
  已通过: "claude",
  已合并: "claude"
};

export function ownerOf(task) {
  return STAGE_OWNER[task.stage] ?? task.agent;
}

export function shortTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

export function relTime(iso, now = Date.now()) {
  if (!iso) return "—";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 5) return "刚刚";
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.round(s / 3600)} 小时前`;
  return `${Math.round(s / 86400)} 天前`;
}

export function esc(text) {
  return String(text ?? "").replace(
    /[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}
