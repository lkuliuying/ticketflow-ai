<script lang="ts" setup>
import { onMounted, ref } from "vue";
import RatingSummaryCards from "../components/RatingSummaryCards.vue";
import { useRatings } from "../utils/hook";

defineOptions({
  name: "TicketFlowMyRatings" // 必须定义，用于菜单自动匹配组件
});

const tableRef = ref();
const {
  api,
  auth,
  canSummary,
  summary,
  summaryLoading,
  loadSummary,
  listColumnsFormat,
  searchColumnsFormat,
  operationButtonsProps
} = useRatings("TicketFlowMyRatings", { mode: "mine" });

onMounted(() => {
  if (canSummary) void loadSummary();
});
</script>

<template>
  <div class="main flex flex-col gap-4">
    <RatingSummaryCards
      v-if="canSummary"
      :stats="summary"
      :loading="summaryLoading"
    />
    <RePlusPage
      ref="tableRef"
      :api="api"
      :auth="auth"
      locale-name="ticketflow.rating"
      :selection="false"
      :listColumnsFormat="listColumnsFormat"
      :searchColumnsFormat="searchColumnsFormat"
      :operationButtonsProps="operationButtonsProps"
    />
  </div>
</template>
