<script lang="ts" setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { AssistantFeedbackSummary } from "@/api/ticketflow/assistant";
import { formatPercent } from "../../../ratings/utils/format";

/** AI 反馈统计：会话数、问题数、好评率（赞 / 有评价的回答）与转人工率（转人工 / 会话） */
defineOptions({ name: "TicketFlowAssistantFeedbackSummary" });

const props = defineProps<{
  summary: AssistantFeedbackSummary | null;
  loading?: boolean;
}>();
const { t } = useI18n();

const ratio = (part: number, whole: number) =>
  whole > 0 ? part / whole : null;

const items = computed(() => {
  const s = props.summary;
  const up = s?.up ?? 0;
  const down = s?.down ?? 0;
  return [
    { key: "sessions", value: String(s?.sessions ?? 0) },
    { key: "questions", value: String(s?.questions ?? 0) },
    {
      key: "upRate",
      value: formatPercent(ratio(up, up + down)),
      hint: t("ticketflow.assistantFeedback.votes", { up, down })
    },
    {
      key: "handoffRate",
      value: formatPercent(ratio(s?.handoffs ?? 0, s?.sessions ?? 0)),
      hint: t("ticketflow.assistantFeedback.handoffCount", {
        count: s?.handoffs ?? 0
      })
    }
  ];
});
</script>

<template>
  <div v-loading="loading" class="grid gap-4 grid-cols-2 lg:grid-cols-4">
    <el-card
      v-for="item in items"
      :key="item.key"
      shadow="never"
      body-class="p-4!"
      :data-testid="`assistant-summary-${item.key}`"
    >
      <div class="text-sm text-fg-muted">
        {{ t(`ticketflow.assistantFeedback.summary.${item.key}`) }}
      </div>
      <div class="summary-value">{{ item.value }}</div>
      <div v-if="item.hint" class="text-xs text-fg-muted mt-1">
        {{ item.hint }}
      </div>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.summary-value {
  margin-top: 6px;
  font-size: var(--font-size-2xl);
  font-weight: 600;
  color: var(--el-text-color-primary);
}
</style>
