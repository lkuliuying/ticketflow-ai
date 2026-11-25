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

export async function postChatText(
  ticketId: string,
  content: string
): Promise<TicketChatMessage | null> {
  const res = await ticketApi
    .chatSend(ticketId, {
      kind: "TEXT",
      content,
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
    }
  });
  return instance;
}
