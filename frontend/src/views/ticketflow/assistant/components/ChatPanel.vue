<script lang="ts" setup>
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { ScrollbarInstance } from "element-plus";
import type {
  AssistantMessage,
  AssistantSession,
  FeedbackVote
} from "@/api/ticketflow/assistant";
import type { TicketItem } from "@/api/ticketflow/tickets";
import { isSuccess } from "@/api/types";
import { message as toast } from "@/utils/message";
import { assistantSessionApi } from "@/api/ticketflow/assistant";
import MessageBubble from "./MessageBubble.vue";
import { LOCAL_PREFIX, useAssistantChat } from "../utils/useAssistantChat";
import {
  loadHandoffDraft,
  openDownvoteDialog,
  openHandoffDialog
} from "../utils/assistantDialogs";
import Send from "~icons/ri/send-plane-2-line";
import Stop from "~icons/ri/stop-circle-line";
import Service from "~icons/ri/customer-service-2-line";

/**
 * AI 助手右侧：当前会话的问答、流式回答、点赞点踩与转人工提单。
 * Enter 发送、Shift+Enter 换行；问题没能记录时把原文放回输入框。
 */
defineOptions({ name: "TicketFlowAssistantChat" });

const QUESTION_MAX = 4000;

const props = defineProps<{
  session: AssistantSession;
  canFeedback: boolean;
  canHandoff: boolean;
}>();
const emit = defineEmits<{
  asked: [pk: string, first: boolean, text: string];
  handedOff: [pk: string, ticket: TicketItem];
}>();

const { t } = useI18n();
const { messages, loading, pending, chat, streaming, ask, stop, setFeedback } =
  useAssistantChat(() => props.session.pk);
const input = ref("");
const error = ref("");
const drafting = ref(false);
const scrollbar = ref<ScrollbarInstance>();

const questions = computed(() =>
  messages.value.filter(m => m.role === "user").map(m => m.content)
);
const busy = computed(() => streaming.value || drafting.value);

function scrollToBottom() {
  void nextTick(() => scrollbar.value?.setScrollTop(Number.MAX_SAFE_INTEGER));
}
watch(
  () => [messages.value.length, chat.value.text, pending.value],
  scrollToBottom
);

async function send() {
  const text = input.value.trim();
  if (!text || busy.value || text.length > QUESTION_MAX) return;
  const first = messages.value.length === 0;
  const pk = props.session.pk;
  input.value = "";
  error.value = "";
  const recorded = await ask(text);
  if (recorded) {
    emit("asked", pk, first, text);
    return;
  }
  input.value = text;
  error.value =
    chat.value.error?.detail || t("ticketflow.assistant.sendFailed");
}

function onKeydown(event: Event | KeyboardEvent) {
  if (!(event instanceof KeyboardEvent)) return;
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  void send();
}

function feedbackable(message: AssistantMessage) {
  return (
    props.canFeedback &&
    message.role === "assistant" &&
    !message.pk.startsWith(LOCAL_PREFIX)
  );
}

async function vote(message: AssistantMessage, value: FeedbackVote) {
  if (value === "down") {
    openDownvoteDialog(props.session.pk, message.pk, message.feedback, saved =>
      setFeedback(message.pk, saved)
    );
    return;
  }
  if (message.feedback?.vote === "up") return;
  const res = await assistantSessionApi
    .feedback(props.session.pk, message.pk, { vote: "up" })
    .catch(() => null);
  if (res && isSuccess(res) && res.data) {
    setFeedback(message.pk, res.data);
    toast(t("ticketflow.assistant.feedbackSaved"), { type: "success" });
  }
}

async function handoff() {
  if (busy.value) return;
  drafting.value = true;
  const draft = await loadHandoffDraft(props.session.pk, questions.value);
  drafting.value = false;
  const pk = props.session.pk;
  openHandoffDialog(pk, draft, ticket => emit("handedOff", pk, ticket));
}
</script>

<template>
  <section class="chat flex flex-col min-h-0" data-testid="assistant-chat">
    <header
      class="flex-bc gap-2 pb-3 border-b border-(--el-border-color-lighter)"
    >
      <h3 class="m-0 truncate text-base">{{ session.title }}</h3>
      <el-button
        v-if="canHandoff"
        :icon="Service"
        :loading="drafting"
        :disabled="streaming || questions.length === 0"
        data-testid="assistant-handoff"
        @click="handoff"
      >
        {{ t("ticketflow.handoff.action") }}
      </el-button>
    </header>

    <el-scrollbar ref="scrollbar" v-loading="loading" class="flex-1 py-3">
      <div class="flex flex-col gap-3 pr-2">
        <el-empty
          v-if="!loading && messages.length === 0 && pending === null"
          :image-size="80"
          :description="t('ticketflow.assistant.emptyChat')"
        />
        <MessageBubble
          v-for="item in messages"
          :key="item.pk"
          :message="item"
          :feedbackable="feedbackable(item)"
          @vote="value => vote(item, value)"
        />
        <template v-if="pending !== null">
          <MessageBubble
            :message="{
              role: 'user',
              content: pending,
              references: [],
              status: 'complete'
            }"
          />
          <MessageBubble
            :message="{
              role: 'assistant',
              content: chat.text,
              references: chat.references,
              status: 'complete'
            }"
            :streaming="streaming"
          />
        </template>
      </div>
    </el-scrollbar>

    <footer class="flex flex-col gap-2 pt-3">
      <el-alert
        v-if="error"
        type="error"
        :title="error"
        show-icon
        data-testid="assistant-error"
        @close="error = ''"
      />
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        :maxlength="QUESTION_MAX"
        :placeholder="t('ticketflow.assistant.placeholder')"
        :disabled="drafting"
        data-testid="assistant-input"
        @keydown="onKeydown"
      />
      <div class="flex-bc">
        <span class="text-xs text-fg-muted">
          {{ t("ticketflow.assistant.inputHint") }}
        </span>
        <el-button
          v-if="streaming"
          type="danger"
          plain
          :icon="Stop"
          data-testid="assistant-stop"
          @click="stop"
        >
          {{ t("ticketflow.assistant.stop") }}
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="Send"
          :disabled="!input.trim() || busy"
          data-testid="assistant-send"
          @click="send"
        >
          {{ t("ticketflow.assistant.send") }}
        </el-button>
      </div>
    </footer>
  </section>
</template>
