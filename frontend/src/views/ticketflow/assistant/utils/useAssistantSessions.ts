import { computed, ref } from "vue";
import { isSuccess } from "@/api/types";
import {
  assistantSessionApi,
  type AssistantSession
} from "@/api/ticketflow/assistant";

/** 会话列表一次取回的上限：员工的历史会话通常不多，超出部分不在侧栏展示 */
const PAGE_SIZE = 100;

/**
 * 本人会话列表：新建、改名、删除（软删除）和当前选中项。
 * 列表按更新时间倒序，提问或改名后把会话移到最前，与服务端排序保持一致。
 */
export function useAssistantSessions() {
  const sessions = ref<AssistantSession[]>([]);
  const activeId = ref<string | null>(null);
  const loading = ref(false);
  const creating = ref(false);
  /** 本次进入页面后新建、尚未改过名的会话：首个问题可用来自动命名 */
  const untitled = ref(new Set<string>());

  const active = computed(
    () => sessions.value.find(s => s.pk === activeId.value) ?? null
  );

  async function load() {
    loading.value = true;
    const res = await assistantSessionApi
      .list<AssistantSession>({ page: 1, size: PAGE_SIZE })
      .catch(() => null);
    loading.value = false;
    if (!res || !isSuccess(res)) return;
    sessions.value = res.data?.results ?? [];
    if (!sessions.value.some(s => s.pk === activeId.value)) {
      activeId.value = sessions.value[0]?.pk ?? null;
    }
  }

  async function create(): Promise<AssistantSession | null> {
    if (creating.value) return null;
    creating.value = true;
    const res = await assistantSessionApi
      .create<AssistantSession>({})
      .catch(() => null);
    creating.value = false;
    if (!res || !isSuccess(res) || !res.data) return null;
    sessions.value = [res.data, ...sessions.value];
    untitled.value = new Set(untitled.value).add(res.data.pk);
    activeId.value = res.data.pk;
    return res.data;
  }

  /** 用服务端返回的最新会话替换本地一项，并移到列表最前 */
  function upsert(session: AssistantSession) {
    sessions.value = [
      session,
      ...sessions.value.filter(s => s.pk !== session.pk)
    ];
  }

  async function rename(pk: string, title: string): Promise<boolean> {
    if (untitled.value.has(pk)) {
      const next = new Set(untitled.value);
      next.delete(pk);
      untitled.value = next;
    }
    const res = await assistantSessionApi.rename(pk, title).catch(() => null);
    if (!res || !isSuccess(res) || !res.data) return false;
    upsert(res.data);
    return true;
  }

  /** 从列表移除（删除成功或已转人工）；移除的是当前会话时选中下一条 */
  function drop(pk: string) {
    sessions.value = sessions.value.filter(s => s.pk !== pk);
    if (activeId.value === pk) activeId.value = sessions.value[0]?.pk ?? null;
  }

  async function remove(pk: string): Promise<boolean> {
    const ok = await assistantSessionApi
      .remove(pk)
      .then(() => true)
      .catch(() => false);
    if (ok) drop(pk);
    return ok;
  }

  /** 有新问答时刷新排序：只更新时间，标题以服务端为准 */
  function touch(pk: string) {
    const session = sessions.value.find(s => s.pk === pk);
    if (session) upsert({ ...session, updated_time: new Date().toISOString() });
  }

  return {
    sessions,
    activeId,
    active,
    loading,
    creating,
    untitled,
    load,
    create,
    rename,
    remove,
    drop,
    touch
  };
}
