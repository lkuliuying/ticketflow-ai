// 场景与界面共用的颜色、阶段与文案。

export const AGENT_COLORS = {
  claude: "#e07a3f",
  codex: "#1f9d75",
  gemini: "#3b7ddd",
  human: "#8a94a6"
};

export const STAGE_COLORS = {
  待开始: "#94a3b8",
  阻塞: "#e0607e",
  执行中: "#f0a92e",
  待评审: "#9b7be0",
  评审中: "#4a8fe7",
  需修改: "#ef5b5b",
  已通过: "#2fb383",
  已合并: "#6cbf4a"
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
