import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({
      t: (key: string, params?: Record<string, unknown>) =>
        params ? `${key}:${JSON.stringify(params)}` : key
    })
  };
});

import RatingForm from "../components/RatingForm.vue";
import RatingSummaryCards from "../components/RatingSummaryCards.vue";
import { formatPercent, formatScore } from "../utils/format";

describe("评价格式化", () => {
  it("平均分两位小数、解决率百分比，无数据显示占位", () => {
    expect(formatScore(4.5)).toBe("4.50");
    expect(formatScore(null)).toBe("—");
    expect(formatPercent(0.6667)).toBe("66.7%");
    expect(formatPercent(1)).toBe("100.0%");
    expect(formatPercent(undefined)).toBe("—");
  });
});

describe("RatingForm", () => {
  it("未选是否解决或未打分时校验失败，返回 null", async () => {
    const wrapper = mount(RatingForm, {
      props: { handlerName: "tf_agent" },
      global: { plugins: [ElementPlus] }
    });
    const vm = wrapper.vm;
    expect(await vm.getPayload()).toBeNull();

    vm.form.resolved = true;
    vm.form.satisfaction = 4;
    expect(await vm.getPayload()).toBeNull();
  });

  it("填写完整后返回去空白的提交数据", async () => {
    const wrapper = mount(RatingForm, { global: { plugins: [ElementPlus] } });
    const vm = wrapper.vm;
    vm.form.resolved = false;
    vm.form.satisfaction = 2;
    vm.form.handler_score = 4;
    vm.form.tags = ["PROFESSIONAL"];
    vm.form.comment = "  需要再跟进  ";
    await flushPromises();
    expect(await vm.getPayload()).toEqual({
      resolved: false,
      satisfaction: 2,
      handler_score: 4,
      tags: ["PROFESSIONAL"],
      comment: "需要再跟进"
    });
  });

  it("文字评价超过 500 字时校验失败", async () => {
    const wrapper = mount(RatingForm, { global: { plugins: [ElementPlus] } });
    const vm = wrapper.vm;
    Object.assign(vm.form, {
      resolved: true,
      satisfaction: 5,
      handler_score: 5,
      comment: "好".repeat(501)
    });
    await flushPromises();
    expect(await vm.getPayload()).toBeNull();
  });
});

describe("RatingSummaryCards", () => {
  it("展示汇总数值与全部标签计数", () => {
    const wrapper = mount(RatingSummaryCards, {
      props: {
        stats: {
          count: 3,
          avg_satisfaction: 3.67,
          avg_handler_score: 4.67,
          resolved_rate: 0.6667,
          tags: { CLEAR: 2 }
        }
      }
    });
    expect(
      wrapper.get('[data-testid="rating-summary-count"]').text()
    ).toContain("3");
    expect(
      wrapper.get('[data-testid="rating-summary-resolvedRate"]').text()
    ).toContain("66.7%");
    expect(wrapper.text()).toContain("ticketflow.rating.tagValue.CLEAR · 2");
    expect(wrapper.text()).toContain("ticketflow.rating.tagValue.FAST · 0");
  });
});
