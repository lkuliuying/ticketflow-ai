import { h } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import type { Composer } from "vue-i18n";
import { addDrawer } from "@/components/ReDrawer";
import { drawerSize } from "@/components/ReDialog/size";
import { i18n } from "@/plugins/i18n";
import AssistantTranscript from "../components/AssistantTranscript.vue";

const t = (key: string, params: Record<string, unknown> = {}) =>
  (i18n.global as Composer).t(key, params);

/** 打开工单关联的 AI 对话（只读抽屉） */
export function openAssistantTranscript(ticket: {
  pk: string;
  number?: string;
}) {
  addDrawer({
    title: ticket.number
      ? t("ticketflow.assistant.transcriptTitleWithNumber", {
          number: ticket.number
        })
      : t("ticketflow.assistant.transcriptTitle"),
    size: deviceDetection() ? drawerSize("full") : drawerSize("md"),
    destroyOnClose: true,
    closeOnClickModal: true,
    hideFooter: true,
    contentRenderer: () => h(AssistantTranscript, { ticketId: ticket.pk })
  });
}
