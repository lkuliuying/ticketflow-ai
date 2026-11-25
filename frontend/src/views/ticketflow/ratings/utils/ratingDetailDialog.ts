import { h } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import type { Composer } from "vue-i18n";
import { i18n } from "@/plugins/i18n";
import type { TicketRating } from "@/api/ticketflow/ratings";
import RatingDetailDialog from "../components/RatingDetailDialog.vue";

const t = (key: string, params: Record<string, unknown> = {}) =>
  (i18n.global as Composer).t(key, params);

/** 动态打开评价关联的工单详情抽屉（懒加载避免 ratings ↔ tickets 静态环） */
export async function openRelatedTicket(
  ticketId: string,
  ticketNumber: string
) {
  const { openTicketDetail } =
    await import("../../tickets/utils/ticketDetailDrawer");
  openTicketDetail({ pk: ticketId, number: ticketNumber });
}

/** 打开专用评价详情弹窗（只读，隐藏内部 ID，按语义渲染状态、星级与标签） */
export function openRatingDetailDialog(
  rating: TicketRating,
  options: { canViewTicket?: boolean; fixedHandlerName?: string } = {}
) {
  addDialog({
    title: `${t("ticketflow.rating.detailTitle")} · ${rating.ticket_number}`,
    width: deviceDetection() ? "100%" : dialogSize("md"),
    draggable: true,
    closeOnClickModal: true,
    hideFooter: true,
    contentRenderer: () =>
      h(RatingDetailDialog, {
        rating,
        canViewTicket: options.canViewTicket,
        fixedHandlerName: options.fixedHandlerName,
        onViewTicket: () =>
          void openRelatedTicket(rating.ticket_id, rating.ticket_number)
      })
  });
}
