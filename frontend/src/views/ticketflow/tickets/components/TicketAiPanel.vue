<script lang="ts" setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { TicketDetail } from "@/api/ticketflow/tickets";
import type { TicketRun } from "../utils/useTicketDetail";
import { useReplyStream, useTicketAnalysis } from "../utils/useTicketAi";
import { PRIORITY_TONE } from "../utils/ticketColumns";
import type { ReplyReference } from "@/api/ticketflow/ai";
import { openArticleDetail } from "../../knowledge/utils/articleDetailDrawer";

/**
 * 详情右侧 AI 面板：工单分析与一键采纳、流式回复建议。
 * 只在 `viewer.can_handle` 时挂载；生成的回复只填入回复框，发送仍由用户操作。
 */
defineOptions({ name: "TicketFlowTicketAiPanel" });

const props = defineProps<{
  ticket: TicketDetail;
  run: TicketRun;
  busy: boolean;
  /** 详情里有回复框时才能填入（例如已关闭工单没有回复框） */
  canFill: boolean;
}>();
const emit = defineEmits<{ fill: [text: string] }>();

const { t, te } = useI18n();
const { analysis, analyzing, stale, analyze, adopt } = useTicketAnalysis(
  () => props.ticket,
  props.run
);
const { reply, generate, stop } = useReplyStream(() => props.ticket.pk);

const streaming = computed(() => reply.value.status === "streaming");
const statusText = computed(() => {
  const { status, error } = reply.value;
  if (status === "error") return error?.detail || t("ticketflow.ai.failed");
  if (status === "idle" || status === "done") return "";
  return t(`ticketflow.ai.status.${status}`);
});

function category(value: string) {
  const key = `ticketflow.categoryValue.${value}`;
  return te(key) ? t(key) : value;
}

/** 引用文章的显示名：标题缺失时用文章 ID 前 8 位 */
function referenceLabel(reference: ReplyReference) {
  return reference.title || reference.article_id.slice(0, 8);
}

/** 点击引用标题，在知识库详情抽屉里打开对应文章 */
function openReference(reference: ReplyReference) {
  openArticleDetail({
    pk: reference.article_id,
    title: referenceLabel(reference)
  });
}
</script>

<template>
  <aside class="flex flex-col gap-4" data-testid="ticket-ai-panel">
    <section class="flex flex-col gap-2">
      <div class="flex-bc">
        <h4 class="m-0">{{ t("ticketflow.ai.analysis") }}</h4>
        <el-button
          size="small"
          :loading="analyzing"
          data-testid="ai-analyze"
          @click="analyze"
        >
          {{
            analysis ? t("ticketflow.ai.reanalyze") : t("ticketflow.ai.analyze")
          }}
        </el-button>
      </div>
      <template v-if="analysis">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item :label="t('ticketflow.category')">
            {{ category(analysis.category) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.priority')">
            <el-tag
              :type="PRIORITY_TONE[analysis.suggested_priority]"
              effect="plain"
              size="small"
            >
              {{ analysis.suggested_priority }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.ai_summary')">
            <div class="whitespace-pre-wrap wrap-break-word">
              {{ analysis.summary }}
            </div>
          </el-descriptions-item>
          <el-descriptions-item :label="t('ticketflow.ai_tags')">
            <div class="flex flex-wrap gap-1">
              <el-tag v-for="tag in analysis.tags" :key="tag" size="small">
                {{ tag }}
              </el-tag>
            </div>
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="stale"
          type="warning"
          :closable="false"
          show-icon
          :title="
            t('ticketflow.ai.stale', {
              from: analysis.ticket_version,
              to: ticket.version
            })
          "
        />
        <el-button
          type="primary"
          plain
          :disabled="stale || busy"
          data-testid="ai-adopt"
          @click="adopt"
        >
          {{ t("ticketflow.ai.adopt") }}
        </el-button>
      </template>
      <span v-else class="text-sm text-(--el-text-color-secondary)">
        {{ t("ticketflow.ai.analysisHint") }}
      </span>
    </section>

    <section class="flex flex-col gap-2">
      <div class="flex-bc">
        <h4 class="m-0">{{ t("ticketflow.ai.reply") }}</h4>
        <el-button
          v-if="streaming"
          size="small"
          type="danger"
          plain
          data-testid="ai-stop"
          @click="stop"
        >
          {{ t("ticketflow.ai.stop") }}
        </el-button>
        <el-button
          v-else
          size="small"
          data-testid="ai-generate"
          @click="generate"
        >
          {{
            reply.status === "idle"
              ? t("ticketflow.ai.generate")
              : t("ticketflow.ai.regenerate")
          }}
        </el-button>
      </div>
      <div
        v-if="streaming || reply.text"
        class="ai-reply whitespace-pre-wrap wrap-break-word text-sm"
        data-testid="ai-reply-text"
        aria-live="polite"
      >
        {{ reply.text }}<span v-if="streaming" class="ai-reply__cursor" />
      </div>
      <div v-if="statusText" class="flex items-center gap-2">
        <el-text
          size="small"
          :type="reply.status === 'error' ? 'danger' : 'info'"
          data-testid="ai-reply-status"
        >
          {{ statusText }}
        </el-text>
        <el-button
          v-if="reply.status === 'error' && reply.error?.retryable"
          link
          type="primary"
          size="small"
          data-testid="ai-retry"
          @click="generate"
        >
          {{ t("ticketflow.ai.retry") }}
        </el-button>
      </div>
      <div
        v-if="reply.references.length"
        class="flex flex-col gap-1 text-xs"
        data-testid="ai-references"
      >
        <span class="text-(--el-text-color-secondary)">
          {{
            t("ticketflow.ai.references", { count: reply.references.length })
          }}
        </span>
        <el-button
          v-for="reference in reply.references"
          :key="reference.article_id"
          link
          type="primary"
          size="small"
          class="justify-start! ml-0! max-w-full"
          :title="referenceLabel(reference)"
          @click="openReference(reference)"
        >
          <span class="truncate">{{ referenceLabel(reference) }}</span>
        </el-button>
      </div>
      <div class="flex gap-2">
        <el-button
          type="primary"
          :disabled="!canFill || reply.status !== 'done' || !reply.text.trim()"
          data-testid="ai-fill"
          @click="emit('fill', reply.text)"
        >
          {{ t("ticketflow.ai.fill") }}
        </el-button>
        <el-text v-if="!canFill" size="small" type="info">
          {{ t("ticketflow.ai.noReplyBox") }}
        </el-text>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.ai-reply {
  min-height: 96px;
  max-height: 320px;
  padding: 8px 10px;
  overflow-y: auto;
  background: var(--el-fill-color-light);
  border-radius: var(--el-border-radius-base);
}

.ai-reply__cursor {
  display: inline-block;
  width: 6px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--el-color-primary);
  animation: ai-blink 1s steps(2) infinite;
}

@keyframes ai-blink {
  50% {
    opacity: 0;
  }
}
</style>
