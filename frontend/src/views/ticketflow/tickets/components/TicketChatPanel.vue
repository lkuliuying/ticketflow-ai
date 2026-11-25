<script lang="ts" setup>
import { nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useUserStoreHook } from "@/store/modules/user";
import {
  ticketApi,
  type TicketChatState,
  type TicketDetail
} from "@/api/ticketflow/tickets";
import { useAuthorizedMedia } from "../utils/useAuthorizedMedia";
import { useTicketChat } from "../utils/useTicketChat";

defineOptions({ name: "TicketFlowTicketChatPanel" });

const props = defineProps<{ ticket: TicketDetail }>();
const emit = defineEmits<{ stateChange: [state: TicketChatState] }>();

const { t } = useI18n();
const userStore = useUserStoreHook();
const draft = ref("");
const listRef = ref<HTMLElement>();
const imageInputRef = ref<HTMLInputElement>();
const videoInputRef = ref<HTMLInputElement>();
const { urls: mediaUrls, ensure: ensureMedia } = useAuthorizedMedia();

const {
  messages,
  chatState,
  hasMore,
  loading,
  sending,
  uploading,
  load,
  connect,
  sendText,
  sendMedia
} = useTicketChat(
  () => props.ticket.pk,
  state => emit("stateChange", state)
);

function scrollToBottom() {
  void nextTick(() => {
    const el = listRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

watch(
  messages,
  rows => {
    for (const row of rows) {
      if (row.kind === "IMAGE" || row.kind === "VIDEO") {
        const fileUrl =
          row.file_url || ticketApi.chatFileUrl(props.ticket.pk, row.id);
        if (row.thumb_url) void ensureMedia(row.thumb_url);
        if (row.file_url) void ensureMedia(fileUrl);
      }
    }
    scrollToBottom();
  },
  { deep: true }
);

watch(
  () => props.ticket.chat_state,
  next => {
    if (next) {
      chatState.value = next;
      emit("stateChange", next);
    }
  },
  { immediate: true }
);

onMounted(() => {
  void load();
  connect();
});

async function submit() {
  const ok = await sendText(draft.value);
  if (ok) draft.value = "";
}

function onKeydown(event: Event | KeyboardEvent) {
  if (
    event instanceof KeyboardEvent &&
    event.key === "Enter" &&
    !event.shiftKey
  ) {
    event.preventDefault();
    void submit();
  }
}

function onMediaSelected(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (file) void sendMedia(file);
}

function onPaste(event: ClipboardEvent) {
  if (!chatState.value.can_send) return;
  const file = Array.from(event.clipboardData?.files ?? []).find(
    item => item.type.startsWith("image/") || item.type.startsWith("video/")
  );
  if (file) {
    event.preventDefault();
    void sendMedia(file);
  }
}

function isMine(senderId: number | null) {
  return senderId !== null && senderId === Number(userStore.pk);
}

function lockMessage(reason: TicketChatState["lock_reason"]) {
  return reason ? t(`ticketflow.chat.locked.${reason}`) : "";
}

defineExpose({
  fill: (text: string) => {
    draft.value = text;
  },
  refresh: () => load()
});
</script>

<template>
  <div
    class="flex flex-col gap-3 rounded border border-(--el-border-color) p-3"
    data-testid="ticket-chat-panel"
  >
    <el-alert
      v-if="!chatState.can_send && chatState.lock_reason"
      type="info"
      :closable="false"
      show-icon
      :title="lockMessage(chatState.lock_reason)"
      data-testid="ticket-chat-locked"
    />

    <div
      ref="listRef"
      v-loading="loading"
      class="flex flex-col gap-3 max-h-96 min-h-48 overflow-y-auto p-2 rounded bg-(--el-fill-color-lighter)"
      data-testid="ticket-chat-messages"
    >
      <div v-if="hasMore" class="text-center">
        <el-button
          link
          type="primary"
          size="small"
          @click="load(messages[0]?.id)"
        >
          {{ t("ticketflow.chat.loadMore") }}
        </el-button>
      </div>
      <el-empty
        v-if="!messages.length && !loading"
        :image-size="60"
        :description="t('ticketflow.chat.empty')"
      />
      <div
        v-for="item in messages"
        :key="item.id"
        class="flex flex-col gap-1"
        :class="isMine(item.sender_id) ? 'items-end' : 'items-start'"
        data-testid="ticket-chat-item"
      >
        <div class="text-xs text-(--el-text-color-secondary)">
          <span>{{ item.sender_name }}</span>
          <span class="ml-2">
            {{ new Date(item.created_time).toLocaleString() }}
          </span>
        </div>
        <div
          class="chat-bubble text-sm whitespace-pre-wrap wrap-break-word"
          :class="
            isMine(item.sender_id) ? 'chat-bubble--mine' : 'chat-bubble--peer'
          "
        >
          <template v-if="item.kind === 'IMAGE'">
            <el-image
              v-if="
                item.file_url &&
                (mediaUrls[item.thumb_url || ''] || mediaUrls[item.file_url])
              "
              :src="mediaUrls[item.thumb_url || ''] || mediaUrls[item.file_url]"
              :preview-src-list="
                mediaUrls[item.file_url] ? [mediaUrls[item.file_url]] : []
              "
              fit="cover"
              class="max-w-60 max-h-48 rounded cursor-pointer"
            />
            <span v-else class="text-xs">
              {{ item.media_meta?.filename || "[IMAGE]" }}
            </span>
          </template>
          <template v-else-if="item.kind === 'VIDEO'">
            <el-text
              v-if="item.media_expired"
              size="small"
              type="info"
              data-testid="ticket-chat-video-expired"
            >
              {{ t("ticketflow.chat.mediaExpired") }}
            </el-text>
            <video
              v-else-if="item.file_url && mediaUrls[item.file_url]"
              :src="mediaUrls[item.file_url]"
              controls
              preload="metadata"
              class="max-w-72 max-h-56 rounded"
            />
            <span v-else class="text-xs">
              {{ item.media_meta?.filename || "[VIDEO]" }}
            </span>
          </template>
          <div v-if="item.content">{{ item.content }}</div>
        </div>
      </div>
    </div>

    <div
      v-if="chatState.can_send"
      class="flex flex-col gap-2"
      data-testid="ticket-chat-composer"
      @paste="onPaste"
    >
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        maxlength="4000"
        show-word-limit
        :placeholder="t('ticketflow.chat.placeholder')"
        data-testid="ticket-chat-input"
        @keydown="onKeydown"
      />
      <div class="flex-bc">
        <div class="flex items-center gap-2">
          <input
            ref="imageInputRef"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            class="hidden"
            @change="onMediaSelected"
          />
          <input
            ref="videoInputRef"
            type="file"
            accept="video/mp4,video/webm"
            class="hidden"
            @change="onMediaSelected"
          />
          <el-button
            size="small"
            plain
            :loading="uploading"
            data-testid="ticket-chat-upload-image"
            @click="imageInputRef?.click()"
          >
            {{ t("ticketflow.chat.uploadImage") }}
          </el-button>
          <el-button
            size="small"
            plain
            :loading="uploading"
            data-testid="ticket-chat-upload-video"
            @click="videoInputRef?.click()"
          >
            {{ t("ticketflow.chat.uploadVideo") }}
          </el-button>
        </div>
        <el-button
          type="primary"
          size="small"
          :loading="sending"
          :disabled="!draft.trim()"
          data-testid="ticket-chat-send"
          @click="submit"
        >
          {{ t("ticketflow.chat.send") }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-bubble {
  max-width: 82%;
  padding: 8px 12px;
  border-radius: var(--el-border-radius-base);
}

.chat-bubble--mine {
  color: var(--el-color-white);
  background: var(--el-color-primary);
}

.chat-bubble--peer {
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}
</style>
