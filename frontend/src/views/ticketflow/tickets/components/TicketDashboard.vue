<script lang="ts" setup>
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { isSuccess } from "@/api/types";
import {
  ticketApi,
  type TicketDashboard,
  type TicketPriority,
  type TicketSlaState,
  type TicketStatus
} from "@/api/ticketflow/tickets";
import { PRIORITY_TONE, SLA_TONE, STATUS_TONE } from "../utils/ticketColumns";

/**
 * 工单看板：在当前用户可见范围内按状态、优先级、SLA 分组计数。
 * 点击计数把对应条件写入列表筛选（同一维度再点一次取消）；
 * 列表每次查询完成后由父组件调用 refresh 同步计数。
 */
defineOptions({ name: "TicketFlowTicketDashboard" });

export type DashboardFilter = {
  key: "status" | "priority" | "sla";
  value: string;
};

const props = defineProps<{ active: DashboardFilter | null }>();
const emit = defineEmits<{ select: [filter: DashboardFilter | null] }>();

const STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING_VERIFY",
  "REOPENED",
  "CLOSED"
];
const PRIORITIES: TicketPriority[] = ["P0", "P1", "P2", "P3"];
const SLA_STATES: TicketSlaState[] = ["OVERDUE", "DUE_SOON", "ON_TRACK", "MET"];

const { t } = useI18n();
const data = ref<TicketDashboard | null>(null);

async function refresh() {
  const res = await ticketApi.dashboard().catch(() => null);
  if (res && isSuccess(res)) data.value = res.data;
}

function toggle(key: DashboardFilter["key"], value: string) {
  const same = props.active?.key === key && props.active.value === value;
  emit("select", same ? null : { key, value });
}

function isActive(key: DashboardFilter["key"], value: string) {
  return props.active?.key === key && props.active.value === value;
}

onMounted(refresh);
defineExpose({ refresh });
</script>

<template>
  <div
    v-if="data"
    class="grid gap-3 mb-3 md:grid-cols-3"
    data-testid="ticket-dashboard"
  >
    <el-card shadow="never" body-class="p-3!">
      <div class="text-sm mb-2">{{ t("ticketflow.status") }}</div>
      <div class="flex flex-wrap gap-2">
        <el-check-tag
          v-for="status in STATUSES"
          :key="status"
          :type="STATUS_TONE[status]"
          :checked="isActive('status', status)"
          @change="toggle('status', status)"
        >
          {{ t(`ticketflow.statusValue.${status}`) }}
          <b class="ml-1">{{ data.status[status] ?? 0 }}</b>
        </el-check-tag>
      </div>
    </el-card>
    <el-card shadow="never" body-class="p-3!">
      <div class="text-sm mb-2">{{ t("ticketflow.priority") }}</div>
      <div class="flex flex-wrap gap-2">
        <el-check-tag
          v-for="priority in PRIORITIES"
          :key="priority"
          :type="PRIORITY_TONE[priority]"
          :checked="isActive('priority', priority)"
          @change="toggle('priority', priority)"
        >
          {{ priority }}
          <b class="ml-1">{{ data.priority[priority] ?? 0 }}</b>
        </el-check-tag>
      </div>
    </el-card>
    <el-card shadow="never" body-class="p-3!">
      <div class="text-sm mb-2">{{ t("ticketflow.sla_state") }}</div>
      <div class="flex flex-wrap gap-2">
        <el-check-tag
          v-for="state in SLA_STATES"
          :key="state"
          :type="SLA_TONE[state]"
          :checked="isActive('sla', state)"
          @change="toggle('sla', state)"
        >
          {{ t(`ticketflow.slaValue.${state}`) }}
          <b class="ml-1">{{ data.sla[state] ?? 0 }}</b>
        </el-check-tag>
      </div>
    </el-card>
  </div>
</template>
