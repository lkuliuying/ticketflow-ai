import type { TicketStatus } from "@/api/ticketflow/tickets";

/**
 * 流转按钮的动作名：同一目标状态在不同来源状态下语义不同
 * （待验收 → 处理中是“验收退回”，已重开 → 处理中是“恢复处理”）。
 */
export function transitionLabelKey(
  from: TicketStatus,
  to: TicketStatus
): string {
  if (to === "IN_PROGRESS") {
    if (from === "PENDING_VERIFY") return "ticketflow.action.reject";
    if (from === "REOPENED") return "ticketflow.action.resume";
    return "ticketflow.action.accept";
  }
  if (to === "PENDING_VERIFY") return "ticketflow.action.submitVerify";
  if (to === "CLOSED") return "ticketflow.action.close";
  if (to === "REOPENED") return "ticketflow.action.reopen";
  return `ticketflow.statusValue.${to}`;
}

/** 主操作用强调色，退回与重开用警示色 */
export function transitionButtonType(
  from: TicketStatus,
  to: TicketStatus
): "primary" | "success" | "warning" {
  if (to === "CLOSED") return "success";
  if (to === "REOPENED" || (from === "PENDING_VERIFY" && to === "IN_PROGRESS"))
    return "warning";
  return "primary";
}

/** 时间线日志动作名 */
export function logActionKey(action: string): string {
  const known = [
    "CREATE",
    "ASSIGN",
    "AUTO_ASSIGN",
    "REOPEN_ASSIGN",
    "RETURN",
    "TRANSITION",
    "AI_METADATA"
  ];
  return known.includes(action)
    ? `ticketflow.log.${action}`
    : "ticketflow.log.OTHER";
}
