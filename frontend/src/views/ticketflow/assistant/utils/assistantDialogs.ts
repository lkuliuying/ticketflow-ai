import { h, ref } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import type { Composer } from "vue-i18n";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import { isSuccess } from "@/api/types";
import { i18n } from "@/plugins/i18n";
import { message } from "@/utils/message";
import {
  assistantSessionApi,
  type AssistantFeedback,
  type FeedbackPayload
} from "@/api/ticketflow/assistant";
import {
  handoffDraft,
  type HandoffDraft
} from "@/api/ticketflow/assistantStream";
import {
  ticketApi,
  type TicketCreatePayload,
  type TicketItem
} from "@/api/ticketflow/tickets";
import FeedbackForm from "../components/FeedbackForm.vue";
import HandoffForm from "../components/HandoffForm.vue";

type FormRef<T> = { getPayload: () => Promise<T | null> };
type HandoffPayload = Omit<TicketCreatePayload, "assistant_session_id">;

const t = (key: string, params: Record<string, unknown> = {}) =>
  (i18n.global as Composer).t(key, params);

/** 点踩弹窗：原因与补充都是可选的；提交成功后关弹层并回传最新反馈 */
export function openDownvoteDialog(
  sessionId: string,
  messageId: string,
  initial: AssistantFeedback | null | undefined,
  onSaved: (feedback: AssistantFeedback) => void
) {
  const formRef = ref<FormRef<FeedbackPayload>>();
  addDialog({
    title: t("ticketflow.assistant.downTitle"),
    width: deviceDetection() ? "100%" : dialogSize("sm"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () => h(FeedbackForm, { ref: formRef, initial }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await formRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      const res = await assistantSessionApi
        .feedback(sessionId, messageId, payload)
        .catch(() => null);
      closeLoading();
      if (res && isSuccess(res) && res.data) {
        message(t("ticketflow.assistant.feedbackSaved"), { type: "success" });
        done();
        onSaved(res.data);
      }
    }
  });
}

/** 草稿生成失败时的兜底：首个问题作标题，整段问题作描述，由员工自行修改 */
export function fallbackDraft(questions: string[]): HandoffDraft {
  const first = questions[0]?.trim() ?? "";
  return {
    title: first.slice(0, 60),
    description: questions.join("\n\n"),
    category: "OTHER"
  };
}

/** 取转人工草稿；失败（含 Mock 之外的上游错误）时用兜底草稿并提示 */
export async function loadHandoffDraft(
  sessionId: string,
  questions: string[]
): Promise<HandoffDraft> {
  const draft = await handoffDraft(sessionId).catch(() => null);
  if (draft && draft.title) return draft;
  message(t("ticketflow.handoff.draftFailed"), { type: "warning" });
  return fallbackDraft(questions);
}

/**
 * 转人工提单弹窗：提交时带上会话 ID，建单与会话关联由服务端在同一事务完成。
 * 成功后会话从员工列表消失（服务端软删除），对话保留在工单里供处理人查看。
 */
export function openHandoffDialog(
  sessionId: string,
  draft: HandoffDraft,
  onCreated: (ticket: TicketItem) => void
) {
  const formRef = ref<FormRef<HandoffPayload>>();
  addDialog({
    title: t("ticketflow.handoff.title"),
    width: deviceDetection() ? "100%" : dialogSize("md"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () => h(HandoffForm, { ref: formRef, initial: draft }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await formRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      const res = await ticketApi
        .create<TicketItem>({ ...payload, assistant_session_id: sessionId })
        .catch(() => null);
      closeLoading();
      if (res && isSuccess(res) && res.data) {
        done();
        onCreated(res.data);
      }
    }
  });
}
