<script lang="ts" setup>
import type { TicketRun } from "../utils/useTicketDetail";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessageBox } from "element-plus";
import { isSuccess } from "@/api/types";
import {
  ticketApi,
  type TicketAssignee,
  type TicketDetail,
  type TicketStatus
} from "@/api/ticketflow/tickets";
import {
  transitionButtonType,
  transitionLabelKey
} from "../utils/ticketActions";

/**
 * 工单操作区：流转按钮来自后端 `available_transitions`，指派区只在
 * `viewer.can_assign` 为真时出现；写操作交给父组件的 `run` 统一处理
 * 成功刷新与 409 冲突。
 */
defineOptions({ name: "TicketFlowTicketActions" });

const props = defineProps<{
  ticket: TicketDetail;
  run: TicketRun;
}>();

const { t } = useI18n();
const candidates = ref<TicketAssignee[]>([]);
const searching = ref(false);
const assigneeId = ref<number | null>(null);

async function transition(to: TicketStatus) {
  const label = t(transitionLabelKey(props.ticket.status, to));
  const note = await ElMessageBox.prompt(
    t("ticketflow.detail.notePrompt"),
    label,
    {
      inputType: "textarea",
      inputPlaceholder: t("ticketflow.detail.noteOptional"),
      confirmButtonText: label,
      cancelButtonText: t("buttons.cancel")
    }
  )
    .then(result => result.value ?? "")
    .catch(() => null);
  if (note === null) return;
  await props.run(
    () =>
      ticketApi.transition(props.ticket.pk, {
        target_status: to,
        version: props.ticket.version,
        ...(note.trim() ? { note: note.trim() } : {})
      }),
    t("ticketflow.detail.transitioned", { action: label })
  );
}

async function searchCandidates(keyword: string) {
  searching.value = true;
  const res = await ticketApi
    .assignees(props.ticket.pk, keyword)
    .catch(() => null);
  candidates.value = res && isSuccess(res) ? res.data : [];
  searching.value = false;
}

async function assign() {
  const ok = await props.run(
    () =>
      ticketApi.assign(props.ticket.pk, {
        assignee_id: assigneeId.value,
        version: props.ticket.version
      }),
    t("ticketflow.detail.assigned")
  );
  if (ok) assigneeId.value = null;
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div
      v-if="ticket.available_transitions.length"
      class="flex flex-wrap gap-2"
      data-testid="ticket-transitions"
    >
      <el-button
        v-for="to in ticket.available_transitions"
        :key="to"
        :type="transitionButtonType(ticket.status, to)"
        @click="transition(to)"
      >
        {{ t(transitionLabelKey(ticket.status, to)) }}
      </el-button>
    </div>
    <p v-else class="text-sm text-(--el-text-color-secondary) m-0">
      {{ t("ticketflow.detail.noTransition") }}
    </p>

    <div
      v-if="ticket.viewer.can_assign"
      class="flex items-center gap-2"
      data-testid="ticket-assign"
    >
      <el-select
        v-model="assigneeId"
        class="flex-1"
        filterable
        remote
        clearable
        :remote-method="searchCandidates"
        :loading="searching"
        :placeholder="t('ticketflow.detail.assigneePlaceholder')"
        @visible-change="(open: boolean) => open && searchCandidates('')"
      >
        <el-option
          v-for="item in candidates"
          :key="item.pk"
          :label="`${item.nickname || item.username}（${item.username}）`"
          :value="item.pk"
        >
          <span>{{ item.nickname || item.username }}</span>
          <span class="ml-2 text-(--el-text-color-secondary)">
            {{ item.username }} · {{ item.department_name || "—" }}
          </span>
        </el-option>
      </el-select>
      <el-button :disabled="assigneeId === null" @click="assign">
        {{ t("ticketflow.detail.assign") }}
      </el-button>
    </div>
  </div>
</template>
