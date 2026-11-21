<script lang="ts" setup>
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import type { TicketDetail } from "@/api/ticketflow/tickets";
import { useUserStoreHook } from "@/store/modules/user";
import { useTicketDetail } from "../utils/useTicketDetail";
import { PRIORITY_TONE, SLA_TONE, STATUS_TONE } from "../utils/ticketColumns";
import TicketActions from "./TicketActions.vue";
import TicketReply from "./TicketReply.vue";
import TicketTimeline from "./TicketTimeline.vue";

/**
 * 工单详情抽屉：摘要与 SLA、可执行操作、回复框、时间线。
 * 操作与输入框的显隐全部依据后端返回的 `viewer` 与 `available_transitions`。
 */
defineOptions({ name: "TicketFlowTicketDetail" });

const props = defineProps<{
  pk: string;
  onChanged?: () => void;
  onArchive?: (_ticket: TicketDetail) => void;
}>();

const { t, te } = useI18n();
const { detail, loading, notFound, load, run } = useTicketDetail(
  props.pk,
  props.onChanged
);

onMounted(load);

const userStore = useUserStoreHook();
/** 处理人可回复；提交人只能对自己的工单发对外回复（与后端评论校验一致） */
const canReply = computed(
  () =>
    Boolean(detail.value) &&
    (detail.value!.viewer.can_handle ||
      detail.value!.submitter_id === Number(userStore.pk))
);

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
    <template v-else-if="detail">
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
              detail.sla_state === 'DUE_SOON' || detail.sla_state === 'OVERDUE'
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
      </el-descriptions>

      <section class="flex flex-col gap-2">
        <h4 class="m-0">{{ t("ticketflow.detail.actions") }}</h4>
        <TicketActions :ticket="detail" :run="run" />
        <div v-if="detail.viewer.can_archive && onArchive">
          <el-button
            type="success"
            plain
            data-testid="ticket-archive"
            @click="onArchive(detail)"
          >
            {{ t("ticketflow.detail.archive") }}
          </el-button>
        </div>
      </section>

      <section v-if="canReply" class="flex flex-col gap-2">
        <h4 class="m-0">{{ t("ticketflow.detail.reply") }}</h4>
        <TicketReply :ticket="detail" :run="run" />
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
    </template>
  </div>
</template>
