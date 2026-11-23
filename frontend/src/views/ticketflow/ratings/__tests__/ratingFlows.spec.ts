import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

const mocks = vi.hoisted(() => ({
  addDialog: vi.fn(),
  rate: vi.fn(),
  summary: vi.fn(),
  message: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) };
});
vi.mock("@/plugins/i18n", () => ({
  i18n: { global: { t: (key: string) => key } },
  $t: (key: string) => key,
  transformI18n: (key: string) => key
}));
vi.mock("@/components/ReDialog", () => ({ addDialog: mocks.addDialog }));
vi.mock("@/utils/message", () => ({ message: mocks.message }));
vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { rate: mocks.rate }
}));
vi.mock("@/api/ticketflow/ratings", async importOriginal => {
  const actual =
    await importOriginal<typeof import("@/api/ticketflow/ratings")>();
  return { ...actual, ratingApi: { summary: mocks.summary } };
});
vi.mock("@/router/utils", () => ({
  usePageAuth: () => ({ list: true })
}));

import { openRatingDialog } from "../utils/ratingDialog";
import { useRatings } from "../utils/hook";
import StatsPage from "../stats/index.vue";

const ticket = { pk: "t1", number: "TF-1", assignee_name: "tf_agent" };
const payload = {
  resolved: true,
  satisfaction: 5,
  handler_score: 5,
  tags: [],
  comment: ""
};

type DialogOptions = {
  title: string;
  contentRenderer: () => { ref: { r: { value: unknown } } };
  beforeSure: (
    done: () => void,
    ctx: { closeLoading: () => void }
  ) => Promise<void>;
};

/** 取 addDialog 的配置，并把内容渲染出的表单 ref 换成可控的桩 */
function dialogOptions(getPayload: () => Promise<unknown>): DialogOptions {
  const options: DialogOptions = mocks.addDialog.mock.calls.at(-1)![0];
  options.contentRenderer().ref.r.value = { getPayload };
  return options;
}

describe("openRatingDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("关闭后自动弹出时使用提示补评的标题", () => {
    openRatingDialog(ticket, { afterClose: true });
    expect(mocks.addDialog.mock.calls[0][0].title).toBe(
      "ticketflow.rating.afterCloseTitle"
    );
    openRatingDialog(ticket);
    expect(mocks.addDialog.mock.calls[1][0].title).toBe(
      "ticketflow.rating.title"
    );
  });

  it("提交成功后关闭弹窗并回调", async () => {
    mocks.rate.mockResolvedValue({ code: 1000, data: {} });
    const onRated = vi.fn();
    openRatingDialog(ticket, { onRated });
    const options = dialogOptions(async () => payload);
    const done = vi.fn();
    await options.beforeSure(done, { closeLoading: vi.fn() });
    expect(mocks.rate).toHaveBeenCalledWith("t1", payload);
    expect(done).toHaveBeenCalled();
    expect(onRated).toHaveBeenCalled();
  });

  it("校验失败或提交失败时保持弹窗", async () => {
    const done = vi.fn();
    const closeLoading = vi.fn();
    openRatingDialog(ticket);
    await dialogOptions(async () => null).beforeSure(done, { closeLoading });
    expect(mocks.rate).not.toHaveBeenCalled();

    mocks.rate.mockResolvedValue({ code: 409, detail: "工单已评价" });
    openRatingDialog(ticket);
    await dialogOptions(async () => payload).beforeSure(done, {
      closeLoading
    });
    expect(done).not.toHaveBeenCalled();
    expect(closeLoading).toHaveBeenCalledTimes(2);
  });
});

describe("评价汇总加载", () => {
  beforeEach(() => vi.clearAllMocks());

  it("快速切换时只采用最后一次请求，失败时清空旧数据", async () => {
    let resolveFirst: (value: unknown) => void = () => undefined;
    mocks.summary
      .mockReturnValueOnce(new Promise(resolve => (resolveFirst = resolve)))
      .mockResolvedValueOnce({ code: 1000, data: { count: 2 } });
    let ratings!: ReturnType<typeof useRatings>;
    const Host = defineComponent({
      setup() {
        ratings = useRatings("TicketFlowMyRatings");
        return () => h("div");
      }
    });
    mount(Host);
    const first = ratings.loadSummary({ created_from: "2026-11-01" });
    await ratings.loadSummary({ created_from: "2026-11-20" });
    resolveFirst({ code: 1000, data: { count: 99 } });
    await first;
    expect(ratings.summary.value?.count).toBe(2);
    expect(ratings.summaryLoading.value).toBe(false);

    mocks.summary.mockRejectedValueOnce(new Error("boom"));
    await ratings.loadSummary();
    expect(ratings.summary.value).toBeNull();
  });
});

describe("评价统计页", () => {
  beforeEach(() => vi.clearAllMocks());

  function mountPage() {
    mocks.summary.mockResolvedValue({ code: 1000, data: { count: 0 } });
    const fields: Record<string, unknown> = {};
    const handleGetData = vi.fn();
    const PlusPage = defineComponent({
      setup(_, { expose }) {
        expose({ searchFields: fields, handleGetData });
        return () => h("div");
      }
    });
    const DatePicker = defineComponent({
      props: { modelValue: { type: Array, default: null } },
      emits: ["update:modelValue", "change"],
      setup: () => () => h("div", { class: "date-picker" })
    });
    const wrapper = mount(StatsPage, {
      global: {
        stubs: {
          RePlusPage: PlusPage,
          RatingSummaryCards: true,
          "el-card": { template: "<div><slot /></div>" },
          "el-table": true,
          "el-date-picker": DatePicker
        }
      }
    });
    const pick = (value: string[]) => {
      const picker = wrapper.findComponent(DatePicker);
      picker.vm.$emit("update:modelValue", value);
      picker.vm.$emit("change", value);
    };
    return { wrapper, fields, handleGetData, pick };
  }

  it("切换时间段同时刷新汇总与明细", async () => {
    const { fields, handleGetData, pick } = mountPage();
    await flushPromises();
    mocks.summary.mockClear();
    pick(["2026-11-01", "2026-11-23"]);
    await flushPromises();
    expect(mocks.summary).toHaveBeenCalledWith({
      created_from: "2026-11-01",
      created_to: "2026-11-23"
    });
    expect(fields).toMatchObject({
      created_from: "2026-11-01",
      created_to: "2026-11-23",
      page: 1
    });
    expect(handleGetData).toHaveBeenCalled();
  });

  it("下钻带上处理人与当前时间段，没有处理人的行不下钻", async () => {
    const { wrapper, fields, handleGetData, pick } = mountPage();
    await flushPromises();
    pick(["2026-11-01", "2026-11-23"]);
    await flushPromises();
    handleGetData.mockClear();

    wrapper.vm.drillDown({ handler_id: null } as never);
    expect(handleGetData).not.toHaveBeenCalled();

    wrapper.vm.drillDown({ handler_id: 2 } as never);
    expect(fields).toMatchObject({
      handler_id: 2,
      created_from: "2026-11-01",
      created_to: "2026-11-23",
      page: 1
    });
    expect(handleGetData).toHaveBeenCalled();
  });
});
