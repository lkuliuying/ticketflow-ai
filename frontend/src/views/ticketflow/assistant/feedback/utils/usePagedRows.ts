import { reactive, ref, shallowRef } from "vue";
import { isSuccess, type ListResult } from "@/api/types";

type Fetcher<T, P> = (
  params: P & { page: number; size: number }
) => Promise<ListResult<T>>;

/**
 * 简单分页列表：页码、每页条数、总数与加载态；过期请求的结果直接丢弃，
 * 避免快速切换时间段时旧结果覆盖新结果。
 */
export function usePagedRows<T, P extends object>(fetcher: Fetcher<T, P>) {
  const rows = shallowRef<T[]>([]);
  const total = ref(0);
  const loading = ref(false);
  const pager = reactive({ page: 1, size: 10 });
  let filters = {} as P;
  let seq = 0;

  async function load() {
    const own = ++seq;
    loading.value = true;
    const res = await fetcher({ ...filters, ...pager }).catch(() => null);
    if (own !== seq) return;
    loading.value = false;
    if (!res || !isSuccess(res)) return;
    rows.value = res.data?.results ?? [];
    total.value = res.data?.total ?? 0;
  }

  /** 换筛选条件：回到第一页 */
  function apply(next: P) {
    filters = next;
    pager.page = 1;
    return load();
  }

  /** 改每页条数：回到第一页再查，避免旧页码越界与重复请求 */
  function resize() {
    pager.page = 1;
    return load();
  }

  return { rows, total, loading, pager, load, apply, resize };
}
