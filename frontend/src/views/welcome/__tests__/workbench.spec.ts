import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  ticketList: vi.fn(),
  articleList: vi.fn()
}));

vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { dashboard: mocks.dashboard, list: mocks.ticketList }
}));
vi.mock("@/api/ticketflow/knowledge", () => ({
  knowledgeApi: { list: mocks.articleList }
}));
vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) };
});

import { greetingKey } from "../greeting";
import { summarize, useWorkbench } from "../useWorkbench";
import WorkbenchStats from "../components/WorkbenchStats.vue";

const ok = <T>(data: T) => ({ code: 1000, detail: "", data });

describe("greetingKey", () => {
  it.each([
    [4, "evening"],
    [5, "morning"],
    [11, "morning"],
    [12, "afternoon"],
    [17, "afternoon"],
    [18, "evening"],
    [23, "evening"]
  ])("%i 点使用 %s 问候", (hour, part) => {
    expect(greetingKey(hour)).toBe(`workbench.greeting.${part}`);
  });
});

describe("summarize", () => {
  it("待处理合并新建与重开，SLA 风险合并即将超时与已超时", () => {
    expect(
      summarize({
        status: { OPEN: 3, REOPENED: 2, IN_PROGRESS: 4, PENDING_VERIFY: 1 },
        priority: {},
        sla: { ON_TRACK: 5, DUE_SOON: 2, OVERDUE: 1, MET: 9 }
      })
    ).toEqual({ pending: 5, inProgress: 4, verifying: 1, slaRisk: 3 });
  });

  it("没有数据时全部为 0", () => {
    expect(summarize(null)).toEqual({
      pending: 0,
      inProgress: 0,
      verifying: 0,
      slaRisk: 0
    });
  });
});

describe("useWorkbench", () => {
  beforeEach(() => vi.clearAllMocks());

  it("并行加载计数、最近工单与已发布文章", async () => {
    mocks.dashboard.mockResolvedValue(
      ok({ status: { OPEN: 1 }, priority: {}, sla: {} })
    );
    mocks.ticketList.mockResolvedValue(ok({ results: [{ pk: "t1" }] }));
    mocks.articleList.mockResolvedValue(ok({ results: [{ pk: "a1" }] }));

    const workbench = useWorkbench();
    await workbench.reload();

    expect(mocks.ticketList).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, size: 6, ordering: "-updated_time" })
    );
    expect(mocks.articleList).toHaveBeenCalledWith(
      expect.objectContaining({ status: "PUBLISHED", size: 5 })
    );
    expect(workbench.stats.value.pending).toBe(1);
    expect(workbench.tickets.value).toEqual([{ pk: "t1" }]);
    expect(workbench.articles.value).toEqual([{ pk: "a1" }]);
    expect(workbench.loading.value).toBe(false);
  });

  it("单路失败不影响其他数据，加载状态正常结束", async () => {
    mocks.dashboard.mockRejectedValue(new Error("boom"));
    mocks.ticketList.mockResolvedValue({ code: 4000, detail: "x", data: null });
    mocks.articleList.mockResolvedValue(ok({ results: [{ pk: "a1" }] }));

    const workbench = useWorkbench();
    await workbench.reload();

    expect(workbench.dashboard.value).toBeNull();
    expect(workbench.tickets.value).toEqual([]);
    expect(workbench.articles.value).toEqual([{ pk: "a1" }]);
    expect(workbench.loading.value).toBe(false);
  });
});

describe("WorkbenchStats", () => {
  it("展示计数，点击卡片带上对应筛选", async () => {
    const wrapper = mount(WorkbenchStats, {
      props: {
        stats: { pending: 5, inProgress: 4, verifying: 1, slaRisk: 3 }
      },
      global: { stubs: { "el-icon": true } }
    });
    await flushPromises();
    expect(
      wrapper.get('[data-testid="workbench-stat-pending"]').text()
    ).toContain("5");
    await wrapper
      .get('[data-testid="workbench-stat-verifying"]')
      .trigger("click");
    await wrapper
      .get('[data-testid="workbench-stat-slaRisk"]')
      .trigger("click");
    expect(wrapper.emitted("open")).toEqual([
      [{ status: "PENDING_VERIFY" }],
      [{ sla: "OVERDUE" }]
    ]);
  });
});
