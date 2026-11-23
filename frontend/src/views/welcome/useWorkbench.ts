import { computed, ref } from "vue";
import { isSuccess } from "@/api/types";
import {
  ticketApi,
  type TicketDashboard,
  type TicketItem
} from "@/api/ticketflow/tickets";
import { knowledgeApi, type ArticleItem } from "@/api/ticketflow/knowledge";

export const RECENT_TICKET_COUNT = 6;
export const LATEST_ARTICLE_COUNT = 5;

export type WorkbenchStats = {
  pending: number;
  inProgress: number;
  verifying: number;
  slaRisk: number;
};

/**
 * 首页计数口径：待处理含新建与重开，SLA 风险含即将超时与已超时。
 * 数据范围由后端按当前身份限定，这里不做角色判断。
 */
export function summarize(data: TicketDashboard | null): WorkbenchStats {
  const status = data?.status ?? {};
  const sla = data?.sla;
  return {
    pending: (status.OPEN ?? 0) + (status.REOPENED ?? 0),
    inProgress: status.IN_PROGRESS ?? 0,
    verifying: status.PENDING_VERIFY ?? 0,
    slaRisk: (sla?.DUE_SOON ?? 0) + (sla?.OVERDUE ?? 0)
  };
}

/** 工作台数据：看板计数、最近工单与最新已发布文章，三路并行加载、互不阻塞 */
export function useWorkbench() {
  const dashboard = ref<TicketDashboard | null>(null);
  const tickets = ref<TicketItem[]>([]);
  const articles = ref<ArticleItem[]>([]);
  const loading = ref(false);
  const stats = computed(() => summarize(dashboard.value));

  async function loadDashboard() {
    const res = await ticketApi.dashboard().catch(() => null);
    if (res && isSuccess(res)) dashboard.value = res.data;
  }

  async function loadTickets() {
    const res = await ticketApi
      .list<TicketItem>({
        page: 1,
        size: RECENT_TICKET_COUNT,
        ordering: "-updated_time"
      })
      .catch(() => null);
    if (res && isSuccess(res)) tickets.value = res.data.results ?? [];
  }

  async function loadArticles() {
    const res = await knowledgeApi
      .list<ArticleItem>({
        page: 1,
        size: LATEST_ARTICLE_COUNT,
        status: "PUBLISHED"
      })
      .catch(() => null);
    if (res && isSuccess(res)) articles.value = res.data.results ?? [];
  }

  async function reload() {
    loading.value = true;
    try {
      await Promise.all([loadDashboard(), loadTickets(), loadArticles()]);
    } finally {
      loading.value = false;
    }
  }

  return { dashboard, tickets, articles, loading, stats, reload, loadTickets };
}
