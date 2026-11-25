import { onBeforeUnmount, ref } from "vue";
import type {
  TicketChatMessage,
  TicketChatState
} from "@/api/ticketflow/tickets";
import type { WS } from "@/utils/websocket";
import * as chat from "./chatSocket";

/** 工单实时排查会话 Hook：历史拉取、WS 实时收发、断线补拉、状态同步与已读上报 */
export function useTicketChat(
  ticketId: () => string,
  onStateChange?: (state: TicketChatState) => void
) {
  const messages = ref<TicketChatMessage[]>([]);
  const chatState = ref<TicketChatState>({
    can_send: false,
    lock_reason: "WAITING_ACCEPT"
  });
  const hasMore = ref(false);
  const loading = ref(false);
  const sending = ref(false);
  const uploading = ref(false);
  let socket: WS | null = null;
  let disposed = false;

  const applyState = (next: TicketChatState) => {
    chatState.value = next;
    onStateChange?.(next);
  };

  async function load(beforeId?: string) {
    loading.value = true;
    const data = await chat.fetchChatPage(
      ticketId(),
      beforeId ? { limit: 50, before_id: beforeId } : { limit: 50 }
    );
    loading.value = false;
    if (!data || disposed) return;
    applyState(data.chat_state);
    hasMore.value = data.has_more;
    messages.value = beforeId
      ? chat.prependUniqueMessages(messages.value, data.results)
      : data.results;
    if (!beforeId) chat.markChatRead(ticketId());
  }

  async function syncMissed() {
    const lastId = messages.value[messages.value.length - 1]?.id;
    if (!lastId) return load();
    const data = await chat.fetchChatPage(ticketId(), {
      after_id: lastId,
      limit: 100
    });
    if (!data || disposed) return;
    applyState(data.chat_state);
    if (data.results.length) {
      messages.value = chat.appendUniqueMessages(messages.value, data.results);
      chat.markChatRead(ticketId());
    }
  }

  function connect() {
    socket?.close();
    socket = chat.openChatSocket(ticketId(), {
      onMessage: item => {
        messages.value = chat.upsertChatMessage(messages.value, item);
        chat.markChatRead(ticketId());
      },
      onState: applyState,
      onReconnect: () => void syncMissed()
    });
  }

  async function dispatchSend(
    busy: typeof sending,
    action: () => Promise<TicketChatMessage | null>
  ): Promise<boolean> {
    if (busy.value || !chatState.value.can_send) return false;
    busy.value = true;
    const saved = await action();
    busy.value = false;
    if (!saved) return false;
    messages.value = chat.upsertChatMessage(messages.value, saved);
    return true;
  }

  const sendText = (content: string) =>
    content.trim()
      ? dispatchSend(sending, () =>
          chat.postChatText(ticketId(), content.trim())
        )
      : Promise.resolve(false);

  const sendMedia = (file: File) =>
    dispatchSend(uploading, () => chat.postChatMedia(ticketId(), file));

  onBeforeUnmount(() => {
    disposed = true;
    socket?.close();
    socket = null;
  });

  return {
    messages,
    chatState,
    hasMore,
    loading,
    sending,
    uploading,
    load,
    connect,
    sendText,
    sendMedia
  };
}
