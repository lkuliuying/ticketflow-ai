import { computed, onBeforeUnmount, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import {
  analyzeTicket,
  emptyReply,
  streamReply,
  type ReplyState,
  type TicketAnalysis
} from "@/api/ticketflow/ai";
import { ticketApi, type TicketDetail } from "@/api/ticketflow/tickets";
import { getToken } from "@/utils/auth";
import type { TicketRun } from "./useTicketDetail";

/** 流内错误里可以直接重试的状态码：限流、上游繁忙、超时 */
const RETRYABLE = new Set([429, 503, 504]);

/**
 * 工单分析与一键采纳。分析结果带着它所依据的工单版本：详情刷新到更高版本后结果视为过期，
 * 不再允许采纳；采纳本身经详情的统一执行器提交，409 时由执行器重新加载详情。
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
    return Boolean(
      analysis.value &&
      current &&
      current.version !== analysis.value.ticket_version
    );
  });

  async function analyze() {
    const current = ticket();
    if (!current || analyzing.value) return;
    analyzing.value = true;
    try {
      analysis.value = await analyzeTicket(current.pk);
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

/**
 * 流式回复建议：同一时刻只有一条流，重新生成或组件卸载（关闭抽屉、切换工单）都会取消在途的流。
 * fetch 不经过 axios 的刷新链路，access 过期时先用一次普通请求触发刷新。
 */
export function useReplyStream(ticketId: () => string | undefined) {
  const reply = ref<ReplyState>(emptyReply());
  let controller: AbortController | null = null;

  function stop() {
    controller?.abort();
  }

  async function generate() {
    const id = ticketId();
    if (!id) return;
    stop();
    const own = new AbortController();
    controller = own;
    if (!getToken()) await ticketApi.retrieve(id).catch(() => null);
    try {
      await streamReply(
        id,
        state => {
          if (controller === own) reply.value = state;
        },
        own.signal
      );
    } catch (error) {
      if (controller !== own) return;
      const code = Number((error as { code?: number })?.code ?? 0);
      reply.value = {
        ...reply.value,
        status: "error",
        error: {
          code,
          detail: (error as Error)?.message ?? "",
          retryable: RETRYABLE.has(code)
        }
      };
    } finally {
      if (controller === own) controller = null;
    }
  }

  onBeforeUnmount(stop);

  return { reply, generate, stop };
}
