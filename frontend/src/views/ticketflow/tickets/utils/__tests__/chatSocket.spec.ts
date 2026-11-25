import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TicketChatMessage } from "@/api/ticketflow/tickets";

type CloseCb = (socket: unknown, event?: { code: number }) => void;

const wsState = vi.hoisted(() => ({
  openCallback: null as ((socket: unknown) => void) | null,
  closeCallback: null as CloseCb | null,
  messageCallback: null as ((data: unknown) => void) | null,
  close: vi.fn(),
  lastUrl: ""
}));

vi.mock("@/utils/websocket", () => ({
  WS: class MockWS {
    constructor(
      url: string,
      options?: {
        openCallback?: (socket: unknown) => void;
        closeCallback?: CloseCb;
      }
    ) {
      wsState.lastUrl = url;
      wsState.openCallback = options?.openCallback ?? null;
      wsState.closeCallback = options?.closeCallback ?? null;
    }
    onMessage(cb: (data: unknown) => void) {
      wsState.messageCallback = cb;
    }
    close = wsState.close;
  }
}));

import { openChatSocket, parseChatFrame } from "../chatSocket";

describe("chatSocket", () => {
  beforeEach(() => {
    wsState.openCallback = null;
    wsState.closeCallback = null;
    wsState.close.mockReset();
    wsState.messageCallback = null;
    wsState.lastUrl = "";
  });

  it("同时兼容已解析对象帧与 JSON 字符串帧", () => {
    expect(
      parseChatFrame({ event: "chat.message", data: { id: "m1" } })
    ).toEqual({
      event: "chat.message",
      data: { id: "m1" }
    });
    expect(
      parseChatFrame(
        JSON.stringify({ event: "chat.state", data: { can_send: true } })
      )
    ).toEqual({
      event: "chat.state",
      data: { can_send: true }
    });
    expect(parseChatFrame("not-json")).toBeNull();
  });

  it("收到 WS.onMessage 传入的已解析对象时即时触发回调，并在重连后触发补拉", () => {
    const onMessage = vi.fn();
    const onState = vi.fn();
    const onReconnect = vi.fn();

    openChatSocket("ticket-42", { onMessage, onState, onReconnect });
    expect(wsState.lastUrl).toContain("/ws/tickets/ticket-42/chat/");

    wsState.openCallback?.({});
    expect(onReconnect).not.toHaveBeenCalled();

    const msg = {
      id: "m1",
      ticket_id: "ticket-42",
      sender_id: 10,
      sender_name: "emp",
      kind: "TEXT",
      content: "客户发来新消息",
      media_meta: {},
      media_expired: false,
      file_url: null,
      thumb_url: null,
      client_msg_id: "c1",
      created_time: "2026-11-25T12:00:00Z"
    } satisfies TicketChatMessage;

    // 模拟底座 WS.onMessage 已 JSON.parse 后的对象入参
    wsState.messageCallback?.({ event: "chat.message", data: msg });
    expect(onMessage).toHaveBeenCalledWith(msg);

    wsState.messageCallback?.({
      event: "chat.state",
      data: { can_send: false, lock_reason: "CLOSED" }
    });
    expect(onState).toHaveBeenCalledWith({
      can_send: false,
      lock_reason: "CLOSED"
    });

    // 模拟断线重连后再次 openCallback
    wsState.openCallback?.({});
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("鉴权类关闭码停止重连并回调，其余关闭码交给底座重连", () => {
    const onRevoked = vi.fn();
    openChatSocket("ticket-42", {
      onMessage: vi.fn(),
      onState: vi.fn(),
      onRevoked
    });

    wsState.closeCallback?.({}, { code: 1011 });
    wsState.closeCallback?.({}, { code: 1006 });
    expect(wsState.close).not.toHaveBeenCalled();
    expect(onRevoked).not.toHaveBeenCalled();

    wsState.closeCallback?.({}, { code: 4403 });
    expect(wsState.close).toHaveBeenCalledTimes(1);
    expect(onRevoked).toHaveBeenCalledWith(4403);
  });
});
