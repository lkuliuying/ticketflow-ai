<script lang="ts" setup>
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { isSuccess } from "@/api/types";
import {
  ticketAssistantSession,
  type AssistantMessage
} from "@/api/ticketflow/assistant";
import MessageBubble from "./MessageBubble.vue";

/** 工单关联的 AI 对话：只读，不显示评价；提交人、当前处理人与管理员可见 */
defineOptions({ name: "TicketFlowAssistantTranscript" });

const PAGE_SIZE = 100;
const MAX_PAGES = 10;

const props = defineProps<{ ticketId: string }>();

const { t } = useI18n();
const messages = ref<AssistantMessage[]>([]);
const loading = ref(true);
const failed = ref(false);

async function load() {
  loading.value = true;
  failed.value = false;
  const rows: AssistantMessage[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const res = await ticketAssistantSession(props.ticketId, {
      page,
      size: PAGE_SIZE
    }).catch(() => null);
    if (!res || !isSuccess(res) || !res.data) {
      failed.value = page === 1;
      break;
    }
    rows.push(...res.data.messages.results);
    if (rows.length >= res.data.messages.total) break;
  }
  messages.value = rows;
  loading.value = false;
}

defineExpose({ load });
onMounted(load);
</script>

<template>
  <div
    v-loading="loading"
    class="flex flex-col gap-3 min-h-40"
    data-testid="assistant-transcript"
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      :title="t('ticketflow.assistant.transcriptHint')"
    />
    <el-empty
      v-if="!loading && (failed || messages.length === 0)"
      :image-size="64"
      :description="
        failed
          ? t('ticketflow.assistant.transcriptFailed')
          : t('ticketflow.assistant.emptyChat')
      "
    />
    <MessageBubble v-for="item in messages" :key="item.pk" :message="item" />
  </div>
</template>
