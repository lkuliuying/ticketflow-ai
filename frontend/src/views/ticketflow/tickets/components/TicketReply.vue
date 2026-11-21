<script lang="ts" setup>
import type { TicketRun } from "../utils/useTicketDetail";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  ticketApi,
  type CommentVisibility,
  type TicketDetail
} from "@/api/ticketflow/tickets";

/**
 * 回复框：处理人可选“对外回复 / 内部备注”，提交人只能对外回复。
 * 回复只追加、不需要版本号；客服的首条对外回复会写入首次响应时间。
 */
defineOptions({ name: "TicketFlowTicketReply" });

const props = defineProps<{
  ticket: TicketDetail;
  run: TicketRun;
}>();

const { t } = useI18n();
const body = ref("");
const visibility = ref<CommentVisibility>("PUBLIC");
const sending = ref(false);

async function send() {
  const text = body.value.trim();
  if (!text) return;
  sending.value = true;
  const ok = await props.run(
    () =>
      ticketApi.comments(props.ticket.pk, {
        body: text,
        visibility: props.ticket.viewer.can_comment_internal
          ? visibility.value
          : "PUBLIC"
      }),
    t("ticketflow.detail.replied")
  );
  sending.value = false;
  if (ok) body.value = "";
}

defineExpose({ fill: (text: string) => (body.value = text) });
</script>

<template>
  <div class="flex flex-col gap-2" data-testid="ticket-reply">
    <el-input
      v-model="body"
      type="textarea"
      :rows="4"
      maxlength="20000"
      show-word-limit
      :placeholder="t('ticketflow.detail.replyPlaceholder')"
    />
    <div class="flex-bc">
      <el-radio-group
        v-if="ticket.viewer.can_comment_internal"
        v-model="visibility"
        size="small"
      >
        <el-radio-button value="PUBLIC">
          {{ t("ticketflow.visibility.PUBLIC") }}
        </el-radio-button>
        <el-radio-button value="INTERNAL">
          {{ t("ticketflow.visibility.INTERNAL") }}
        </el-radio-button>
      </el-radio-group>
      <span v-else class="text-sm text-(--el-text-color-secondary)">
        {{ t("ticketflow.visibility.PUBLIC") }}
      </span>
      <el-button
        type="primary"
        :loading="sending"
        :disabled="!body.trim()"
        @click="send"
      >
        {{ t("ticketflow.detail.send") }}
      </el-button>
    </div>
  </div>
</template>
