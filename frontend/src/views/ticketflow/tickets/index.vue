<script lang="ts" setup>
import { ref } from "vue";
import { useTickets } from "./utils/hook";
import TicketDashboard, {
  type DashboardFilter
} from "./components/TicketDashboard.vue";

defineOptions({
  name: "TicketFlowTickets" // 必须定义，用于菜单自动匹配组件
});

type PageExpose = {
  handleGetData?: () => void;
  searchFields?: { value: Record<string, unknown> } | Record<string, unknown>;
};

const tableRef = ref<PageExpose>();
const dashboardRef = ref<InstanceType<typeof TicketDashboard>>();
const activeFilter = ref<DashboardFilter | null>(null);
const { api, auth, listColumnsFormat, operationButtonsProps } =
  useTickets(tableRef);

/** 看板点选：清掉三个看板维度后写入当前条件，与搜索表单保持一致再查询 */
function applyDashboardFilter(filter: DashboardFilter | null) {
  activeFilter.value = filter;
  const fields = tableRef.value?.searchFields as
    Record<string, unknown> | undefined;
  if (!fields) return;
  for (const key of ["status", "priority", "sla"]) fields[key] = "";
  if (filter) fields[filter.key] = filter.value;
  tableRef.value?.handleGetData?.();
}

/** 列表查询完成后刷新看板计数；表单里手动改了看板维度时同步高亮 */
function onSearchComplete({
  searchFields
}: {
  searchFields: { value: Record<string, unknown> };
}) {
  const fields = searchFields.value ?? {};
  const current = activeFilter.value;
  if (current && fields[current.key] !== current.value) {
    activeFilter.value = null;
  }
  dashboardRef.value?.refresh();
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
