<script lang="ts" setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { TicketDetail } from "@/api/ticketflow/tickets";
import { useTicketDetail } from "../utils/useTicketDetail";
import { PRIORITY_TONE, SLA_TONE, STATUS_TONE } from "../utils/ticketColumns";
import TicketActions from "./TicketActions.vue";
import TicketAiPanel from "./TicketAiPanel.vue";
import TicketReply from "./TicketReply.vue";
import TicketTimeline from "./TicketTimeline.vue";

/**
 * 工单详情抽屉：摘要与 SLA、可执行操作、回复框、时间线；处理人在右侧另有 AI 面板。
 * 操作与输入框的显隐全部依据后端返回的 `viewer` 与 `available_transitions`。
 */
defineOptions({ name: "TicketFlowTicketDetail" });

const props = defineProps<{
  pk: string;
  onChanged?: () => void;
  onArchive?: (_ticket: TicketDetail, _reload: () => void) => void;
}>();

const { t, te } = useI18n();
const { detail, loading, busy, notFound, load, run } = useTicketDetail(
  props.pk,
  props.onChanged
);

onMounted(load);

/** 能否回复完全由后端 viewer 给出（处理人或提交人，且有评论权限） */
const canReply = computed(() => Boolean(detail.value?.viewer.can_reply));

const replyRef = ref<InstanceType<typeof TicketReply>>();

/** AI 生成的回复只填入回复框（对外回复），发送仍由用户点击 */
function fillReply(text: string) {
  replyRef.value?.fill(text);
}

function label(group: string, value: string | null | undefined) {
  if (!value) return "—";
  const key = `ticketflow.${group}.${value}`;
  return te(key) ? t(key) : value;
}

function time(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : "—";
}
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-4 min-h-40">
    <el-result
      v-if="notFound"
      icon="warning"
      :title="t('ticketflow.detail.notFound')"
    />
    <div
      v-else-if="detail"
      class="grid gap-6"
      :class="{ 'ticket-detail--ai': detail.viewer.can_handle }"
    >
      <div class="flex flex-col gap-4 min-w-0">
        <header class="flex flex-col gap-2" data-testid="ticket-header">
          <div class="flex items-center gap-2 flex-wrap">
            <el-tag :type="STATUS_TONE[detail.status]">
              {{ label("statusValue", detail.status) }}
            </el-tag>
            <el-tag :type="PRIORITY_TONE[detail.priority]" effect="plain">
              {{ detail.priority }}
            </el-tag>
            <el-tag
              :type="SLA_TONE[detail.sla_state]"
              :effect="
                detail.sla_state === 'DUE_SOON' ||
                detail.sla_state === 'OVERDUE'
                  ? 'dark'
                  : 'plain'
              "
            >
              SLA · {{ label("slaValue", detail.sla_state) }}
            </el-tag>
            <span class="text-(--el-text-color-secondary) text-sm">
              {{ detail.number }} · v{{ detail.version }}
            </span>
          </div>
          <h3 class="m-0">{{ detail.title }}</h3>
        </header>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('ticketflow.category')">
            {{ label("categoryValue", detail.category) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.department_name')">
            {{ detail.department_name }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.submitter_name')">
            {{ detail.submitter_name }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.assignee_name')">
            {{ detail.assignee_name || t("ticketflow.unassigned") }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.sla_due_at')">
            {{ time(detail.sla_due_at) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.first_response_at')">
            {{ time(detail.first_response_at) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.description')" :span="2">
            <div class="whitespace-pre-wrap wrap-break-word">
              {{ detail.description }}
            </div>
          </el-descriptions-item>
          <el-descriptions-item
            v-if="detail.ai_summary || detail.ai_tags?.length"
            :label="t('ticketflow.ai_summary')"
            :span="2"
          >
            <div class="flex flex-col gap-1" data-testid="ticket-ai-summary">
              <span class="whitespace-pre-wrap wrap-break-word">
                {{ detail.ai_summary }}
              </span>
              <div class="flex flex-wrap gap-1">
                <el-tag
                  v-for="tag in detail.ai_tags"
                  :key="tag"
                  size="small"
                  effect="plain"
                >
                  {{ tag }}
                </el-tag>
              </div>
            </div>
          </el-descriptions-item>
        </el-descriptions>

        <section class="flex flex-col gap-2">
          <h4 class="m-0">{{ t("ticketflow.detail.actions") }}</h4>
          <TicketActions :ticket="detail" :run="run" :busy="busy" />
          <div v-if="detail.viewer.can_archive && onArchive">
            <el-button
              type="success"
              plain
              data-testid="ticket-archive"
              @click="onArchive(detail, load)"
            >
              {{ t("ticketflow.detail.archive") }}
            </el-button>
          </div>
        </section>

        <section v-if="canReply" class="flex flex-col gap-2">
          <h4 class="m-0">{{ t("ticketflow.detail.reply") }}</h4>
          <TicketReply
            ref="replyRef"
            :ticket="detail"
            :run="run"
            :busy="busy"
          />
        </section>

        <section class="flex flex-col gap-2">
          <h4 class="m-0">
            {{ t("ticketflow.detail.timeline") }}
            <span class="text-sm text-(--el-text-color-secondary)">
              （{{ detail.timeline.total }}）
            </span>
          </h4>
          <TicketTimeline :ticket="detail" />
        </section>
      </div>
      <TicketAiPanel
        v-if="detail.viewer.can_handle"
        :ticket="detail"
        :run="run"
        :busy="busy"
        :can-fill="canReply"
        @fill="fillReply"
      />
    </div>
  </div>
</template>

<style scoped>
@media (width >= 1200px) {
  .ticket-detail--ai {
    grid-template-columns: minmax(0, 1fr) 340px;
  }
}
</style>
