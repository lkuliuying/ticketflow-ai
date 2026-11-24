import type { Component } from "vue";
import {
  AlarmClock,
  Clock,
  Finished,
  Histogram,
  RefreshLeft,
  Tickets,
  User,
  Warning
} from "@element-plus/icons-vue";
import type { TicketDashboard } from "@/api/ticketflow/tickets";
import type { WorkbenchStats } from "./useWorkbench";

/** 工作台视角：由看板返回的指派维度推断（管理员有 unassigned，技术员有 current），不硬编码角色名 */
export type WorkbenchRole = "admin" | "agent" | "requester";

export type StatCard = {
  key: keyof WorkbenchStats;
  icon: Component;
  tone: "primary" | "warning" | "info" | "danger" | "success";
  /** 点击后带到工单列表的看板筛选，与计数口径一一对应 */
  query: Record<string, string>;
};

export function workbenchRole(data: TicketDashboard | null): WorkbenchRole {
  const assignment = data?.assignment ?? {};
  if (assignment.unassigned !== undefined) return "admin";
  if (assignment.current !== undefined) return "agent";
  return "requester";
}

const CARD: Record<keyof WorkbenchStats, StatCard> = {
  unassigned: {
    key: "unassigned",
    icon: User,
    tone: "danger",
    query: { assignment: "unassigned" }
  },
  current: {
    key: "current",
    icon: Tickets,
    tone: "primary",
    query: { assignment: "current" }
  },
  history: {
    key: "history",
    icon: Histogram,
    tone: "info",
    query: { assignment: "history" }
  },
  open: {
    key: "open",
    icon: Tickets,
    tone: "primary",
    query: { status: "OPEN" }
  },
  reopened: {
    key: "reopened",
    icon: RefreshLeft,
    tone: "danger",
    query: { status: "REOPENED" }
  },
  inProgress: {
    key: "inProgress",
    icon: Clock,
    tone: "warning",
    query: { status: "IN_PROGRESS" }
  },
  verifying: {
    key: "verifying",
    icon: Finished,
    tone: "success",
    query: { status: "PENDING_VERIFY" }
  },
  dueSoon: {
    key: "dueSoon",
    icon: AlarmClock,
    tone: "warning",
    query: { sla: "DUE_SOON" }
  },
  overdue: {
    key: "overdue",
    icon: Warning,
    tone: "danger",
    query: { sla: "OVERDUE" }
  }
};

const ROLE_CARDS: Record<WorkbenchRole, (keyof WorkbenchStats)[]> = {
  admin: [
    "unassigned",
    "open",
    "inProgress",
    "verifying",
    "dueSoon",
    "overdue"
  ],
  agent: [
    "current",
    "history",
    "inProgress",
    "verifying",
    "dueSoon",
    "overdue"
  ],
  requester: ["open", "inProgress", "verifying", "reopened"]
};

export function cardsFor(role: WorkbenchRole): StatCard[] {
  return ROLE_CARDS[role].map(key => CARD[key]);
}
