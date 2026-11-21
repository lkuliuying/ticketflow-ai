import { reactive } from "vue";
import { useI18n } from "vue-i18n";
import { usePageAuth } from "@/router/utils";
import { ticketApi } from "@/api/ticketflow/tickets";
import { useTicketColumns } from "./ticketColumns";

/**
 * 工单列表页：列表、筛选和新建表单由后端元数据驱动。
 *
 * 新建走 `ticketApi.create`，它为每份待提交内容附带 `Idempotency-Key`，
 * 重复提交同一份内容不会生成第二张工单。工单没有通用的编辑和删除接口，
 * 状态变化统一经详情里的流转动作完成。
 */
export function useTickets() {
  const { t } = useI18n();
  const api = reactive(ticketApi);
  const auth = usePageAuth("TicketFlowTickets");

  const { listColumnsFormat } = useTicketColumns({ t });

  return { api, auth, listColumnsFormat };
}
