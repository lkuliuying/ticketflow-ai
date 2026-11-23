import { computed, onBeforeUnmount, ref, watch } from "vue";
import { isSuccess } from "@/api/types";
import {
  assistantSessionApi,
  type AssistantFeedback,
  type AssistantMessage
} from "@/api/ticketflow/assistant";
import type { ChatState } from "@/api/ticketflow/assistantStream";
import { useChatStream } from "./useChatStream";
import { fetchAllMessages, localAnswer } from "./messagePages";

export { LOCAL_PREFIX } from "./messagePages";

/**
 * 提问结果：`recorded` 问题已写入（回答可能不完整，见 state）；`rejected` 问题没能写入，
 * 界面应把原文放回输入框；`cancelled` 期间切换了会话或组件已卸载，什么都不用做。
 */
export type AskOutcome =
  | { kind: "recorded"; state: ChatState }
  | { kind: "rejected"; state: ChatState }
  | { kind: "cancelled" };

/**
 * 当前会话的消息与提问。问题由 FastAPI 写入 DRF（meta 帧带回 user_message_id），
 * 流结束后重新拉取消息，以服务端记录为准。没有消息查看权限时不拉取历史。
 */
export function useAssistantChat(
  sessionId: () => string | null,
  canRead: () => boolean = () => true
) {
  const messages = ref<AssistantMessage[]>([]);
  const loading = ref(false);
  /** 正在流式回答的问题原文（尚未从服务端刷新到消息列表） */
  const pending = ref<string | null>(null);
  const { chat, send, stop, reset } = useChatStream();
  const streaming = computed(() => chat.value.status === "streaming");
  let seq = 0;
  let disposed = false;

  async function load(id: string) {
    if (!canRead()) return;
    const own = ++seq;
    loading.value = true;
    const rows = await fetchAllMessages(
      async (page, size) => {
        const res = await assistantSessionApi.messages(id, { page, size });
        return isSuccess(res) && res.data ? res.data : null;
      },
      () => own !== seq
    );
    if (own !== seq) return;
    loading.value = false;
    if (rows) messages.value = rows;
  }

  watch(
    sessionId,
    id => {
      seq++;
      reset();
      pending.value = null;
      messages.value = [];
      loading.value = false;
      if (id) void load(id);
    },
    { immediate: true }
  );

  onBeforeUnmount(() => {
    disposed = true;
    seq++;
  });

  const cancelled = (id: string) => disposed || sessionId() !== id;

  async function ask(text: string): Promise<AskOutcome> {
    const id = sessionId();
    if (!id || streaming.value) return { kind: "cancelled" };
    pending.value = text;
    const state = await send(id, text);
    if (!state || cancelled(id)) return { kind: "cancelled" };
    const questionId = state.userMessageId;
    if (!questionId) {
      pending.value = null;
      return { kind: "rejected", state };
    }
    await load(id);
    if (cancelled(id)) return { kind: "cancelled" };
    const answered = messages.value.some(
      m => m.role === "assistant" && m.user_message_id === questionId
    );
    if (!answered && state.status !== "done") {
      messages.value = [...messages.value, localAnswer(state, questionId)];
    }
    pending.value = null;
    return { kind: "recorded", state };
  }

  function setFeedback(messageId: string, feedback: AssistantFeedback) {
    const target = messages.value.find(m => m.pk === messageId);
    if (target) target.feedback = feedback;
  }

  return {
    messages,
    loading,
    pending,
    chat,
    streaming,
    ask,
    stop,
    setFeedback
  };
}
