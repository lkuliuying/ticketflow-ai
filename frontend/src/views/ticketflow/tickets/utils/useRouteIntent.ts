import { watch } from "vue";
import { useRoute, useRouter } from "vue-router";

/** 与 TicketDashboard.vue 导出的看板筛选同形（.ts 无法从 SFC 取类型导出） */
type DashboardFilter = { key: "status" | "priority" | "sla"; value: string };

/** 其他页面（如首页工作台）跳转到工单页时可携带的意图参数 */
export type RouteIntent = {
  filter: DashboardFilter | null;
  create: boolean;
};

const FILTER_KEYS = ["status", "sla", "priority"] as const;

/** 解析 query：`create=1` 打开新建表单，`status` / `sla` / `priority` 取第一个作为看板筛选 */
export function parseRouteIntent(
  query: Record<string, unknown>
): RouteIntent | null {
  const create = query.create === "1";
  const key = FILTER_KEYS.find(
    name => typeof query[name] === "string" && query[name]
  );
  const filter = key ? { key, value: query[key] as string } : null;
  return create || filter ? { filter, create } : null;
}

/**
 * 消费路由意图：列表首次查询完成（元数据与表单列就绪）后执行，执行后清掉 query，
 * 避免刷新或返回时重复打开表单。页面被缓存时，再次带参进入同样会触发。
 */
export function useRouteIntent(handlers: {
  isReady: () => boolean;
  applyFilter: (_filter: DashboardFilter) => void;
  openCreate: () => void;
}) {
  const route = useRoute();
  const router = useRouter();

  function consume() {
    if (!handlers.isReady()) return;
    const intent = parseRouteIntent(route.query);
    if (!intent) return;
    router.replace({ path: route.path });
    if (intent.filter) handlers.applyFilter(intent.filter);
    if (intent.create) handlers.openCreate();
  }

  watch(() => route.query, consume);
  return { consume };
}
