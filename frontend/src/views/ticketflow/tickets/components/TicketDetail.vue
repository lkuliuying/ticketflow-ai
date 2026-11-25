<script lang="ts" setup>
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type {
  TicketChatState,
  TicketDetail,
  TicketStatus
} from "@/api/ticketflow/tickets";
import { useAuthorizedMedia } from "../utils/useAuthorizedMedia";
import { useTicketDetail } from "../utils/useTicketDetail";
import { PRIORITY_TONE, SLA_TONE, STATUS_TONE } from "../utils/ticketColumns";
import TicketActions from "./TicketActions.vue";
import TicketAiPanel from "./TicketAiPanel.vue";
import TicketChatPanel from "./TicketChatPanel.vue";
import TicketReply from "./TicketReply.vue";
import TicketTimeline from "./TicketTimeline.vue";
import RatingCard from "../../ratings/components/RatingCard.vue";
import { openRatingDialog } from "../../ratings/utils/ratingDialog";
import { openAssistantTranscript } from "../../assistant/utils/transcriptDrawer";

/**
 * 工单详情抽屉：摘要与附带图片、可执行操作、实时排查会话（替代对外回复）、
 * 内部备注与流转日志；处理人在右侧另有 AI 面板。
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
const { urls: mediaUrls, ensure: ensureMedia } = useAuthorizedMedia();
const activeTab = ref<"chat" | "timeline">("chat");
const chatRef = ref<InstanceType<typeof TicketChatPanel>>();
const chatCanSend = ref(false);

onMounted(load);

watch(
  () => detail.value?.attachments,
  items => {
    for (const att of items ?? []) {
      void ensureMedia(att.thumb_url);
      void ensureMedia(att.url);
    }
  },
  { immediate: true }
);

watch(
  () => detail.value?.chat_state,
  state => {
    if (state) chatCanSend.value = state.can_send;
  },
  { immediate: true }
);

const showActions = computed(() => {
  const ticket = detail.value;
  if (!ticket) return false;
  return showTicketActions.value || canArchive.value;
});

const showTicketActions = computed(() => {
  const ticket = detail.value;
  return Boolean(
    ticket &&
    (!ticket.viewer.read_only || ticket.available_transitions.length > 0)
  );
});

const canArchive = computed(() =>
  Boolean(detail.value?.viewer.can_archive && props.onArchive)
);

const canCommentInternal = computed(() =>
  Boolean(detail.value?.viewer.can_comment_internal)
);

const attachmentPreviewList = computed(() =>
  (detail.value?.attachments ?? [])
    .map(att => mediaUrls[att.url])
    .filter(Boolean)
);

function rate(afterClose = false) {
  if (!detail.value) return;
  openRatingDialog(detail.value, {
    afterClose,
    onRated: () => {
      void load();
      props.onChanged?.();
    }
  });
}

function onTransitioned(to: TicketStatus) {
  void chatRef.value?.refresh?.();
  if (to === "CLOSED" && detail.value?.viewer.can_rate) rate(true);
}

function onChatStateChange(state: TicketChatState) {
  chatCanSend.value = state.can_send;
}

function fillChat(text: string) {
  activeTab.value = "chat";
  chatRef.value?.fill(text);
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
          <div v-if="detail.assistant_session_id">
            <el-button
              size="small"
              plain
              type="primary"
              data-testid="ticket-assistant-transcript"
              @click="openAssistantTranscript(detail)"
            >
              {{ t("ticketflow.assistant.viewTranscript") }}
            </el-button>
          </div>
        </header>

        <el-alert
          v-if="detail.viewer.read_only"
          type="info"
          show-icon
          :closable="false"
          :title="t('ticketflow.detail.readOnly')"
          :description="t('ticketflow.detail.readOnlyHint')"
          data-testid="ticket-read-only"
        />

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
            v-if="detail.attachments?.length"
            :label="t('ticketflow.detail.attachments')"
            :span="2"
          >
            <div
              class="flex flex-wrap gap-2"
              data-testid="ticket-attachments-gallery"
            >
              <el-image
                v-for="(att, idx) in detail.attachments"
                :key="att.id"
                :src="mediaUrls[att.thumb_url] || mediaUrls[att.url]"
                :preview-src-list="attachmentPreviewList"
                :initial-index="idx"
                fit="cover"
                class="size-20 rounded border border-(--el-border-color) cursor-pointer"
              />
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

        <section v-if="showActions" class="flex flex-col gap-2">
          <h4 class="m-0">{{ t("ticketflow.detail.actions") }}</h4>
          <TicketActions
            v-if="showTicketActions"
            :ticket="detail"
            :run="run"
            :busy="busy"
            @transitioned="onTransitioned"
          />
          <div v-if="canArchive">
            <el-button
              type="success"
              plain
              data-testid="ticket-archive"
              @click="onArchive?.(detail, load)"
            >
              {{ t("ticketflow.detail.archive") }}
            </el-button>
          </div>
        </section>

        <section
          v-if="detail.rating || detail.viewer.can_rate"
          class="flex flex-col gap-2"
        >
          <h4 class="m-0">{{ t("ticketflow.rating.section") }}</h4>
          <RatingCard v-if="detail.rating" :rating="detail.rating" />
          <div v-else>
            <el-button
              type="primary"
              plain
              data-testid="ticket-rate"
              @click="rate()"
            >
              {{ t("ticketflow.rating.rate") }}
            </el-button>
            <span class="ml-3 text-sm text-fg-muted">
              {{ t("ticketflow.rating.rateHint") }}
            </span>
          </div>
        </section>

        <el-tabs v-model="activeTab" data-testid="ticket-detail-tabs">
          <el-tab-pane :label="t('ticketflow.detail.tabChat')" name="chat">
            <TicketChatPanel
              ref="chatRef"
              :ticket="detail"
              @state-change="onChatStateChange"
            />
          </el-tab-pane>
          <el-tab-pane
            :label="`${t('ticketflow.detail.tabTimeline')}（${detail.timeline.total}）`"
            name="timeline"
          >
            <div class="flex flex-col gap-4">
              <TicketReply
                v-if="canCommentInternal"
                :ticket="detail"
                :run="run"
                :busy="busy"
              />
              <TicketTimeline :ticket="detail" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <TicketAiPanel
        v-if="detail.viewer.can_handle"
        :ticket="detail"
        :run="run"
        :busy="busy"
        :can-fill="chatCanSend"
        @fill="fillChat"
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
