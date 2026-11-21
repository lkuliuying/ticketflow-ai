import { h } from "vue";
import { ElTag } from "element-plus";
import {
  formatPageColumns,
  type PageTableColumn
} from "@/components/RePlusPage";
import type {
  TicketItem,
  TicketPriority,
  TicketSlaState,
  TicketStatus
} from "@/api/ticketflow/tickets";
import type { useI18n } from "vue-i18n";

type TFunction = ReturnType<typeof useI18n>["t"];
type TeFunction = ReturnType<typeof useI18n>["te"];
type TagType = "primary" | "success" | "info" | "warning" | "danger";

export const STATUS_TONE: Record<TicketStatus, TagType> = {
  OPEN: "primary",
  IN_PROGRESS: "warning",
  PENDING_VERIFY: "info",
  CLOSED: "success",
  REOPENED: "danger"
};

export const PRIORITY_TONE: Record<TicketPriority, TagType> = {
  P0: "danger",
  P1: "warning",
  P2: "primary",
  P3: "info"
};

export const SLA_TONE: Record<TicketSlaState, TagType> = {
  ON_TRACK: "success",
  DUE_SOON: "warning",
  OVERDUE: "danger",
  MET: "info"
};

function renderTag(type: TagType | undefined, text: string) {
  return h(
    ElTag,
    { size: "small", type: type ?? "info", effect: "light" },
    () => text
  );
}

/**
 * 工单列表列渲染：状态、优先级、SLA 状态显示为语义色标签；
 * 即将超时与已超时的 SLA 用醒目的实心标签，便于在列表里一眼找出。
 */
export function useTicketColumns({ t, te }: { t: TFunction; te: TeFunction }) {
  const listColumnsFormat = (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      status: column => {
        column["cellRenderer"] = ({ row }) => {
          const status = (row as TicketItem).status;
          const key = `ticketflow.statusValue.${status}`;
          return renderTag(STATUS_TONE[status], te(key) ? t(key) : status);
        };
      },
      category: column => {
        column["cellRenderer"] = ({ row }) => {
          const category = (row as TicketItem).category;
          const key = `ticketflow.categoryValue.${category}`;
          return h("span", te(key) ? t(key) : category);
        };
      },
      priority: column => {
        column["cellRenderer"] = ({ row }) => {
          const priority = (row as TicketItem).priority;
          return renderTag(PRIORITY_TONE[priority], priority);
        };
      },
      sla_state: column => {
        column["cellRenderer"] = ({ row }) => {
          const state = (row as TicketItem).sla_state;
          const urgent = state === "DUE_SOON" || state === "OVERDUE";
          return h(
            ElTag,
            {
              size: "small",
              type: SLA_TONE[state] ?? "info",
              effect: urgent ? "dark" : "plain"
            },
            () =>
              te(`ticketflow.slaValue.${state}`)
                ? t(`ticketflow.slaValue.${state}`)
                : state
          );
        };
      },
      assignee_name: column => {
        column["cellRenderer"] = ({ row }) =>
          h(
            "span",
            (row as TicketItem).assignee_name || t("ticketflow.unassigned")
          );
      }
    });

  return { listColumnsFormat };
}
