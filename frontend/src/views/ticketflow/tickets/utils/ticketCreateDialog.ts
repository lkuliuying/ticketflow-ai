import { h, ref } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import {
  ticketApi,
  type TicketCreatePayload,
  type TicketItem
} from "@/api/ticketflow/tickets";
import TicketCreateForm from "../components/TicketCreateForm.vue";

type FormRef = { getPayload: () => Promise<TicketCreatePayload | null> };

export function openTicketCreateDialog(options: {
  title: string;
  createdText: string;
  onCreated?: (ticket: TicketItem) => void;
}) {
  const formRef = ref<FormRef>();
  addDialog({
    title: options.title,
    width: deviceDetection() ? "100%" : dialogSize("md"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () => h(TicketCreateForm, { ref: formRef }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await formRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      const res = await ticketApi.create(payload).catch(() => null);
      closeLoading();
      if (res && isSuccess(res)) {
        message(options.createdText, { type: "success" });
        done();
        options.onCreated?.(res.data);
      }
    }
  });
}
