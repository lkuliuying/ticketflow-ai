<script lang="ts" setup>
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { Clock, Finished, Tickets, Warning } from "@element-plus/icons-vue";
import type { WorkbenchStats } from "../useWorkbench";

/** 工作台计数卡：待处理 / 处理中 / 待验收 / SLA 风险；点击跳转工单列表并带上对应筛选 */
defineOptions({ name: "WorkbenchStats" });

const props = defineProps<{ stats: WorkbenchStats }>();
const emit = defineEmits<{ open: [query: Record<string, string>] }>();

type Card = {
  key: keyof WorkbenchStats;
  icon: Component;
  tone: "primary" | "warning" | "info" | "danger";
  query: Record<string, string>;
};

const { t } = useI18n();

const CARDS: Card[] = [
  { key: "pending", icon: Tickets, tone: "primary", query: { status: "OPEN" } },
  {
    key: "inProgress",
    icon: Clock,
    tone: "warning",
    query: { status: "IN_PROGRESS" }
  },
  {
    key: "verifying",
    icon: Finished,
    tone: "info",
    query: { status: "PENDING_VERIFY" }
  },
  { key: "slaRisk", icon: Warning, tone: "danger", query: { sla: "OVERDUE" } }
];

const cards = computed(() =>
  CARDS.map(card => ({ ...card, value: props.stats[card.key] }))
);
</script>

<template>
  <div class="grid gap-4 grid-cols-2 lg:grid-cols-4">
    <button
      v-for="card in cards"
      :key="card.key"
      type="button"
      class="stat-card"
      :data-testid="`workbench-stat-${card.key}`"
      @click="emit('open', card.query)"
    >
      <span
        class="stat-icon"
        :style="{
          color: `var(--el-color-${card.tone})`,
          backgroundColor: `var(--el-color-${card.tone}-light-9)`
        }"
      >
        <el-icon :size="20"><component :is="card.icon" /></el-icon>
      </span>
      <span class="flex flex-col items-start">
        <span class="stat-value">{{ card.value }}</span>
        <span class="text-sm text-fg-muted">
          {{ t(`workbench.stats.${card.key}`) }}
        </span>
      </span>
    </button>
  </div>
</template>

<style lang="scss" scoped>
.stat-card {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 18px 20px;
  text-align: left;
  cursor: pointer;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--radius-xl);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;

  &:hover,
  &:focus-visible {
    outline: none;
    border-color: var(--el-color-primary-light-5);
    box-shadow: var(--el-box-shadow-lighter);
  }
}

.stat-icon {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
}

.stat-value {
  font-size: var(--font-size-2xl);
  font-weight: 600;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}
</style>
