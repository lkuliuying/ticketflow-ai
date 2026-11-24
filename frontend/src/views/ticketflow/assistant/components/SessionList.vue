<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import type { AssistantSession } from "@/api/ticketflow/assistant";
import ChatNew from "~icons/ri/chat-new-line";
import More from "~icons/ep/more-filled";

/** AI 助手左侧：本人历史会话，按最近更新排在前面；改名、删除由页面处理确认与请求 */
defineOptions({ name: "TicketFlowAssistantSessions" });

defineProps<{
  sessions: AssistantSession[];
  activeId: string | null;
  loading: boolean;
  creating: boolean;
  canCreate: boolean;
  canRename: boolean;
  canRemove: boolean;
}>();
const emit = defineEmits<{
  select: [pk: string];
  create: [];
  rename: [session: AssistantSession];
  remove: [session: AssistantSession];
}>();

const { t } = useI18n();

function onCommand(command: string, session: AssistantSession) {
  if (command === "rename") emit("rename", session);
  else if (command === "remove") emit("remove", session);
}
</script>

<template>
  <aside class="sessions flex flex-col gap-3" data-testid="assistant-sessions">
    <el-button
      v-if="canCreate"
      type="primary"
      :icon="ChatNew"
      :loading="creating"
      data-testid="session-create"
      @click="emit('create')"
    >
      {{ t("ticketflow.assistant.newSession") }}
    </el-button>
    <el-scrollbar v-loading="loading" class="flex-1">
      <el-empty
        v-if="!loading && sessions.length === 0"
        :image-size="64"
        :description="t('ticketflow.assistant.noSessions')"
      />
      <ul class="flex flex-col gap-1">
        <li
          v-for="session in sessions"
          :key="session.pk"
          class="session-item flex items-center gap-2"
          :class="{ 'is-active': session.pk === activeId }"
          :data-testid="`session-${session.pk}`"
          role="button"
          tabindex="0"
          :aria-current="session.pk === activeId ? 'true' : undefined"
          @click="emit('select', session.pk)"
          @keydown.enter="emit('select', session.pk)"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1 min-w-0">
              <span class="truncate text-sm">{{ session.title }}</span>
              <el-tag
                v-if="session.ticket_id"
                size="small"
                type="success"
                effect="plain"
                class="shrink-0"
              >
                {{ t("ticketflow.handoff.tag") }}
              </el-tag>
            </div>
            <div class="text-xs text-fg-muted">
              {{ dayjs(session.updated_time).format("MM-DD HH:mm") }}
            </div>
          </div>
          <el-dropdown
            v-if="canRename || canRemove"
            trigger="click"
            @command="(command: string) => onCommand(command, session)"
          >
            <el-button
              link
              :icon="More"
              :aria-label="t('ticketflow.assistant.sessionActions')"
              @click.stop
            />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="canRename" command="rename">
                  {{ t("ticketflow.assistant.rename") }}
                </el-dropdown-item>
                <el-dropdown-item v-if="canRemove" command="remove">
                  {{ t("ticketflow.assistant.remove") }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </li>
      </ul>
    </el-scrollbar>
  </aside>
</template>

<style scoped>
.session-item {
  padding: 8px 10px;
  cursor: pointer;
  border-radius: 6px;
}

.session-item:hover {
  background: var(--el-fill-color-light);
}

.session-item.is-active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
</style>
