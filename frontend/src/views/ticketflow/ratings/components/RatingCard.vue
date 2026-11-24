<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import type { TicketRating } from "@/api/ticketflow/ratings";

/** 工单评价展示：是否解决、两项星级、标签与文字评价（只读） */
defineOptions({ name: "TicketFlowRatingCard" });

defineProps<{ rating: TicketRating }>();

const { t } = useI18n();
</script>

<template>
  <div class="rating-card" data-testid="ticket-rating">
    <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
      <el-tag :type="rating.resolved ? 'success' : 'danger'" effect="light">
        {{
          rating.resolved
            ? t("ticketflow.rating.resolvedYes")
            : t("ticketflow.rating.resolvedNo")
        }}
      </el-tag>
      <span class="inline-flex items-center gap-2 text-sm">
        {{ t("ticketflow.rating.satisfaction") }}
        <el-rate :model-value="rating.satisfaction" disabled />
      </span>
      <span class="inline-flex items-center gap-2 text-sm">
        {{ t("ticketflow.rating.handlerScore") }}
        <el-rate :model-value="rating.handler_score" disabled />
      </span>
    </div>
    <div v-if="rating.tags.length" class="flex flex-wrap gap-1 mt-2">
      <el-tag
        v-for="tag in rating.tags"
        :key="tag"
        size="small"
        type="primary"
        effect="plain"
      >
        {{ t(`ticketflow.rating.tagValue.${tag}`) }}
      </el-tag>
    </div>
    <p v-if="rating.comment" class="mt-2 mb-0 whitespace-pre-wrap text-sm">
      {{ rating.comment }}
    </p>
    <p class="mt-2 mb-0 text-xs text-fg-muted">
      {{ rating.rater_name }} ·
      {{ new Date(rating.created_time).toLocaleString() }}
      <template v-if="rating.handler_name">
        · {{ t("ticketflow.rating.handler") }} {{ rating.handler_name }}
      </template>
    </p>
  </div>
</template>

<style lang="scss" scoped>
.rating-card {
  padding: 12px 16px;
  background: var(--el-fill-color-lighter);
  border-radius: var(--radius-lg);
}
</style>
