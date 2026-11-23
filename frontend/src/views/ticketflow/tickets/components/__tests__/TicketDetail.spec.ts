import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";

const state = vi.hoisted(() => ({ detail: null as unknown }));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});

vi.mock("../../utils/useTicketDetail", () => ({
  useTicketDetail: () => ({
    detail: ref(state.detail),
    loading: ref(false),
    busy: ref(false),
    notFound: ref(false),
    load: vi.fn(),
    run: vi.fn()
  })
}));

const { stub } = vi.hoisted(() => ({
  stub: (name: string, props: string[] = []) => ({
    name,
    props,
    template: `<div class="${name}" />`
  })
}));
vi.mock("../TicketActions.vue", () => ({ default: stub("TicketActions") }));
vi.mock("../TicketReply.vue", () => ({ default: stub("TicketReply") }));
vi.mock("../TicketTimeline.vue", () => ({ default: stub("TicketTimeline") }));
vi.mock("../TicketAiPanel.vue", () => ({
  default: stub("TicketAiPanel", ["canFill"])
}));

import TicketDetail from "../TicketDetail.vue";

/** 回复区与 AI 面板“填入回复框”只看后端 viewer.can_reply，不再按提交人推断 */
function mountWith(
  viewer: Record<string, boolean>,
  overrides: Record<string, unknown> = {},
  submitterId = 7
) {
  state.detail = {
    pk: "t1",
    title: "VPN",
    status: "IN_PROGRESS",
    priority: "P2",
    sla_state: "ON_TRACK",
    version: 2,
    submitter_id: submitterId,
    timeline: { total: 0, results: [] },
    available_transitions: [],
    viewer: {
      can_handle: false,
      can_assign: false,
      can_reply: false,
      can_comment_internal: false,
      can_archive: false,
      can_return: false,
      read_only: false,
      ...viewer
    },
    ...overrides
  };
  return mount(TicketDetail, {
    props: { pk: "t1" },
    global: { stubs: { "el-descriptions": true, "el-result": true } }
  });
}

describe("TicketDetail 回复能力", () => {
  it("can_reply 为真时显示回复区", () => {
    const wrapper = mountWith({ can_reply: true });
    expect(wrapper.find(".TicketReply").exists()).toBe(true);
  });

  it("can_reply 为假时不显示回复区，即使当前用户是提交人", () => {
    const wrapper = mountWith({ can_reply: false });
    expect(wrapper.find(".TicketReply").exists()).toBe(false);
  });

  it("处理人有 AI 面板，能否填入回复框跟随 can_reply", () => {
    for (const canReply of [true, false]) {
      const wrapper = mountWith({ can_handle: true, can_reply: canReply });
      const panel = wrapper.findComponent({ name: "TicketAiPanel" });
      expect(panel.exists()).toBe(true);
      expect(panel.props("canFill")).toBe(canReply);
    }
  });
});

describe("TicketDetail 只读历史工单", () => {
  it("read_only 时显示只读提示，隐藏操作区、回复区与 AI 面板", () => {
    const wrapper = mountWith({ read_only: true });
    expect(wrapper.find('[data-testid="ticket-read-only"]').exists()).toBe(
      true
    );
    expect(wrapper.find(".TicketActions").exists()).toBe(false);
    expect(wrapper.find(".TicketReply").exists()).toBe(false);
    expect(wrapper.findComponent({ name: "TicketAiPanel" }).exists()).toBe(
      false
    );
  });

  it("只读但仍是提交人时，按能力位显示验收操作与回复区", () => {
    const wrapper = mountWith(
      { read_only: true, can_reply: true },
      { available_transitions: ["CLOSED", "IN_PROGRESS"] }
    );
    expect(wrapper.find('[data-testid="ticket-read-only"]').exists()).toBe(
      true
    );
    expect(wrapper.find(".TicketActions").exists()).toBe(true);
    expect(wrapper.find(".TicketReply").exists()).toBe(true);
  });

  it("只读的已关闭工单可转存时显示转存入口", () => {
    const wrapper = mountWith({ read_only: true, can_archive: true });
    expect(wrapper.find(".TicketActions").exists()).toBe(true);
  });

  it("非只读时不显示只读提示，操作区照常出现", () => {
    const wrapper = mountWith({});
    expect(wrapper.find('[data-testid="ticket-read-only"]').exists()).toBe(
      false
    );
    expect(wrapper.find(".TicketActions").exists()).toBe(true);
  });
});
