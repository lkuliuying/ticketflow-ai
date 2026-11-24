import { h, ref } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import type { Composer } from "vue-i18n";
import { i18n } from "@/plugins/i18n";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";
import type { RatingPayload } from "@/api/ticketflow/ratings";
import RatingForm from "../components/RatingForm.vue";

type FormRef = { getPayload: () => Promise<RatingPayload | null> };

/** 组件外翻译（legacy: false 下 global 为 Composer） */
const t = (key: string, params: Record<string, unknown> = {}) =>
  (i18n.global as Composer).t(key, params);

/**
 * 打开工单评价弹窗。关闭时自动弹出的场景传 `afterClose`，标题提示可以稍后在详情里补评。
 * 先 done() 关弹层再回调刷新，失败时保持弹层便于修改（409 已评价等由拦截器提示）。
 */
export function openRatingDialog(
  ticket: Pick<TicketDetail, "pk" | "number" | "assignee_name">,
  options: { afterClose?: boolean; onRated?: () => void } = {}
) {
  const formRef = ref<FormRef>();
  addDialog({
    title: options.afterClose
      ? t("ticketflow.rating.afterCloseTitle")
      : t("ticketflow.rating.title", { number: ticket.number }),
    width: deviceDetection() ? "100%" : dialogSize("md"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () =>
      h(RatingForm, { ref: formRef, handlerName: ticket.assignee_name }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await formRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      const res = await ticketApi.rate(ticket.pk, payload).catch(() => null);
      closeLoading();
      if (res && isSuccess(res)) {
        message(t("ticketflow.rating.submitted"), { type: "success" });
        done();
        options.onRated?.();
      }
    }
  });
}
