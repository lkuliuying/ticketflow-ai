<script lang="ts" setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RATING_TAGS, type RatingStats } from "@/api/ticketflow/ratings";
import { formatPercent, formatScore } from "../utils/format";

/** 评价汇总卡：评价数、平均满意度、平均处理人评分、解决率与标签分布 */
defineOptions({ name: "TicketFlowRatingSummaryCards" });

const props = defineProps<{ stats: RatingStats | null; loading?: boolean }>();
const { t } = useI18n();

const items = computed(() => [
  { key: "count", value: String(props.stats?.count ?? 0) },
  { key: "avgSatisfaction", value: formatScore(props.stats?.avg_satisfaction) },
  {
    key: "avgHandlerScore",
    value: formatScore(props.stats?.avg_handler_score)
  },
  { key: "resolvedRate", value: formatPercent(props.stats?.resolved_rate) }
]);

const tags = computed(() =>
  RATING_TAGS.map(tag => ({ tag, count: props.stats?.tags?.[tag] ?? 0 }))
);
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-3">
    <div class="grid gap-4 grid-cols-2 lg:grid-cols-4">
      <el-card
        v-for="item in items"
        :key="item.key"
        shadow="never"
        body-class="p-4!"
        :data-testid="`rating-summary-${item.key}`"
      >
        <div class="text-sm text-fg-muted">
          {{ t(`ticketflow.rating.summary.${item.key}`) }}
        </div>
        <div class="summary-value">{{ item.value }}</div>
      </el-card>
    </div>
    <div class="flex flex-wrap items-center gap-2 text-sm">
      <span class="text-fg-muted">{{ t("ticketflow.rating.tags") }}</span>
      <el-tag
        v-for="item in tags"
        :key="item.tag"
        type="primary"
        effect="plain"
        size="small"
      >
        {{ t(`ticketflow.rating.tagValue.${item.tag}`) }} · {{ item.count }}
      </el-tag>
    </div>
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
