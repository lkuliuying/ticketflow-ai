<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import {
  assistantFeedbackApi,
  type DownvoteRow,
  type FeedbackRange
} from "@/api/ticketflow/assistant";
import MessageBubble from "../../components/MessageBubble.vue";
import { usePagedRows } from "../utils/usePagedRows";
import { openTicketDetail } from "../../../tickets/utils/ticketDetailDrawer";

/** 被点踩的回答：展开行看问题、回答与引用；已转人工的可跳到工单 */
defineOptions({ name: "TicketFlowAssistantDownvotes" });

const { t } = useI18n();
const { rows, total, loading, pager, load, apply } = usePagedRows<
  DownvoteRow,
  FeedbackRange
>(params => assistantFeedbackApi.downvotes(params));

const time = (value?: string | null) =>
  value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";

defineExpose({ apply, load });
</script>

<template>
  <div class="flex flex-col gap-3" data-testid="assistant-downvotes">
    <el-table
      v-loading="loading"
      :data="rows"
      row-key="answer.pk"
      :empty-text="t('ticketflow.assistantFeedback.noDownvotes')"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="flex flex-col gap-3 px-4 py-2">
            <MessageBubble :message="(row as DownvoteRow).question" />
            <MessageBubble :message="(row as DownvoteRow).answer" />
          </div>
        </template>
      </el-table-column>
      <el-table-column
        :label="t('ticketflow.assistantFeedback.votedAt')"
        width="150"
      >
        <template #default="{ row }">
          {{ time((row as DownvoteRow).answer.feedback?.updated_time) }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('ticketflow.assistantFeedback.user')"
        prop="session.username"
        width="140"
      />
      <el-table-column
        :label="t('ticketflow.assistantFeedback.question')"
        min-width="220"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          {{ (row as DownvoteRow).question.content }}
        </template>
      </el-table-column>
      <el-table-column :label="t('ticketflow.assistant.reason')" width="120">
        <template #default="{ row }">
          <el-tag
            v-if="(row as DownvoteRow).answer.feedback?.reason"
            type="danger"
            effect="plain"
            size="small"
          >
            {{
              t(
                `ticketflow.assistant.reasonValue.${(row as DownvoteRow).answer.feedback?.reason}`
              )
            }}
          </el-tag>
          <span v-else class="text-fg-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column
        :label="t('ticketflow.assistant.comment')"
        min-width="180"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          {{ (row as DownvoteRow).answer.feedback?.comment || "—" }}
        </template>
      </el-table-column>
      <el-table-column :label="t('ticketflow.number')" width="160">
        <template #default="{ row }">
          <el-button
            v-if="(row as DownvoteRow).session.ticket_id"
            link
            type="primary"
            @click="
              openTicketDetail({
                pk: (row as DownvoteRow).session.ticket_id!,
                number: (row as DownvoteRow).session.ticket_number ?? ''
              })
            "
          >
            {{ (row as DownvoteRow).session.ticket_number }}
          </el-button>
          <span v-else class="text-fg-muted">—</span>
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
