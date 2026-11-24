import { http } from "@/utils/http";
import { postSse, type SseFrame } from "@/utils/sse";
import type { AssistantReference } from "./assistant";

/**
 * AI 助手的 FastAPI 部分（网关前缀 `/ai/`）：流式问答与转人工草稿。
 * 成功响应是裸 JSON；建流前的错误为 `{code, detail}`，由 postSse 抛出 SseError。
 */
const BASE = "/ai/v1/assistant";

export type ChatStatus =
  "idle" | "streaming" | "done" | "error" | "stopped" | "interrupted";

export type ChatState = {
  status: ChatStatus;
  text: string;
  references: AssistantReference[];
  userMessageId?: string;
  assistantMessageId?: string;
  finishReason?: string;
  error?: { code: number; detail: string; retryable: boolean };
};

export const emptyChat = (): ChatState => ({
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

function toReferences(value: unknown): AssistantReference[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    if (!item || typeof item !== "object") return [];
    const { article_id, title } = item as Record<string, unknown>;
    const id = typeof article_id === "string" ? article_id.trim() : "";
    if (!id) return [];
    return [
      { article_id: id, title: typeof title === "string" ? title.trim() : "" }
    ];
  });
}

const optionalString = (value: unknown) =>
  typeof value === "string" && value ? value : undefined;

/**
 * 纯函数：按一帧推进问答状态。帧序 `meta` → `delta`* → `done`，建流后失败以 `error` 结束，
 * `ping` 只是心跳；终态之后的帧一律忽略。
 */
export function applyChatFrame(state: ChatState, frame: SseFrame): ChatState {
  if (state.status !== "streaming") return state;
  const data = parse(frame.data);
  switch (frame.event) {
    case "meta":
      return {
        ...state,
        references: toReferences(data?.references),
        userMessageId: optionalString(data?.user_message_id)
      };
    case "delta":
      return typeof data?.text === "string"
        ? { ...state, text: state.text + data.text }
        : state;
    case "done":
      return {
        ...state,
        status: "done",
        finishReason: String(data?.finish_reason ?? "stop"),
        assistantMessageId: optionalString(data?.assistant_message_id)
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
 * 在会话里提问并流式接收回答。`onUpdate` 每帧回调最新状态；正常结束却没有 `done`
 * 视为中断，主动取消标记为 `stopped`。建流前失败抛出 SseError（code / detail）。
 */
export async function streamChat(
  sessionId: string,
  message: string,
  onUpdate: (state: ChatState) => void,
  signal: AbortSignal
): Promise<ChatState> {
  let state: ChatState = { ...emptyChat(), status: "streaming" };
  onUpdate(state);
  try {
    await postSse(
      `${BASE}/chat/stream`,
      { session_id: sessionId, message },
      {
        signal,
        onFrame: frame => {
          if (signal.aborted) return;
          const next = applyChatFrame(state, frame);
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

export type HandoffDraft = {
  title: string;
  description: string;
  category: string;
};

/** 把会话整理成工单草稿（标题、描述、建议分类），供员工确认后提交 */
export const handoffDraft = (sessionId: string) =>
  http.request<HandoffDraft>("post", `${BASE}/handoff-draft`, {
    data: { session_id: sessionId }
  });
