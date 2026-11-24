<script lang="ts" setup>
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import { isSuccess } from "@/api/types";
import {
  assistantFeedbackApi,
  type AssistantFeedbackSummary,
  type FeedbackRange
} from "@/api/ticketflow/assistant";
import FeedbackSummaryCards from "./components/FeedbackSummaryCards.vue";
import DownvoteList from "./components/DownvoteList.vue";
import HandoffList from "./components/HandoffList.vue";

defineOptions({
  name: "TicketFlowAssistantFeedback" // 必须定义，用于菜单自动匹配组件
});

type ListExpose = { apply: (_range: FeedbackRange) => Promise<void> };

const { t } = useI18n();
const period = ref<[string, string] | null>(null);
const tab = ref<"downvotes" | "handoffs">("downvotes");
const summary = ref<AssistantFeedbackSummary | null>(null);
const summaryLoading = ref(false);
const downvotes = ref<ListExpose>();
const handoffs = ref<ListExpose>();
let summarySeq = 0;

/** 日期段换成带时区的起止时刻（两端包含），与后端筛选口径一致 */
function rangeParams(): FeedbackRange {
  const [from, to] = period.value ?? [];
  if (!from || !to) return {};
  return {
    created_from: dayjs(from).startOf("day").format(),
    created_to: dayjs(to).endOf("day").format()
  };
}

async function loadSummary(range: FeedbackRange) {
  const own = ++summarySeq;
  summaryLoading.value = true;
  const res = await assistantFeedbackApi.summary(range).catch(() => null);
  if (own !== summarySeq) return;
  summaryLoading.value = false;
  if (res && isSuccess(res)) summary.value = res.data ?? null;
}

/** 时间段同时作用于统计与两个列表 */
function applyPeriod() {
  const range = rangeParams();
  void loadSummary(range);
  void downvotes.value?.apply(range);
  void handoffs.value?.apply(range);
}

defineExpose({ applyPeriod });
onMounted(applyPeriod);
</script>

<template>
  <div class="main flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-3">
      <el-date-picker
        v-model="period"
        type="daterange"
        value-format="YYYY-MM-DD"
        :start-placeholder="t('ticketflow.rating.periodStart')"
        :end-placeholder="t('ticketflow.rating.periodEnd')"
        data-testid="assistant-feedback-period"
        @change="applyPeriod"
      />
      <span class="text-xs text-fg-muted">
        {{ t("ticketflow.assistantFeedback.scopeHint") }}
      </span>
    </div>
    <FeedbackSummaryCards :summary="summary" :loading="summaryLoading" />
    <el-card shadow="never">
      <el-tabs v-model="tab">
        <el-tab-pane
          :label="t('ticketflow.assistantFeedback.downvotes')"
          name="downvotes"
        >
          <DownvoteList ref="downvotes" />
        </el-tab-pane>
        <el-tab-pane
          :label="t('ticketflow.assistantFeedback.handoffs')"
          name="handoffs"
        >
          <HandoffList ref="handoffs" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>
