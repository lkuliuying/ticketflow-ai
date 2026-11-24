import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import ElementPlus from "element-plus";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  retrieve: vi.fn(),
  openTicketDetail: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});
vi.mock("../utils/useAssistantChat", () => ({
  LOCAL_PREFIX: "local-",
  useAssistantChat: () => ({
    messages: ref([
      {
        pk: "q1",
        role: "user",
        content: "VPN",
        references: [],
        status: "complete",
        user_message_id: null,
        created_time: ""
      }
    ]),
    loading: ref(false),
    pending: ref(null),
    chat: ref({ status: "idle", text: "", references: [] }),
    streaming: ref(false),
    ask: vi.fn(),
    stop: vi.fn(),
    setFeedback: vi.fn()
  })
}));
vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { retrieve: mocks.retrieve }
}));
vi.mock("../../tickets/utils/ticketDetailDrawer", () => ({
  openTicketDetail: mocks.openTicketDetail
}));

import ChatPanel from "../components/ChatPanel.vue";

const session = (ticketId: string | null) => ({
  pk: "s1",
  title: "VPN 排查",
  ticket_id: ticketId,
  created_time: "",
  updated_time: ""
});

function mountPanel(ticketId: string | null) {
  return mount(ChatPanel, {
    props: {
      session: session(ticketId),
      canRead: true,
      canFeedback: true,
      canHandoff: true,
      autoTitle: false
    },
    global: { plugins: [ElementPlus], stubs: { MessageBubble: true } }
  });
}

describe("ChatPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("未转人工时可输入，并提供转人工入口", () => {
    const wrapper = mountPanel(null);
    expect(wrapper.find('[data-testid="assistant-input"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="assistant-handoff"]').exists()).toBe(
      true
    );
    expect(wrapper.find('[data-testid="assistant-handed-off"]').exists()).toBe(
      false
    );
  });

  it("已转人工的会话只读，可打开关联工单", async () => {
    mocks.retrieve.mockResolvedValue({
      code: 1000,
      data: { pk: "t1", number: "TF-1" }
    });
    const wrapper = mountPanel("t1");
    expect(wrapper.find('[data-testid="assistant-input"]').exists()).toBe(
      false
    );
    expect(wrapper.find('[data-testid="assistant-handoff"]').exists()).toBe(
      false
    );
    await wrapper.get('[data-testid="assistant-open-ticket"]').trigger("click");
    await flushPromises();
    expect(mocks.retrieve).toHaveBeenCalledWith("t1");
    expect(mocks.openTicketDetail).toHaveBeenCalledWith(
      { pk: "t1", number: "TF-1" },
      {}
    );
  });
});
