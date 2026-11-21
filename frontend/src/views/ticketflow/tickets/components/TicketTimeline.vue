<script lang="ts" setup>
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { isSuccess } from "@/api/types";
import {
  ticketApi,
  type TicketDetail,
  type TimelineEntry
} from "@/api/ticketflow/tickets";
import { logActionKey } from "../utils/ticketActions";
import { STATUS_TONE } from "../utils/ticketColumns";

/**
 * 时间线：首屏用详情接口带回的第一页（日志与评论合并、按时间倒序），
 * 超过一页时按需调用 `/timeline` 继续翻页。内部备注与内部日志是否可见
 * 由后端按当前用户过滤，这里只负责展示。
 */
defineOptions({ name: "TicketFlowTicketTimeline" });

const PAGE_SIZE = 20;
const props = defineProps<{ ticket: TicketDetail }>();
const { t } = useI18n();

const entries = ref<TimelineEntry[]>([]);
const total = ref(0);
const page = ref(1);
const loadingMore = ref(false);

watch(
  () => props.ticket,
  ticket => {
    entries.value = [...ticket.timeline.results];
    total.value = ticket.timeline.total;
    page.value = 1;
  },
  { immediate: true }
);

const hasMore = computed(() => entries.value.length < total.value);

async function loadMore() {
  loadingMore.value = true;
  const next = page.value + 1;
  const res = await ticketApi
    .timeline(props.ticket.pk, { page: next, size: PAGE_SIZE })
    .catch(() => null);
  if (res && isSuccess(res)) {
    const seen = new Set(entries.value.map(item => item.id));
    entries.value.push(...res.data.results.filter(item => !seen.has(item.id)));
    total.value = res.data.total ?? total.value;
    page.value = next;
  }
  loadingMore.value = false;
}

function statusText(status: string | null) {
  return status ? t(`ticketflow.statusValue.${status}`) : "";
}
</script>

<template>
  <div data-testid="ticket-timeline">
    <el-timeline v-if="entries.length" class="pl-1">
      <el-timeline-item
        v-for="item in entries"
        :key="item.id"
        :timestamp="new Date(item.created_time).toLocaleString()"
        :type="
          item.kind === 'comment'
            ? item.visibility === 'INTERNAL'
              ? 'warning'
              : 'primary'
            : 'info'
        "
        placement="top"
      >
        <div class="flex items-center gap-2 text-sm">
          <b>{{ item.actor }}</b>
          <template v-if="item.kind === 'comment'">
            <el-tag
              size="small"
              :type="item.visibility === 'INTERNAL' ? 'warning' : 'primary'"
            >
              {{ t(`ticketflow.visibility.${item.visibility}`) }}
            </el-tag>
          </template>
          <template v-else>
            <span>{{ t(logActionKey(item.action)) }}</span>
            <el-tag
              v-if="item.from_status && item.from_status !== item.to_status"
              size="small"
              :type="STATUS_TONE[item.from_status]"
              effect="plain"
            >
              {{ statusText(item.from_status) }}
            </el-tag>
            <span
              v-if="item.from_status && item.from_status !== item.to_status"
            >
              →
            </span>
            <el-tag
              v-if="item.to_status"
              size="small"
              :type="STATUS_TONE[item.to_status]"
            >
              {{ statusText(item.to_status) }}
            </el-tag>
          </template>
        </div>
        <p
          v-if="item.body"
          class="mt-1 mb-0 whitespace-pre-wrap wrap-break-word text-sm"
        >
          {{ item.body }}
        </p>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else :description="t('ticketflow.detail.noTimeline')" />
    <div v-if="hasMore" class="text-center">
      <el-button link type="primary" :loading="loadingMore" @click="loadMore">
        {{ t("ticketflow.detail.loadMore", { rest: total - entries.length }) }}
      </el-button>
    </div>
  </div>
</template>
