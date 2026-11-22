import { onBeforeUnmount, ref, watch } from "vue";
import { emptyReply, streamReply } from "@/api/ticketflow/ai";
import { ticketApi } from "@/api/ticketflow/tickets";
import { isSuccess } from "@/api/types";
import { getToken } from "@/utils/auth";

/** 流内错误里可以直接重试的状态码：限流、上游繁忙、超时 */
const RETRYABLE = new Set([429, 503, 504]);

/**
 * 经 axios 复用既有的登录态处理：access 过期时静默刷新，已撤销时提示并回到登录页。
 * 返回会话是否仍然可用。
 */
async function ensureSession(ticketId: string): Promise<boolean> {
  try {
    return isSuccess(await ticketApi.retrieve(ticketId));
  } catch {
    return false;
  }
}

/**
 * 流式回复建议：同一时刻只有一条流，重新生成、换工单或组件卸载都会取消在途的流。
 * fetch 不经过 axios 的刷新链路：本地没有 access 时先建立会话，建流返回 401 时
 * 交给 axios 处理后重试一次。
 */
export function useReplyStream(ticketId: () => string | undefined) {
  const reply = ref(emptyReply());
  let controller: AbortController | null = null;

  function stop() {
    controller?.abort();
  }

  async function open(id: string, own: AbortController, retried: boolean) {
    try {
      await streamReply(
        id,
        state => {
          if (controller === own) reply.value = state;
        },
        own.signal
      );
    } catch (error) {
      const code = Number((error as { code?: number })?.code ?? 0);
      if (code === 401 && !retried && (await ensureSession(id))) {
        if (controller === own) await open(id, own, true);
        return;
      }
      if (controller !== own) return;
      reply.value = {
        ...reply.value,
        status: "error",
        error: {
          code,
          detail: (error as Error)?.message ?? "",
          retryable: RETRYABLE.has(code)
        }
      };
    }
  }

  async function generate() {
    const id = ticketId();
    if (!id) return;
    stop();
    const own = new AbortController();
    controller = own;
    reply.value = emptyReply();
    const ready = Boolean(getToken()) || (await ensureSession(id));
    // 建立会话期间已停止、重新生成或卸载：不再建流
    if (controller !== own || own.signal.aborted) return;
    if (!ready) {
      controller = null;
      return;
    }
    await open(id, own, false);
    if (controller === own) controller = null;
  }

  watch(ticketId, () => {
    stop();
    controller = null;
    reply.value = emptyReply();
  });
  onBeforeUnmount(stop);

  return { reply, generate, stop };
}
