<script lang="ts" setup>
import { ref } from "vue";
import { useTickets } from "./utils/hook";
import { useRouteIntent } from "./utils/useRouteIntent";
import TicketDashboard, {
  type DashboardFilter
} from "./components/TicketDashboard.vue";

defineOptions({
  name: "TicketFlowTickets" // 必须定义，用于菜单自动匹配组件
});

type PageExpose = {
  handleGetData?: () => void;
  handleAddOrEdit?: (_isAdd?: boolean) => void;
  searchFields?: { value: Record<string, unknown> } | Record<string, unknown>;
};

const tableRef = ref<PageExpose>();
const dashboardRef = ref<InstanceType<typeof TicketDashboard>>();
const activeFilter = ref<DashboardFilter | null>(null);
const { api, auth, listColumnsFormat, operationButtonsProps } =
  useTickets(tableRef);
const listReady = ref(false);
const { consume: consumeRouteIntent } = useRouteIntent({
  isReady: () => listReady.value,
  applyFilter: filter => applyDashboardFilter(filter),
  openCreate: () => {
    if (auth.create) tableRef.value?.handleAddOrEdit?.(true);
  }
});

const DASHBOARD_KEYS = ["status", "priority", "sla"] as const;
/** 看板计数随列表筛选变化，但不带看板自身的三个维度与分页参数 */
const NON_FILTER_KEYS = new Set<string>([
  ...DASHBOARD_KEYS,
  "page",
  "size",
  "ordering"
]);

/** 看板点选：清掉三个看板维度后写入当前条件，回到第 1 页，与搜索表单保持一致再查询 */
function applyDashboardFilter(filter: DashboardFilter | null) {
  const fields = tableRef.value?.searchFields as
    Record<string, unknown> | undefined;
  if (!fields) return;
  activeFilter.value = filter;
  for (const key of DASHBOARD_KEYS) fields[key] = "";
  if (filter) fields[filter.key] = filter.value;
  fields.page = 1;
  tableRef.value?.handleGetData?.();
}

/**
 * 列表查询完成后按当前非看板筛选刷新计数；表单里改动了看板维度
 * （改了当前维度的值或叠加了其他维度）时取消高亮，避免视觉与实际条件不符。
 */
function onSearchComplete({
  searchFields
}: {
  searchFields: { value: Record<string, unknown> };
}) {
  const fields = searchFields.value ?? {};
  const current = activeFilter.value;
  if (current) {
    const others = DASHBOARD_KEYS.filter(key => key !== current.key);
    if (
      fields[current.key] !== current.value ||
      others.some(key => fields[key])
    ) {
      activeFilter.value = null;
    }
  }
  const filters = Object.fromEntries(
    Object.entries(fields).filter(
      ([key, value]) =>
        !NON_FILTER_KEYS.has(key) && value !== "" && value != null
    )
  );
  dashboardRef.value?.refresh(filters);
  if (!listReady.value) {
    listReady.value = true;
    consumeRouteIntent();
  }
}
</script>

<template>
  <div class="main">
    <TicketDashboard
      ref="dashboardRef"
      :active="activeFilter"
      @select="applyDashboardFilter"
    />
    <RePlusPage
      ref="tableRef"
      :api="api"
      :auth="auth"
      locale-name="ticketflow"
      :selection="false"
      :listColumnsFormat="listColumnsFormat"
      :operationButtonsProps="operationButtonsProps"
      @search-complete="onSearchComplete"
    />
  </div>
</template>
