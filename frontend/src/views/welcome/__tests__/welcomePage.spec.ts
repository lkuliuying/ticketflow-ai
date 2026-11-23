import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

const mocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  ticketList: vi.fn(),
  articleList: vi.fn(),
  push: vi.fn()
}));

vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: {
    dashboard: mocks.dashboard,
    list: mocks.ticketList
  }
}));
vi.mock("@/api/ticketflow/knowledge", () => ({
  knowledgeApi: { list: mocks.articleList }
}));
vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, locale: { value: "zh" } })
  };
});
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/store/modules/user", () => ({
  useUserStoreHook: () => ({ nickname: "演示", username: "demo" })
}));
vi.mock("@/router/utils", () => ({
  usePageAuth: () => ({ list: true, create: true })
}));
vi.mock("@/views/ticketflow/tickets/utils/ticketDetailDrawer", () => ({
  openTicketDetail: vi.fn()
}));
vi.mock("@/views/ticketflow/knowledge/utils/articleDetailDrawer", () => ({
  openArticleDetail: vi.fn()
}));

import Welcome from "../index.vue";

const ok = <T>(data: T) => ({ code: 1000, detail: "", data });
const Passthrough = defineComponent({
  setup(_, { slots, attrs }) {
    return () => h("div", attrs, slots.default?.());
  }
});
const Button = defineComponent({
  emits: ["click"],
  setup(_, { slots, attrs, emit }) {
    return () =>
      h(
        "button",
        { ...attrs, onClick: () => emit("click") },
        slots.default?.()
      );
  }
});

function mountWith(assignment: Record<string, number> | undefined) {
  mocks.dashboard.mockResolvedValue(
    ok({ status: {}, priority: {}, sla: {}, assignment })
  );
  mocks.ticketList.mockResolvedValue(ok({ results: [] }));
  mocks.articleList.mockResolvedValue(ok({ results: [] }));
  return mount(Welcome, {
    global: {
      stubs: {
        "el-card": Passthrough,
        "el-button": Button,
        RecentTickets: true,
        LatestArticles: true,
        WorkbenchStats: true,
        ReSkeleton: { template: "<i class='skeleton' />" }
      }
    }
  });
}

const has = (wrapper: ReturnType<typeof mountWith>, id: string) =>
  wrapper.find(`[data-testid="workbench-${id}"]`).exists();

describe("首页工作台按视角切换入口", () => {
  beforeEach(() => vi.clearAllMocks());

  it("看板返回前不渲染随视角变化的入口", () => {
    const wrapper = mountWith({ unassigned: 1 });
    expect(has(wrapper, "create")).toBe(false);
    expect(has(wrapper, "unassigned")).toBe(false);
  });

  it("员工视角显示新建工单", async () => {
    const wrapper = mountWith({});
    await flushPromises();
    expect(has(wrapper, "create")).toBe(true);
    expect(has(wrapper, "unassigned")).toBe(false);
    expect(has(wrapper, "current")).toBe(false);
  });

  it("管理员视角显示待分配入口并带筛选跳转", async () => {
    const wrapper = mountWith({ unassigned: 2 });
    await flushPromises();
    expect(has(wrapper, "create")).toBe(false);
    await wrapper.get('[data-testid="workbench-unassigned"]').trigger("click");
    expect(mocks.push).toHaveBeenCalledWith({
      path: "/ticketflow/tickets/index",
      query: { assignment: "unassigned" }
    });
  });

  it("技术员视角显示我的待办", async () => {
    const wrapper = mountWith({ current: 1, history: 0 });
    await flushPromises();
    expect(has(wrapper, "current")).toBe(true);
    expect(has(wrapper, "create")).toBe(false);
  });

  it("看板失败时按员工视角兜底", async () => {
    mocks.dashboard.mockRejectedValue(new Error("boom"));
    mocks.ticketList.mockResolvedValue(ok({ results: [] }));
    mocks.articleList.mockResolvedValue(ok({ results: [] }));
    const wrapper = mount(Welcome, {
      global: {
        stubs: {
          "el-card": Passthrough,
          "el-button": Button,
          RecentTickets: true,
          LatestArticles: true,
          WorkbenchStats: true
        }
      }
    });
    await flushPromises();
    expect(has(wrapper, "create")).toBe(true);
  });
});
