import { ref } from "vue";
import { isSuccess } from "@/api/types";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";
import { message } from "@/utils/message";

/** 详情内写操作的统一执行器：成功刷新、409 提示并重新加载 */
export type TicketRun = (
  _action: () => Promise<{ code?: number }>,
  _successText: string
) => Promise<boolean>;

/** http 拦截器对 4xx 以响应体 reject；工单冲突时响应体的 code 即 409 */
function isConflict(error: unknown): boolean {
  return (error as { code?: number } | null)?.code === 409;
}

/**
 * 工单详情的数据与写操作。
 *
 * 写操作统一经 `run` 执行：成功后重新加载详情并通知列表刷新；收到 409
 * （版本过期或状态已不允许该动作）时重新加载，用户基于最新状态再操作。
 * 失败提示（含 409 的“工单已变更”）由 http 拦截器展示服务端 detail。
 */
export function useTicketDetail(pk: string, onChanged?: () => void) {
  const detail = ref<TicketDetail | null>(null);
  const loading = ref(false);
  const notFound = ref(false);

  async function load() {
    loading.value = true;
    try {
      const res = await ticketApi.retrieve<TicketDetail>(pk);
      if (isSuccess(res)) {
        detail.value = res.data;
        notFound.value = false;
      }
    } catch {
      notFound.value = true;
    } finally {
      loading.value = false;
    }
  }

  async function run(
    action: () => Promise<{ code?: number }>,
    successText: string
  ): Promise<boolean> {
    try {
      const res = await action();
      if (!isSuccess(res)) return false;
      message(successText, { type: "success" });
      await load();
      onChanged?.();
      return true;
    } catch (error) {
      // 冲突文案（服务端 detail）已由 http 拦截器展示，这里只负责刷新到最新状态
      if (isConflict(error)) {
        await load();
        onChanged?.();
      }
      return false;
    }
  }

  return { detail, loading, notFound, load, run };
}
