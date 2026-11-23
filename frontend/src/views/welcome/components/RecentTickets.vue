<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import type { TicketItem } from "@/api/ticketflow/tickets";
import {
  PRIORITY_TONE,
  SLA_TONE,
  STATUS_TONE
} from "@/views/ticketflow/tickets/utils/ticketColumns";

/** 工作台“最近工单”：当前身份可见范围内最近更新的几张工单，点击打开详情 */
defineOptions({ name: "WorkbenchRecentTickets" });

defineProps<{ tickets: TicketItem[]; loading: boolean }>();
const emit = defineEmits<{ open: [ticket: TicketItem]; more: [] }>();

const { t } = useI18n();
const RISKY = new Set(["DUE_SOON", "OVERDUE"]);
</script>

<template>
  <el-card shadow="never" class="h-full" body-class="p-0!">
    <template #header>
      <div class="flex-bc">
        <span class="font-medium">{{ t("workbench.recentTickets") }}</span>
        <el-button link type="primary" @click="emit('more')">
          {{ t("workbench.viewAll") }}
        </el-button>
      </div>
    </template>
    <div v-loading="loading" class="min-h-40">
      <el-empty
        v-if="!loading && tickets.length === 0"
        :image-size="72"
        :description="t('workbench.noTickets')"
      />
      <button
        v-for="ticket in tickets"
        :key="ticket.pk"
        type="button"
        class="ticket-row"
        data-testid="workbench-ticket"
        @click="emit('open', ticket)"
      >
        <span class="flex items-center gap-2 min-w-0">
          <el-tag :type="PRIORITY_TONE[ticket.priority]" size="small">
            {{ ticket.priority }}
          </el-tag>
          <span class="truncate text-fg">{{ ticket.title }}</span>
        </span>
        <span class="flex items-center gap-3 shrink-0">
          <el-tag
            v-if="RISKY.has(ticket.sla_state)"
            :type="SLA_TONE[ticket.sla_state]"
            size="small"
            effect="plain"
          >
            {{ t(`ticketflow.slaValue.${ticket.sla_state}`) }}
          </el-tag>
          <el-tag
            :type="STATUS_TONE[ticket.status]"
            size="small"
            effect="light"
          >
            {{ t(`ticketflow.statusValue.${ticket.status}`) }}
          </el-tag>
          <span class="text-xs text-fg-muted w-20 text-right">
            {{ dayjs(ticket.updated_time).format("MM-DD HH:mm") }}
          </span>
        </span>
      </button>
    </div>
  </el-card>
</template>

<style lang="scss" scoped>
.ticket-row {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 20px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);

  &:last-child {
    border-bottom: 0;
  }

  &:hover,
  &:focus-visible {
    outline: none;
    background: var(--el-fill-color-light);
  }
}
</style>
