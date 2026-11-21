import { h } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDrawer } from "@/components/ReDrawer";
import { drawerSize } from "@/components/ReDialog/size";
import type { TicketDetail, TicketItem } from "@/api/ticketflow/tickets";
import TicketDetailView from "../components/TicketDetail.vue";

/** 打开工单详情抽屉；写操作成功或遇到冲突后通过 onChanged 通知列表刷新 */
export function openTicketDetail(
  row: Pick<TicketItem, "pk" | "number">,
  options: {
    onChanged?: () => void;
    onArchive?: (_ticket: TicketDetail) => void;
  } = {}
) {
  addDrawer({
    title: row.number,
    size: deviceDetection() ? drawerSize("full") : drawerSize("md"),
    destroyOnClose: true,
    closeOnClickModal: true,
    hideFooter: true,
    contentRenderer: () =>
      h(TicketDetailView, {
        pk: row.pk,
        onChanged: options.onChanged,
        onArchive: options.onArchive
      })
  });
}
