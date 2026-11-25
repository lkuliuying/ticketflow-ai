<script lang="ts" setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { TicketRating } from "@/api/ticketflow/ratings";

defineOptions({ name: "TicketFlowRatingDetailDialog" });

const props = defineProps<{
  rating: TicketRating;
  canViewTicket?: boolean;
  fixedHandlerName?: string;
  onViewTicket?: () => void;
}>();

const { t } = useI18n();

const handlerDisplay = computed(
  () =>
    props.fixedHandlerName ||
    props.rating.handler_name ||
    t("ticketflow.unassigned")
);

const ratedAt = computed(() =>
  props.rating.created_time
    ? new Date(props.rating.created_time).toLocaleString()
    : "—"
);

function viewTicket() {
  props.onViewTicket?.();
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="rating-detail-dialog">
    <el-descriptions :column="2" border size="small">
      <el-descriptions-item :label="t('ticketflow.rating.ticket_number')">
        <el-link
          v-if="canViewTicket"
          type="primary"
          :underline="false"
          data-testid="rating-detail-ticket-link"
          @click="viewTicket"
        >
          {{ rating.ticket_number }}
        </el-link>
        <span v-else>{{ rating.ticket_number }}</span>
      </el-descriptions-item>
      <el-descriptions-item :label="t('ticketflow.rating.created_time')">
        {{ ratedAt }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('ticketflow.rating.rater_name')">
        {{ rating.rater_name }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('ticketflow.rating.handler_name')">
        <span data-testid="rating-detail-handler">{{ handlerDisplay }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <div class="rating-detail-card flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div class="inline-flex items-center gap-2 text-sm">
          <span class="text-fg-muted">
            {{ t("ticketflow.rating.resolved") }}
          </span>
          <el-tag
            :type="rating.resolved ? 'success' : 'danger'"
            effect="light"
            data-testid="rating-detail-resolved"
          >
            {{
              rating.resolved
                ? t("ticketflow.rating.resolvedYes")
                : t("ticketflow.rating.resolvedNo")
            }}
          </el-tag>
        </div>

        <div class="inline-flex items-center gap-2 text-sm">
          <span class="text-fg-muted">
            {{ t("ticketflow.rating.satisfaction") }}
          </span>
          <el-rate :model-value="rating.satisfaction" disabled />
          <span class="font-medium">{{ rating.satisfaction }} / 5</span>
        </div>

        <div class="inline-flex items-center gap-2 text-sm">
          <span class="text-fg-muted">
            {{ t("ticketflow.rating.handlerScore") }}
          </span>
          <el-rate :model-value="rating.handler_score" disabled />
          <span class="font-medium">{{ rating.handler_score }} / 5</span>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="text-fg-muted">{{ t("ticketflow.rating.tags") }}</span>
        <template v-if="rating.tags?.length">
          <el-tag
            v-for="tag in rating.tags"
            :key="tag"
            size="small"
            type="primary"
            effect="plain"
            data-testid="rating-detail-tag"
          >
            {{ t(`ticketflow.rating.tagValue.${tag}`) }}
          </el-tag>
        </template>
        <span v-else class="text-fg-muted">
          {{ t("ticketflow.rating.noTags") }}
        </span>
      </div>

      <div class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">{{ t("ticketflow.rating.comment") }}</span>
        <p
          v-if="rating.comment?.trim()"
          class="m-0 whitespace-pre-wrap wrap-break-word"
          data-testid="rating-detail-comment"
        >
          {{ rating.comment }}
        </p>
        <p
          v-else
          class="m-0 text-fg-muted"
          data-testid="rating-detail-comment-empty"
        >
          {{ t("ticketflow.rating.noComment") }}
        </p>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.rating-detail-card {
  padding: 14px 16px;
  background: var(--el-fill-color-lighter);
  border-radius: var(--radius-lg);
}
</style>
