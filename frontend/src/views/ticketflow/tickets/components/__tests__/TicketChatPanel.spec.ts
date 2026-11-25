import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  chatMessages: vi.fn(),
  chatSend: vi.fn(),
  chatUpload: vi.fn(),
  chatRead: vi.fn()
}));

const mediaMocks = vi.hoisted(() => ({
  urls: {} as Record<string, string>,
  ensure: vi.fn()
}));

const messageMock = vi.hoisted(() => vi.fn());

vi.mock("@/utils/message", () => ({ message: messageMock }));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});

vi.mock("@/store/modules/user", () => ({
  useUserStoreHook: () => ({ uid: 10 })
}));

vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: apiMocks
}));

vi.mock("../../utils/useAuthorizedMedia", async () => {
  // urls 需为响应式，才能在“加载成功”后驱动模板切换为 <video>
  const { reactive } = await import("vue");
  mediaMocks.urls = reactive({});
  return { useAuthorizedMedia: () => mediaMocks };
});

import TicketChatPanel from "../TicketChatPanel.vue";
import type { TicketDetail } from "@/api/ticketflow/tickets";

function makeTicket(overrides: Partial<TicketDetail> = {}): TicketDetail {
  return {
    pk: "ticket-1",
    number: "TF-20261125-ABC123",
    title: "VPN 故障",
    description: "无法连接",
    category: "NETWORK",
    priority: "P1",
    status: "IN_PROGRESS",
    submitter_id: 10,
    submitter_name: "emp",
    assignee_id: 20,
    assignee_name: "tech",
    department_id: "dept-1",
    department_name: "网络支持组",
    sla_due_at: "2026-11-26T00:00:00Z",
    sla_state: "ON_TRACK",
    first_response_at: null,
    resolved_at: null,
    ai_summary: "",
    ai_tags: [],
    version: 2,
    created_time: "2026-11-25T00:00:00Z",
    updated_time: "2026-11-25T00:00:00Z",
    viewer: {
      can_handle: true,
      can_assign: false,
      can_reply: true,
      can_comment_internal: true,
      can_archive: false,
      can_return: true,
      read_only: false
    },
    available_transitions: [],
    timeline: { total: 0, results: [] },
    chat_state: { can_send: true, lock_reason: "" },
    ...overrides
  };
}

describe("TicketChatPanel 实时排查会话", () => {
  it("未接单时展示锁定提示并隐藏输入框", async () => {
    apiMocks.chatMessages.mockResolvedValueOnce({
      code: 1000,
      data: {
        results: [],
        has_more: false,
        chat_state: { can_send: false, lock_reason: "WAITING_ACCEPT" }
      }
    });
    apiMocks.chatRead.mockResolvedValue({ code: 1000, data: null });

    const wrapper = mount(TicketChatPanel, {
      props: {
        ticket: makeTicket({
          status: "OPEN",
          chat_state: { can_send: false, lock_reason: "WAITING_ACCEPT" }
        })
      }
    });
    await flushPromises();
    expect(wrapper.find('[data-testid="ticket-chat-locked"]').exists()).toBe(
      true
    );
    expect(wrapper.find('[data-testid="ticket-chat-composer"]').exists()).toBe(
      false
    );
  });

  it("处理中允许填入建议并发送文字消息", async () => {
    apiMocks.chatMessages.mockResolvedValueOnce({
      code: 1000,
      data: {
        results: [],
        has_more: false,
        chat_state: { can_send: true, lock_reason: "" }
      }
    });
    apiMocks.chatRead.mockResolvedValue({ code: 1000, data: null });
    apiMocks.chatSend.mockResolvedValueOnce({
      code: 1000,
      data: {
        id: "m1",
        ticket_id: "ticket-1",
        sender_id: 10,
        sender_name: "emp",
        kind: "TEXT",
        content: "已收到建议，请稍等",
        media_meta: {},
        media_expired: false,
        file_url: null,
        thumb_url: null,
        client_msg_id: "cid-1",
        created_time: "2026-11-25T10:00:00Z"
      }
    });

    const wrapper = mount(TicketChatPanel, {
      props: { ticket: makeTicket() }
    });
    await flushPromises();
    (wrapper.vm as { fill: (text: string) => void }).fill("已收到建议，请稍等");
    await flushPromises();
    await wrapper.get('[data-testid="ticket-chat-send"]').trigger("click");
    await flushPromises();

    expect(apiMocks.chatSend).toHaveBeenCalledWith(
      "ticket-1",
      expect.objectContaining({
        kind: "TEXT",
        content: "已收到建议，请稍等"
      })
    );
    expect(wrapper.findAll('[data-testid="ticket-chat-item"]')).toHaveLength(1);
  });

  const fileUrl = (id: string) =>
    `/api/tickets/ticket-1/chat/messages/${id}/file`;
  const media = (id: string, kind: "IMAGE" | "VIDEO") => ({
    id,
    ticket_id: "ticket-1",
    sender_id: 20,
    sender_name: "tech",
    kind,
    content: "",
    media_meta: { filename: `${id}.bin` },
    media_expired: false,
    file_url: fileUrl(id),
    thumb_url: kind === "IMAGE" ? `${fileUrl(id)}?size=thumb` : null,
    client_msg_id: "",
    created_time: "2026-11-25T10:00:00Z"
  });

  async function mountWithMedia() {
    for (const key of Object.keys(mediaMocks.urls)) delete mediaMocks.urls[key];
    mediaMocks.ensure.mockReset();
    messageMock.mockReset();
    apiMocks.chatMessages.mockResolvedValueOnce({
      code: 1000,
      data: {
        results: [media("img1", "IMAGE"), media("vid1", "VIDEO")],
        has_more: false,
        chat_state: { can_send: true, lock_reason: "" }
      }
    });
    apiMocks.chatRead.mockResolvedValue({ code: 1000, data: null });
    const wrapper = mount(TicketChatPanel, {
      props: { ticket: makeTicket() }
    });
    await flushPromises();
    return wrapper;
  }

  it("视频加载成功后渲染 <video>，不提示错误", async () => {
    const wrapper = await mountWithMedia();
    mediaMocks.ensure.mockImplementation(async (url: string) => {
      mediaMocks.urls[url] = "blob:video";
      return true;
    });
    await wrapper
      .get('[data-testid="ticket-chat-load-video"]')
      .trigger("click");
    await flushPromises();
    expect(wrapper.find("video").attributes("src")).toBe("blob:video");
    expect(messageMock).not.toHaveBeenCalled();
  });

  it("视频下载途中组件卸载时不误报失败", async () => {
    const wrapper = await mountWithMedia();
    let finish!: (ok: boolean) => void;
    mediaMocks.ensure.mockImplementation(
      () => new Promise<boolean>(resolve => (finish = resolve))
    );
    await wrapper
      .get('[data-testid="ticket-chat-load-video"]')
      .trigger("click");
    wrapper.unmount();
    finish(false);
    await flushPromises();
    expect(messageMock).not.toHaveBeenCalled();
  });

  it("视频消息不随会话预取，点击“加载视频”后才拉取，失败时提示", async () => {
    const wrapper = await mountWithMedia();
    mediaMocks.ensure.mockResolvedValue(false);

    const fetched = mediaMocks.ensure.mock.calls.map(call => String(call[0]));
    expect(fetched).toContain(`${fileUrl("img1")}?size=thumb`);
    expect(fetched).toContain(fileUrl("img1"));
    expect(fetched.some(url => url.includes("vid1"))).toBe(false);

    await wrapper
      .get('[data-testid="ticket-chat-load-video"]')
      .trigger("click");
    await flushPromises();
    expect(mediaMocks.ensure).toHaveBeenLastCalledWith(fileUrl("vid1"));
    expect(messageMock).toHaveBeenCalledWith(
      "ticketflow.chat.videoLoadFailed",
      { type: "error" }
    );
  });
});
