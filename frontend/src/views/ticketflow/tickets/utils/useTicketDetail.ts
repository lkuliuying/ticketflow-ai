import { ref } from "vue";
import { isSuccess } from "@/api/types";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";
import { message } from "@/utils/message";

/** 详情内写操作的统一执行器：成功刷新、409 重新加载；执行中再次调用直接返回 false */
export type TicketRun = (
  _action: () => Promise<{ code?: number }>,
  _successText: string
) => Promise<boolean>;

/** http 拦截器对 4xx 以响应体 reject，响应体的 code 与 HTTP 状态码一致 */
function errorCode(error: unknown): number | undefined {
  return (error as { code?: number } | null)?.code;
}

/**
 * 工单详情的数据与写操作。
 *
 * - `load`：只有 404（不存在或不在可见范围）才进入“不存在”状态；网络异常或 5xx
 *   保留当前已加载的详情，失败提示由 http 拦截器展示。
 * - `run`：写操作统一入口，`busy` 期间拒绝重复提交；成功后重新加载详情并通知列表刷新；
 *   收到 409（版本过期或状态已不允许该动作）时重新加载到最新版本，冲突文案由拦截器展示。
 */
export function useTicketDetail(pk: string, onChanged?: () => void) {
  const detail = ref<TicketDetail | null>(null);
  const loading = ref(false);
  const busy = ref(false);
  const notFound = ref(false);

  async function load() {
    loading.value = true;
    try {
      const res = await ticketApi.retrieve<TicketDetail>(pk);
      if (isSuccess(res)) {
        detail.value = res.data;
        notFound.value = false;
      }
    } catch (error) {
      if (errorCode(error) === 404) notFound.value = true;
    } finally {
      loading.value = false;
    }
  }

  const run: TicketRun = async (action, successText) => {
    if (busy.value) return false;
    busy.value = true;
    try {
      const res = await action();
      if (!isSuccess(res)) return false;
      message(successText, { type: "success" });
      await load();
      onChanged?.();
      return true;
    } catch (error) {
      if (errorCode(error) === 409) {
        await load();
        onChanged?.();
      }
      return false;
    } finally {
      busy.value = false;
    }
  };

  return { detail, loading, busy, notFound, load, run };
}
