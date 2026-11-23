<script lang="ts" setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import RatingSummaryCards from "../components/RatingSummaryCards.vue";
import { useRatings } from "../utils/hook";
import { formatPercent, formatScore } from "../utils/format";
import type { HandlerRatingStats } from "@/api/ticketflow/ratings";

defineOptions({
  name: "TicketFlowRatingStats" // 必须定义，用于菜单自动匹配组件
});

type PageExpose = {
  handleGetData?: () => void;
  searchFields?: Record<string, unknown>;
};

const { t } = useI18n();
const tableRef = ref<PageExpose>();
const period = ref<[string, string] | null>(null);
const {
  api,
  auth,
  summary,
  summaryLoading,
  loadSummary,
  listColumnsFormat,
  operationButtonsProps
  // 评价列表与汇总在后端共用一组路径权限点（list / summary:TicketFlowMyRatings）
} = useRatings("TicketFlowMyRatings");

const handlers = computed(() => summary.value?.by_handler ?? []);

function reloadSummary() {
  const [from, to] = period.value ?? [];
  loadSummary(from && to ? { created_from: from, created_to: to } : undefined);
}

/** 点技术员一行：明细列表按该处理人筛选（没有处理人的评价不支持按人筛选） */
function drillDown(row: HandlerRatingStats) {
  const fields = tableRef.value?.searchFields;
  if (!fields || row.handler_id == null) return;
  fields.handler_id = row.handler_id;
  fields.page = 1;
  tableRef.value?.handleGetData?.();
}

onMounted(reloadSummary);
</script>

<template>
  <div class="main flex flex-col gap-4">
    <div class="flex items-center gap-3">
      <el-date-picker
        v-model="period"
        type="daterange"
        value-format="YYYY-MM-DD"
        :start-placeholder="t('ticketflow.rating.periodStart')"
        :end-placeholder="t('ticketflow.rating.periodEnd')"
        @change="reloadSummary"
      />
    </div>
    <RatingSummaryCards :stats="summary" :loading="summaryLoading" />
    <el-card shadow="never" data-testid="rating-by-handler">
      <template #header>
        <span class="font-medium">{{ t("ticketflow.rating.byHandler") }}</span>
      </template>
      <el-table
        :data="handlers"
        :empty-text="t('ticketflow.rating.noRatings')"
        @row-click="drillDown"
      >
        <el-table-column :label="t('ticketflow.rating.handler')">
          <template #default="{ row }">
            {{ row.handler_name || t("ticketflow.unassigned") }}
          </template>
        </el-table-column>
        <el-table-column
          prop="count"
          :label="t('ticketflow.rating.summary.count')"
          width="110"
        />
        <el-table-column
          :label="t('ticketflow.rating.summary.avgSatisfaction')"
        >
          <template #default="{ row }">
            {{ formatScore(row.avg_satisfaction) }}
          </template>
        </el-table-column>
        <el-table-column
          :label="t('ticketflow.rating.summary.avgHandlerScore')"
        >
          <template #default="{ row }">
            {{ formatScore(row.avg_handler_score) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('ticketflow.rating.summary.resolvedRate')">
          <template #default="{ row }">
            {{ formatPercent(row.resolved_rate) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <RePlusPage
      ref="tableRef"
      :api="api"
      :auth="auth"
      locale-name="ticketflow.rating"
      :selection="false"
      :listColumnsFormat="listColumnsFormat"
      :operationButtonsProps="operationButtonsProps"
    />
  </div>
</template>
