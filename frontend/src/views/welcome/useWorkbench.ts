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
  unassigned: number;
  current: number;
  history: number;
  open: number;
  reopened: number;
  inProgress: number;
  verifying: number;
  dueSoon: number;
  overdue: number;
};

/**
 * 首页计数：每张卡与工单列表的一个看板筛选一一对应（点击后列表条数与计数一致）。
 * 数据范围由后端按当前身份限定，这里不做角色判断。
 */
export function summarize(data: TicketDashboard | null): WorkbenchStats {
  const status = data?.status ?? {};
  const sla = data?.sla;
  const assignment = data?.assignment ?? {};
  return {
    unassigned: assignment.unassigned ?? 0,
    current: assignment.current ?? 0,
    history: assignment.history ?? 0,
    open: status.OPEN ?? 0,
    reopened: status.REOPENED ?? 0,
    inProgress: status.IN_PROGRESS ?? 0,
    verifying: status.PENDING_VERIFY ?? 0,
    dueSoon: sla?.DUE_SOON ?? 0,
    overdue: sla?.OVERDUE ?? 0
  };
}

/**
 * 工作台数据：看板计数、最近工单与最新已发布文章，三路并行加载、互不阻塞。
 * 没有对应列表权限的部分不请求，避免触发全局 403 提示。
 */
export function useWorkbench(
  can: { tickets: () => boolean; articles: () => boolean } = {
    tickets: () => true,
    articles: () => true
  }
) {
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
    if (res && isSuccess(res)) tickets.value = res.data?.results ?? [];
  }

  async function loadArticles() {
    const res = await knowledgeApi
      .list<ArticleItem>({
        page: 1,
        size: LATEST_ARTICLE_COUNT,
        status: "PUBLISHED",
        ordering: "-updated_time"
      })
      .catch(() => null);
    if (res && isSuccess(res)) articles.value = res.data?.results ?? [];
  }

  async function reload() {
    loading.value = true;
    try {
      const jobs: Promise<void>[] = [];
      if (can.tickets()) jobs.push(loadDashboard(), loadTickets());
      if (can.articles()) jobs.push(loadArticles());
      await Promise.all(jobs);
    } finally {
      loading.value = false;
    }
  }

  return { dashboard, tickets, articles, loading, stats, reload };
}
