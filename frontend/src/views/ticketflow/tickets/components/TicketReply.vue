<script lang="ts" setup>
import type { TicketRun } from "../utils/useTicketDetail";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";

/**
 * 内部备注框：仅技术员与管理员可见，用于记录内部排查进展。
 * 对外实时沟通统一由工单排查会话（TicketChatPanel）承接。
 */
defineOptions({ name: "TicketFlowTicketReply" });

const props = defineProps<{
  ticket: TicketDetail;
  run: TicketRun;
  busy: boolean;
}>();

const { t } = useI18n();
const body = ref("");
const sending = ref(false);

async function send() {
  const text = body.value.trim();
  if (!text) return;
  sending.value = true;
  const ok = await props.run(
    () =>
      ticketApi.comments(props.ticket.pk, {
        body: text,
        visibility: "INTERNAL"
      }),
    t("ticketflow.detail.internalNoteSent")
  );
  sending.value = false;
  if (ok) body.value = "";
}
</script>

<template>
  <div class="flex flex-col gap-2" data-testid="ticket-internal-note">
    <el-input
      v-model="body"
      type="textarea"
      :rows="3"
      maxlength="20000"
      show-word-limit
      :placeholder="t('ticketflow.detail.internalNotePlaceholder')"
    />
    <div class="flex-bc">
      <span class="text-sm text-(--el-text-color-secondary)">
        {{ t("ticketflow.detail.internalNote") }}
      </span>
      <el-button
        type="warning"
        plain
        size="small"
        :loading="sending"
        :disabled="!body.trim() || busy"
        @click="send"
      >
        {{ t("ticketflow.detail.send") }}
      </el-button>
    </div>
  </div>
</template>
