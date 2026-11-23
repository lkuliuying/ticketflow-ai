<script lang="ts" setup>
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessageBox } from "element-plus";
import { usePageAuth } from "@/router/utils";
import { message } from "@/utils/message";
import type { AssistantSession } from "@/api/ticketflow/assistant";
import type { TicketItem } from "@/api/ticketflow/tickets";
import { openTicketDetail } from "../tickets/utils/ticketDetailDrawer";
import SessionList from "./components/SessionList.vue";
import ChatPanel from "./components/ChatPanel.vue";
import { useAssistantSessions } from "./utils/useAssistantSessions";
import Robot from "~icons/ri/robot-2-line";

defineOptions({
  name: "TicketFlowAssistant" // 必须定义，用于菜单自动匹配组件
});

/** 首个问题自动作为会话标题时截取的长度 */
const AUTO_TITLE_MAX = 30;

const { t } = useI18n();
const auth = usePageAuth("TicketFlowAssistant", ["messages", "feedback"]);
const ticketAuth = usePageAuth("TicketFlowTickets");
const {
  sessions,
  activeId,
  active,
  loading,
  creating,
  load,
  create,
  rename,
  remove,
  drop,
  touch
} = useAssistantSessions();

async function promptRename(session: AssistantSession) {
  const result = await ElMessageBox.prompt(
    t("ticketflow.assistant.renamePrompt"),
    t("ticketflow.assistant.rename"),
    {
      inputValue: session.title,
      inputValidator: value => {
        const title = value.trim();
        return title.length > 0 && title.length <= 200
          ? true
          : t("ticketflow.assistant.titleInvalid");
      }
    }
  ).catch(() => null);
  if (!result) return;
  if (await rename(session.pk, result.value.trim())) {
    message(t("ticketflow.assistant.renamed"), { type: "success" });
  }
}

async function confirmRemove(session: AssistantSession) {
  const confirmed = await ElMessageBox.confirm(
    t("ticketflow.assistant.removeConfirm", { title: session.title }),
    t("ticketflow.assistant.remove"),
    { type: "warning" }
  )
    .then(() => true)
    .catch(() => false);
  if (confirmed && (await remove(session.pk))) {
    message(t("ticketflow.assistant.removed"), { type: "success" });
  }
}

/** 首个问题记录后用问题开头作标题，便于在侧栏区分会话 */
function onAsked(pk: string, first: boolean, text: string) {
  touch(pk);
  if (first && auth.partialUpdate) {
    void rename(pk, text.replace(/\s+/g, " ").slice(0, AUTO_TITLE_MAX));
  }
}

/** 转人工成功：会话已由服务端转入工单，从侧栏移除并提供跳转 */
function onHandedOff(pk: string, ticket: TicketItem) {
  drop(pk);
  message(t("ticketflow.handoff.created", { number: ticket.number }), {
    type: "success"
  });
  openTicketDetail(ticket, {});
}

onMounted(load);
</script>

<template>
  <div class="main assistant flex flex-col gap-4 md:flex-row">
    <el-card shadow="never" class="md:w-72 shrink-0" body-class="h-full">
      <SessionList
        :sessions="sessions"
        :active-id="activeId"
        :loading="loading"
        :creating="creating"
        :can-create="Boolean(auth.create)"
        :can-rename="Boolean(auth.partialUpdate)"
        :can-remove="Boolean(auth.destroy)"
        class="h-full"
        @select="pk => (activeId = pk)"
        @create="create"
        @rename="promptRename"
        @remove="confirmRemove"
      />
    </el-card>
    <el-card shadow="never" class="flex-1 min-w-0" body-class="h-full">
      <ChatPanel
        v-if="active"
        :key="active.pk"
        :session="active"
        :can-feedback="Boolean(auth.feedback)"
        :can-handoff="Boolean(ticketAuth.create)"
        class="h-full"
        @asked="onAsked"
        @handed-off="onHandedOff"
      />
      <div
        v-else
        class="h-full flex-c flex-col gap-4 text-center"
        data-testid="assistant-welcome"
      >
        <component :is="Robot" class="size-12 text-(--el-color-primary)" />
        <div>
          <h3 class="m-0">{{ t("ticketflow.assistant.welcomeTitle") }}</h3>
          <p class="text-sm text-fg-muted mt-2">
            {{ t("ticketflow.assistant.welcomeHint") }}
          </p>
        </div>
        <el-button
          v-if="auth.create"
          type="primary"
          :loading="creating"
          @click="create"
        >
          {{ t("ticketflow.assistant.newSession") }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.assistant {
  height: calc(100vh - 140px);
  min-height: 480px;
}
</style>
