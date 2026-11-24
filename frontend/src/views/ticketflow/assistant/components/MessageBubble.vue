<script lang="ts" setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import AiMarkdown from "@/components/AiMarkdown";
import type {
  AssistantMessage,
  AssistantReference,
  FeedbackVote
} from "@/api/ticketflow/assistant";
import { openArticleDetail } from "../../knowledge/utils/articleDetailDrawer";
import ThumbUp from "~icons/ri/thumb-up-line";
import ThumbUpFill from "~icons/ri/thumb-up-fill";
import ThumbDown from "~icons/ri/thumb-down-line";
import ThumbDownFill from "~icons/ri/thumb-down-fill";

/**
 * 一条问答消息：问题靠右显示原文，回答渲染 Markdown 并列出引用的已发布文章。
 * `feedbackable` 时回答下方显示点赞 / 点踩（只读的工单对话与流式中的回答不显示）。
 */
defineOptions({ name: "TicketFlowAssistantMessage" });

const props = withDefaults(
  defineProps<{
    message: Pick<
      AssistantMessage,
      "role" | "content" | "references" | "status" | "feedback"
    >;
    streaming?: boolean;
    feedbackable?: boolean;
  }>(),
  { streaming: false, feedbackable: false }
);
const emit = defineEmits<{ vote: [vote: FeedbackVote] }>();

const { t } = useI18n();
const isUser = computed(() => props.message.role === "user");
const vote = computed(() => props.message.feedback?.vote ?? null);

function referenceLabel(reference: AssistantReference) {
  return reference.title || reference.article_id.slice(0, 8);
}

function openReference(reference: AssistantReference) {
  openArticleDetail({
    pk: reference.article_id,
    title: referenceLabel(reference)
  });
}
</script>

<template>
  <div
    class="flex"
    :class="isUser ? 'justify-end' : 'justify-start'"
    :data-testid="isUser ? 'assistant-question' : 'assistant-answer'"
  >
    <div
      v-if="isUser"
      class="bubble bubble--user whitespace-pre-wrap wrap-break-word"
    >
      {{ message.content }}
    </div>
    <div v-else class="bubble bubble--answer flex flex-col gap-2">
      <AiMarkdown
        v-if="message.content || streaming"
        :content="message.content"
        :streaming="streaming"
      />
      <el-text
        v-if="!streaming && message.status !== 'complete'"
        size="small"
        :type="message.status === 'failed' ? 'danger' : 'warning'"
        data-testid="answer-status"
      >
        {{ t(`ticketflow.assistant.answerStatus.${message.status}`) }}
      </el-text>
      <div
        v-if="message.references.length"
        class="flex flex-col items-start gap-1 text-xs"
        data-testid="answer-references"
      >
        <span class="text-fg-muted">
          {{
            t("ticketflow.assistant.references", {
              count: message.references.length
            })
          }}
        </span>
        <el-button
          v-for="reference in message.references"
          :key="reference.article_id"
          link
          type="primary"
          size="small"
          class="ml-0! max-w-full"
          :title="referenceLabel(reference)"
          @click="openReference(reference)"
        >
          <span class="truncate">{{ referenceLabel(reference) }}</span>
        </el-button>
      </div>
      <div
        v-if="feedbackable && !streaming"
        class="flex items-center gap-1"
        data-testid="answer-feedback"
      >
        <el-button
          link
          size="small"
          :type="vote === 'up' ? 'primary' : 'info'"
          :icon="vote === 'up' ? ThumbUpFill : ThumbUp"
          :aria-label="t('ticketflow.assistant.up')"
          :aria-pressed="vote === 'up'"
          data-testid="vote-up"
          @click="emit('vote', 'up')"
        />
        <el-button
          link
          size="small"
          :type="vote === 'down' ? 'danger' : 'info'"
          :icon="vote === 'down' ? ThumbDownFill : ThumbDown"
          :aria-label="t('ticketflow.assistant.down')"
          :aria-pressed="vote === 'down'"
          data-testid="vote-down"
          @click="emit('vote', 'down')"
        />
        <span v-if="message.feedback?.reason" class="text-xs text-fg-muted">
          {{ t(`ticketflow.assistant.reasonValue.${message.feedback.reason}`) }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble {
  max-width: min(720px, 85%);
  padding: 10px 14px;
  border-radius: 10px;
}

.bubble--user {
  color: var(--el-color-white);
  background: var(--el-color-primary);
}

.bubble--answer {
  background: var(--el-fill-color-light);
}
</style>
