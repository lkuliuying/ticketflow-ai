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

import RatingDetailDialog from "../components/RatingDetailDialog.vue";
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

describe("RatingDetailDialog", () => {
  it("隐藏内部 ID，按语义渲染已解决标签、翻译后的标签与空评价占位", () => {
    const wrapper = mount(RatingDetailDialog, {
      props: {
        canViewTicket: true,
        fixedHandlerName: "工单支持技术员",
        rating: {
          pk: "4bb16725-b0d2-4558-bfd0-537ec7248d96",
          ticket_id: "7b1096d3-ef7e-4830-9e8a-c6d9f6e81d00",
          ticket_number: "TF-20261125-TKFSSP",
          rater_id: 2,
          rater_name: "tf_requester",
          handler_id: 3,
          handler_name: "tf_agent",
          resolved: true,
          satisfaction: 5,
          handler_score: 5,
          tags: ["FAST", "PROFESSIONAL"],
          comment: "",
          created_time: "2026-11-25T04:47:21Z"
        }
      },
      global: { plugins: [ElementPlus] }
    });

    const text = wrapper.text();
    expect(text).toContain("TF-20261125-TKFSSP");
    expect(text).toContain("tf_requester");
    expect(text).toContain("工单支持技术员");
    expect(wrapper.get('[data-testid="rating-detail-resolved"]').text()).toBe(
      "ticketflow.rating.resolvedYes"
    );
    expect(
      wrapper.findAll('[data-testid="rating-detail-tag"]').map(n => n.text())
    ).toEqual([
      "ticketflow.rating.tagValue.FAST",
      "ticketflow.rating.tagValue.PROFESSIONAL"
    ]);
    expect(
      wrapper.get('[data-testid="rating-detail-comment-empty"]').text()
    ).toBe("ticketflow.rating.noComment");
    expect(text).not.toContain("4bb16725-b0d2-4558-bfd0-537ec7248d96");
    expect(text).not.toContain("7b1096d3-ef7e-4830-9e8a-c6d9f6e81d00");
    expect(text).not.toContain('["FAST"');
  });
});
