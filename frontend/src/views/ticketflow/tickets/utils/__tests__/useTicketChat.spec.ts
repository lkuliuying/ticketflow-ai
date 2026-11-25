import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const socketState = vi.hoisted(() => ({
  handlers: null as { onRevoked?: (code: number) => void } | null,
  close: vi.fn()
}));
const chatMocks = vi.hoisted(() => ({
  recheckChatState: vi.fn(),
  REVOKED_CHAT_STATE: { can_send: false, lock_reason: "READ_ONLY" },
  fetchMissedMessages: vi.fn(),
  markChatRead: vi.fn(),
  postChatText: vi.fn(),
  postChatMedia: vi.fn(),
  upsertChatMessage: vi.fn((rows: unknown[], item: unknown) => [...rows, item]),
  prependUniqueMessages: vi.fn(),
  appendUniqueMessages: vi.fn(),
  openChatSocket: vi.fn(
    (_id: string, handlers: { onRevoked?: (code: number) => void }) => {
      socketState.handlers = handlers;
      return { close: socketState.close };
    }
  )
}));

vi.mock("../chatSocket", () => chatMocks);

import { useTicketChat } from "../useTicketChat";

function mountChat() {
  let api!: ReturnType<typeof useTicketChat>;
  mount(
    defineComponent({
      setup() {
        api = useTicketChat(() => "ticket-1");
        api.connect();
        return () => h("div");
      }
    })
  );
  return api;
}

describe("useTicketChat 鉴权类断开复查", () => {
  beforeEach(() => {
    socketState.close.mockReset();
    chatMocks.recheckChatState.mockReset();
  });

  it("令牌过期等可恢复情况：HTTP 复查通过时保持连接、同步状态", async () => {
    const api = mountChat();
    chatMocks.recheckChatState.mockResolvedValueOnce({
      can_send: true,
      lock_reason: ""
    });
    socketState.handlers?.onRevoked?.(4403);
    await flushPromises();
    expect(socketState.close).not.toHaveBeenCalled();
    expect(api.chatState.value).toEqual({ can_send: true, lock_reason: "" });
  });

  it("确已失去权限：HTTP 复查失败时停止重连并锁为只读", async () => {
    const api = mountChat();
    chatMocks.recheckChatState.mockResolvedValueOnce(null);
    socketState.handlers?.onRevoked?.(4403);
    await flushPromises();
    expect(socketState.close).toHaveBeenCalledTimes(1);
    expect(api.chatState.value).toEqual({
      can_send: false,
      lock_reason: "READ_ONLY"
    });
  });
});
