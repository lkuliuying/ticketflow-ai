import { http } from "@/utils/http";
import { postSse, type SseFrame } from "@/utils/sse";
import type { TicketPriority } from "./tickets";

/**
 * 工单 AI 服务（FastAPI，网关前缀 `/ai/`）。成功响应是裸 JSON，不带 `{code, data}` 信封；
 * 建流前的错误统一为 `{code, detail}`，由 http 拦截器提示。
 */
const BASE = "/ai/v1/tickets";

export type TicketAnalysis = {
  ticket_id: string;
  /** 分析基于的工单版本；采纳时原样提交，工单已变更会得到 409 */
  ticket_version: number;
  category: string;
  suggested_priority: TicketPriority;
  summary: string;
  tags: string[];
};

export const analyzeTicket = (ticketId: string) =>
  http.request<TicketAnalysis>("post", `${BASE}/analyze`, {
    data: { ticket_id: ticketId }
  });

export type ReplyStatus =
  "idle" | "streaming" | "done" | "error" | "stopped" | "interrupted";

export type ReplyState = {
  status: ReplyStatus;
  text: string;
  /** 引用的已发布知识文章 ID（meta 帧） */
  references: string[];
  ticketVersion?: number;
  finishReason?: string;
  error?: { code: number; detail: string; retryable: boolean };
};

export const emptyReply = (): ReplyState => ({
  status: "idle",
  text: "",
  references: []
});

function parse(data: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(data);
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

/**
 * 纯函数：按一帧推进回复状态。帧序 `meta` → `delta`* → `done`，建流后失败以 `error` 结束，
 * `ping` 只是心跳。终态之后的帧一律忽略，避免 `done` 后的残帧改写结果。
 */
export function applyReplyFrame(
  state: ReplyState,
  frame: SseFrame
): ReplyState {
  if (state.status !== "streaming") return state;
  const data = parse(frame.data);
  switch (frame.event) {
    case "meta":
      return {
        ...state,
        references: Array.isArray(data?.references)
          ? data.references.map(String)
          : [],
        ticketVersion:
          typeof data?.ticket_version === "number"
            ? data.ticket_version
            : undefined
      };
    case "delta":
      return typeof data?.text === "string"
        ? { ...state, text: state.text + data.text }
        : state;
    case "done":
      return {
        ...state,
        status: "done",
        finishReason: String(data?.finish_reason ?? "stop")
      };
    case "error":
      return {
        ...state,
        status: "error",
        error: {
          code: Number(data?.code ?? 500),
          detail: String(data?.detail ?? ""),
          retryable: Boolean(data?.retryable)
        }
      };
    default:
      return state;
  }
}

/**
 * 流式生成回复建议。`onUpdate` 每帧回调最新状态；正常返回的流若没有 `done` 视为中断，
 * 主动取消标记为 `stopped`。建流前失败抛出 `SseError`（code / detail）。
 */
export async function streamReply(
  ticketId: string,
  onUpdate: (state: ReplyState) => void,
  signal: AbortSignal
): Promise<ReplyState> {
  let state: ReplyState = { ...emptyReply(), status: "streaming" };
  onUpdate(state);
  try {
    await postSse(
      `${BASE}/suggest-reply/stream`,
      { ticket_id: ticketId },
      {
        signal,
        onFrame: frame => {
          const next = applyReplyFrame(state, frame);
          if (next !== state) {
            state = next;
            onUpdate(state);
          }
        }
      }
    );
  } catch (error) {
    if (!signal.aborted) throw error;
  }
  if (state.status === "streaming") {
    state = { ...state, status: signal.aborted ? "stopped" : "interrupted" };
    onUpdate(state);
  }
  return state;
}
