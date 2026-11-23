<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import {
  assistantFeedbackApi,
  type FeedbackRange,
  type FeedbackSession
} from "@/api/ticketflow/assistant";
import { usePagedRows } from "../utils/usePagedRows";
import { openTicketDetail } from "../../../tickets/utils/ticketDetailDrawer";
import { openAssistantTranscript } from "../../utils/transcriptDrawer";

/** 转人工的会话：可查看对话全文，也可跳到对应工单 */
defineOptions({ name: "TicketFlowAssistantHandoffs" });

const { t } = useI18n();
const { rows, total, loading, pager, load, apply } = usePagedRows<
  FeedbackSession,
  FeedbackRange
>(params => assistantFeedbackApi.handoffs(params));

const time = (value?: string | null) =>
  value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";

function ticketOf(row: FeedbackSession) {
  return { pk: row.ticket_id ?? "", number: row.ticket_number ?? "" };
}

defineExpose({ apply, load });
</script>

<template>
  <div class="flex flex-col gap-3" data-testid="assistant-handoffs">
    <el-table
      v-loading="loading"
      :data="rows"
      row-key="pk"
      :empty-text="t('ticketflow.assistantFeedback.noHandoffs')"
    >
      <el-table-column
        :label="t('ticketflow.assistantFeedback.handedOffAt')"
        width="150"
      >
        <template #default="{ row }">
          {{ time((row as FeedbackSession).updated_time) }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('ticketflow.assistantFeedback.user')"
        prop="username"
        width="140"
      />
      <el-table-column
        :label="t('ticketflow.assistantFeedback.sessionTitle')"
        prop="title"
        min-width="220"
        show-overflow-tooltip
      />
      <el-table-column :label="t('ticketflow.number')" width="200">
        <template #default="{ row }">
          <el-button
            v-if="(row as FeedbackSession).ticket_id"
            link
            type="primary"
            @click="openTicketDetail(ticketOf(row as FeedbackSession))"
          >
            {{ (row as FeedbackSession).ticket_number }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column
        :label="t('ticketflow.assistantFeedback.operation')"
        width="140"
      >
        <template #default="{ row }">
          <el-button
            v-if="(row as FeedbackSession).ticket_id"
            link
            type="primary"
            @click="openAssistantTranscript(ticketOf(row as FeedbackSession))"
          >
            {{ t("ticketflow.assistant.viewTranscript") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      class="justify-end"
      layout="total, sizes, prev, pager, next"
      :page-sizes="[10, 20, 50]"
      :total="total"
      @current-change="load"
      @size-change="load"
    />
  </div>
</template>
