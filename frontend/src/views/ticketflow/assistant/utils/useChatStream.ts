import { onBeforeUnmount, ref } from "vue";
import { isSuccess } from "@/api/types";
import { assistantSessionApi } from "@/api/ticketflow/assistant";
import {
  emptyChat,
  streamChat,
  type ChatState
} from "@/api/ticketflow/assistantStream";
import { getToken } from "@/utils/auth";

/** 流内或建流时可以直接重试的状态码：限流、上游繁忙、超时 */
const RETRYABLE = new Set([429, 503, 504]);

/**
 * fetch 不经过 axios 的刷新链路：借一次轻量的会话列表请求让 axios 静默刷新 access，
 * 已撤销时由拦截器提示并回到登录页。返回登录态是否仍可用。
 */
async function ensureSession(): Promise<boolean> {
  try {
    return isSuccess(await assistantSessionApi.list({ page: 1, size: 1 }));
  } catch {
    return false;
  }
}

/**
 * 单条问答流：同一时刻只有一条，切换会话、停止或卸载都会取消在途的流。
 * 本地没有 access 时先建立会话，建流返回 401 时刷新后重试一次。
 */
export function useChatStream() {
  const chat = ref<ChatState>(emptyChat());
  let controller: AbortController | null = null;

  function stop() {
    controller?.abort();
  }

  function reset() {
    stop();
    controller = null;
    chat.value = emptyChat();
  }

  async function open(
    sessionId: string,
    message: string,
    own: AbortController,
    retried: boolean
  ): Promise<void> {
    try {
      await streamChat(
        sessionId,
        message,
        state => {
          if (controller === own) chat.value = state;
        },
        own.signal
      );
    } catch (error) {
      const code = Number((error as { code?: number })?.code ?? 0);
      const restored = code === 401 && !retried ? await ensureSession() : false;
      if (controller !== own) return;
      if (own.signal.aborted) {
        chat.value = { ...chat.value, status: "stopped" };
        return;
      }
      if (restored) return open(sessionId, message, own, true);
      chat.value = {
        ...chat.value,
        status: "error",
        error: {
          code,
          detail: (error as Error)?.message ?? "",
          retryable: RETRYABLE.has(code)
        }
      };
    }
  }

  /** 发送问题并等待流结束；返回结束时的状态（被新的流或切换会话顶掉时返回 null） */
  async function send(
    sessionId: string,
    message: string
  ): Promise<ChatState | null> {
    stop();
    const own = new AbortController();
    controller = own;
    chat.value = { ...emptyChat(), status: "streaming" };
    const ready = Boolean(getToken()) || (await ensureSession());
    if (controller !== own) return null;
    if (own.signal.aborted) {
      chat.value = { ...chat.value, status: "stopped" };
    } else if (!ready) {
      chat.value = emptyChat();
    } else {
      await open(sessionId, message, own, false);
    }
    if (controller !== own) return null;
    controller = null;
    return chat.value;
  }

  // 卸载时放弃在途的流：send 返回 null，调用方不再刷新或回调
  onBeforeUnmount(reset);

  return { chat, send, stop, reset };
}
