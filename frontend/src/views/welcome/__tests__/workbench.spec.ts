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
import { cardsFor, workbenchRole } from "../cards";

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
  it("每张卡取对应状态或 SLA 的单项计数", () => {
    expect(
      summarize({
        status: { OPEN: 3, REOPENED: 2, IN_PROGRESS: 4, PENDING_VERIFY: 1 },
        priority: {},
        sla: { ON_TRACK: 5, DUE_SOON: 2, OVERDUE: 1, MET: 9 }
      })
    ).toEqual({
      unassigned: 0,
      current: 0,
      history: 0,
      open: 3,
      reopened: 2,
      inProgress: 4,
      verifying: 1,
      dueSoon: 2,
      overdue: 1
    });
  });

  it("没有数据时全部为 0", () => {
    expect(Object.values(summarize(null)).every(value => value === 0)).toBe(
      true
    );
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
      expect.objectContaining({
        status: "PUBLISHED",
        size: 5,
        ordering: "-updated_time"
      })
    );
    expect(workbench.stats.value.open).toBe(1);
    expect(workbench.tickets.value).toEqual([{ pk: "t1" }]);
    expect(workbench.articles.value).toEqual([{ pk: "a1" }]);
    expect(workbench.loading.value).toBe(false);
  });

  it("没有列表权限的部分不请求", async () => {
    mocks.articleList.mockResolvedValue(ok({ results: [] }));
    const workbench = useWorkbench({
      tickets: () => false,
      articles: () => true
    });
    await workbench.reload();
    expect(mocks.dashboard).not.toHaveBeenCalled();
    expect(mocks.ticketList).not.toHaveBeenCalled();
    expect(mocks.articleList).toHaveBeenCalledTimes(1);
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

describe("工作台视角", () => {
  const base = { status: {}, priority: {}, sla: {} } as never;

  it("由看板的指派维度推断视角", () => {
    expect(workbenchRole(null)).toBe("requester");
    expect(
      workbenchRole({ ...(base as object), assignment: {} } as never)
    ).toBe("requester");
    expect(
      workbenchRole({
        ...(base as object),
        assignment: { unassigned: 2 }
      } as never)
    ).toBe("admin");
    expect(
      workbenchRole({
        ...(base as object),
        assignment: { current: 1, history: 0 }
      } as never)
    ).toBe("agent");
  });

  it("各视角的计数卡与筛选", () => {
    expect(cardsFor("admin")[0]).toMatchObject({
      key: "unassigned",
      query: { assignment: "unassigned" }
    });
    expect(
      cardsFor("agent")
        .map(card => card.key)
        .slice(0, 2)
    ).toEqual(["current", "history"]);
    expect(cardsFor("requester").map(card => card.key)).toEqual([
      "open",
      "inProgress",
      "verifying",
      "reopened"
    ]);
  });

  it("summarize 读取指派计数", () => {
    const stats = summarize({
      ...(base as object),
      assignment: { current: 3, history: 1 }
    } as never);
    expect(stats.current).toBe(3);
    expect(stats.history).toBe(1);
    expect(stats.unassigned).toBe(0);
  });
});

describe("WorkbenchStats", () => {
  it("按传入的卡片展示计数，点击带上与计数一致的单项筛选", async () => {
    const stats = {
      ...summarize(null),
      unassigned: 5,
      open: 3,
      overdue: 1
    };
    const wrapper = mount(WorkbenchStats, {
      props: { stats, cards: cardsFor("admin") },
      global: { stubs: { "el-icon": true } }
    });
    await flushPromises();
    expect(
      wrapper.get('[data-testid="workbench-stat-unassigned"]').text()
    ).toContain("5");
    expect(
      wrapper.find('[data-testid="workbench-stat-history"]').exists()
    ).toBe(false);
    for (const key of ["unassigned", "open", "overdue"]) {
      await wrapper
        .get(`[data-testid="workbench-stat-${key}"]`)
        .trigger("click");
    }
    expect(wrapper.emitted("open")).toEqual([
      [{ assignment: "unassigned" }],
      [{ status: "OPEN" }],
      [{ sla: "OVERDUE" }]
    ]);
  });
});
