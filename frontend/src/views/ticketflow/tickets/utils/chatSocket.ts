import { isSuccess } from "@/api/types";
import {
  ticketApi,
  type TicketChatMessage,
  type TicketChatState
} from "@/api/ticketflow/tickets";
import { WS } from "@/utils/websocket";

const { VITE_WSS_DOMAIN } = import.meta.env;

export function newClientId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

export function upsertChatMessage(
  rows: TicketChatMessage[],
  item: TicketChatMessage
): TicketChatMessage[] {
  const idx = rows.findIndex(
    row =>
      row.id === item.id ||
      (Boolean(item.client_msg_id) && row.client_msg_id === item.client_msg_id)
  );
  if (idx < 0) return [...rows, item];
  const next = [...rows];
  next[idx] = item;
  return next;
}

export function prependUniqueMessages(
  existing: TicketChatMessage[],
  older: TicketChatMessage[]
): TicketChatMessage[] {
  const seen = new Set(existing.map(item => item.id));
  return [...older.filter(item => !seen.has(item.id)), ...existing];
}

export function appendUniqueMessages(
  existing: TicketChatMessage[],
  newer: TicketChatMessage[]
): TicketChatMessage[] {
  let result = existing;
  for (const item of newer) {
    result = upsertChatMessage(result, item);
  }
  return result;
}

export function parseChatFrame(
  raw: unknown
): { event?: string; data?: unknown } | null {
  if (raw && typeof raw === "object") {
    return raw as { event?: string; data?: unknown };
  }
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object"
        ? (parsed as { event?: string; data?: unknown })
        : null;
    } catch {
      return null;
    }
  }
  return null;
}

export function markChatRead(ticketId: string) {
  void ticketApi.chatRead(ticketId).catch(() => null);
}

export async function fetchChatPage(
  ticketId: string,
  params: { limit?: number; before_id?: string; after_id?: string }
) {
  const res = await ticketApi.chatMessages(ticketId, params).catch(() => null);
  return res && isSuccess(res) ? res.data : null;
}

/** 服务端鉴权类关闭码：4401 未登录、4403 失去权限或令牌失效、4404 工单不可见 */
const CHAT_REVOKED_CODES = new Set([4401, 4403, 4404]);

const SYNC_PAGE_SIZE = 100;
const SYNC_MAX_PAGES = 20;

/**
 * 断线重连后按 after_id 补拉，直到后端返回 has_more=false；
 * 页数设上限，防止异常响应导致死循环。全部失败返回 null，部分成功返回已拉到的消息。
 */
export async function fetchMissedMessages(
  ticketId: string,
  afterId: string
): Promise<{
  results: TicketChatMessage[];
  chat_state: TicketChatState;
} | null> {
  const results: TicketChatMessage[] = [];
  let chatState: TicketChatState | null = null;
  let cursor = afterId;
  for (let page = 0; page < SYNC_MAX_PAGES; page++) {
    const data = await fetchChatPage(ticketId, {
      after_id: cursor,
      limit: SYNC_PAGE_SIZE
    });
    if (!data) break;
    chatState = data.chat_state;
    results.push(...data.results);
    const last = data.results[data.results.length - 1];
    // 游标未前进（异常响应）时停止，避免空转到页数上限
    if (!data.has_more || !last || last.id === cursor) break;
    cursor = last.id;
  }
  return chatState ? { results, chat_state: chatState } : null;
}

/** 复查失败（已失去权限）时采用的会话状态 */
export const REVOKED_CHAT_STATE: TicketChatState = {
  can_send: false,
  lock_reason: "READ_ONLY"
};

/** 经 HTTP 复查会话权限（http 层会自动刷新过期 token）；失败返回 null */
export async function recheckChatState(
  ticketId: string
): Promise<TicketChatState | null> {
  const data = await fetchChatPage(ticketId, { limit: 1 });
  return data?.chat_state ?? null;
}

export async function postChatText(
  ticketId: string,
  content: string
): Promise<TicketChatMessage | null> {
  const res = await ticketApi
    .chatSend(ticketId, {
      kind: "TEXT",
      content: content.trim(),
      client_msg_id: newClientId()
    })
    .catch(() => null);
  return res && isSuccess(res) ? res.data : null;
}

export async function postChatMedia(
  ticketId: string,
  file: File
): Promise<TicketChatMessage | null> {
  const up = await ticketApi.chatUpload(ticketId, file).catch(() => null);
  if (!up || !isSuccess(up)) return null;
  const res = await ticketApi
    .chatSend(ticketId, {
      kind: up.data.kind,
      file_pk: up.data.file_pk,
      client_msg_id: newClientId()
    })
    .catch(() => null);
  return res && isSuccess(res) ? res.data : null;
}

export function openChatSocket(
  ticketId: string,
  handlers: {
    onMessage: (msg: TicketChatMessage) => void;
    onState: (state: TicketChatState) => void;
    onReconnect?: () => void;
    /**
     * 服务端以鉴权类关闭码断开时回调。access token 过期也会收到 4403，
     * 因此这里不直接放弃重连，由调用方经 HTTP（会自动刷新 token）复查权限后决定是否关闭。
     */
    onRevoked?: (code: number) => void;
  }
): WS | null {
  if (typeof WebSocket === "undefined") return null;
  const base =
    VITE_WSS_DOMAIN ||
    (typeof window !== "undefined"
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
      : "");
  if (!base) return null;
  let connectedOnce = false;
  const instance = new WS(`${base}/ws/tickets/${ticketId}/chat/`, {
    openCallback: () => {
      instance.onMessage(raw => {
        const frame = parseChatFrame(raw);
        if (!frame) return;
        if (frame.event === "chat.message" && frame.data) {
          handlers.onMessage(frame.data as TicketChatMessage);
        } else if (frame.event === "chat.state" && frame.data) {
          handlers.onState(frame.data as TicketChatState);
        }
      });
      if (connectedOnce) handlers.onReconnect?.();
      connectedOnce = true;
    },
    closeCallback: (_socket, event) => {
      const code = event?.code ?? 0;
      if (CHAT_REVOKED_CODES.has(code)) handlers.onRevoked?.(code);
    }
  });
  return instance;
}
