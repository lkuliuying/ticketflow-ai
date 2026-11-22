import { computed, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";
import { analyzeTicket, type TicketAnalysis } from "@/api/ticketflow/ai";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";
import type { TicketRun } from "./useTicketDetail";

/**
 * 工单分析与一键采纳。分析结果带着它所依据的工单与版本：换了工单或详情刷新到更高版本后，
 * 结果视为过期，不再允许采纳；采纳经详情的统一执行器提交，409 时由执行器重新加载详情。
 */
export function useTicketAnalysis(
  ticket: () => TicketDetail | null,
  run: TicketRun
) {
  const { t } = useI18n();
  const analysis = shallowRef<TicketAnalysis | null>(null);
  const analyzing = ref(false);
  const stale = computed(() => {
    const current = ticket();
    const result = analysis.value;
    return Boolean(
      result &&
      current &&
      (result.ticket_id !== current.pk ||
        result.ticket_version !== current.version)
    );
  });

  // 同一面板换到另一张工单：旧分析作废
  watch(
    () => ticket()?.pk,
    () => (analysis.value = null)
  );

  async function analyze() {
    const current = ticket();
    if (!current || analyzing.value) return;
    analyzing.value = true;
    try {
      const result = await analyzeTicket(current.pk);
      if (ticket()?.pk === current.pk) analysis.value = result;
    } catch {
      // 失败文案（403 / 404 / 429 / 503 / 504）由 http 拦截器按服务端 detail 展示
    } finally {
      analyzing.value = false;
    }
  }

  function adopt() {
    const current = ticket();
    const result = analysis.value;
    if (!current || !result || stale.value) return Promise.resolve(false);
    return run(
      () =>
        ticketApi.aiMetadata(current.pk, {
          version: result.ticket_version,
          summary: result.summary,
          tags: result.tags,
          category: result.category,
          priority: result.suggested_priority
        }),
      t("ticketflow.ai.adopted")
    );
  }

  return { analysis, analyzing, stale, analyze, adopt };
}

export { useReplyStream } from "./useReplyStream";
