import { computed, ref, watch } from "vue";
import { isSuccess } from "@/api/types";
import {
  assistantSessionApi,
  type AssistantFeedback,
  type AssistantMessage
} from "@/api/ticketflow/assistant";
import type { ChatState } from "@/api/ticketflow/assistantStream";
import { useChatStream } from "./useChatStream";

const PAGE_SIZE = 100;
/** 单个会话最多取回的页数，防止异常数据导致无限翻页 */
const MAX_PAGES = 10;
/** 本地补位消息的主键前缀：没有服务端主键，不能评价 */
export const LOCAL_PREFIX = "local-";

/** 停止或断线时，服务端写回可能晚于这里的刷新：用流里已收到的内容补一条中断的回答 */
function localAnswer(state: ChatState, questionId: string): AssistantMessage {
  return {
    pk: `${LOCAL_PREFIX}${questionId}`,
    role: "assistant",
    content: state.text,
    references: state.references,
    status: state.status === "error" ? "failed" : "interrupted",
    user_message_id: questionId,
    feedback: null,
    created_time: new Date().toISOString()
  };
}

/**
 * 当前会话的消息与提问。问题由 FastAPI 写入 DRF（meta 帧带回 user_message_id），
 * 流结束后重新拉取消息，以服务端记录为准；问题没能写入时返回 false，由界面把原文放回输入框。
 */
export function useAssistantChat(sessionId: () => string | null) {
  const messages = ref<AssistantMessage[]>([]);
  const loading = ref(false);
  /** 正在流式回答的问题原文（尚未从服务端刷新到消息列表） */
  const pending = ref<string | null>(null);
  const { chat, send, stop, reset } = useChatStream();
  const streaming = computed(() => chat.value.status === "streaming");
  let seq = 0;

  async function load(id: string) {
    const own = ++seq;
    loading.value = true;
    const rows: AssistantMessage[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const res = await assistantSessionApi
        .messages(id, { page, size: PAGE_SIZE })
        .catch(() => null);
      if (own !== seq) return;
      if (!res || !isSuccess(res)) break;
      rows.push(...(res.data?.results ?? []));
      if (rows.length >= (res.data?.total ?? 0)) break;
    }
    loading.value = false;
    messages.value = rows;
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

  /** 提问：返回 true 表示问题已记录（无论回答是否完整） */
  async function ask(text: string): Promise<boolean> {
    const id = sessionId();
    if (!id || streaming.value) return false;
    pending.value = text;
    const result = await send(id, text);
    // 流被切换会话或新的提问顶掉：交给新的上下文处理
    if (!result || sessionId() !== id) return true;
    const questionId = result.userMessageId;
    if (!questionId) {
      pending.value = null;
      return false;
    }
    await load(id);
    if (sessionId() !== id) return true;
    const answered = messages.value.some(
      m => m.role === "assistant" && m.user_message_id === questionId
    );
    if (!answered && result.status !== "done") {
      messages.value = [...messages.value, localAnswer(result, questionId)];
    }
    pending.value = null;
    return true;
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
