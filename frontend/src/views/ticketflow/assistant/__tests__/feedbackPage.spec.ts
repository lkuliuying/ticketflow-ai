import { defineComponent } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import ElementPlus from "element-plus";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  summary: vi.fn(),
  downvotes: vi.fn(),
  handoffs: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});
vi.mock("@/api/ticketflow/assistant", () => ({
  assistantFeedbackApi: {
    summary: mocks.summary,
    downvotes: mocks.downvotes,
    handoffs: mocks.handoffs
  }
}));

import FeedbackPage from "../feedback/index.vue";

const listStub = (fetch: (range: object) => void) =>
  defineComponent({
    setup(_props, { expose }) {
      expose({ apply: async (range: object) => fetch(range) });
      return () => null;
    }
  });

describe("AI 反馈页", () => {
  beforeEach(() => vi.clearAllMocks());

  it("时间段换成带时区的整日起止，同时作用于统计与两个列表", async () => {
    mocks.summary.mockResolvedValue({
      code: 1000,
      data: { sessions: 4, questions: 6, up: 3, down: 1, handoffs: 1 }
    });
    const wrapper = mount(FeedbackPage, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          DownvoteList: listStub(mocks.downvotes),
          HandoffList: listStub(mocks.handoffs)
        }
      }
    });
    await flushPromises();
    expect(mocks.summary).toHaveBeenLastCalledWith({});
    expect(
      wrapper.get('[data-testid="assistant-summary-upRate"]').text()
    ).toContain("75.0%");
    expect(
      wrapper.get('[data-testid="assistant-summary-handoffRate"]').text()
    ).toContain("25.0%");

    const picker = wrapper.findComponent({ name: "ElDatePicker" });
    await picker.vm.$emit("update:modelValue", ["2026-11-01", "2026-11-23"]);
    wrapper.vm.applyPeriod();
    await flushPromises();

    const range = mocks.summary.mock.lastCall?.[0];
    expect(range.created_from).toMatch(/^2026-11-01T00:00:00[+-]\d\d:\d\d$/);
    expect(range.created_to).toMatch(/^2026-11-23T23:59:59[+-]\d\d:\d\d$/);
    expect(mocks.downvotes).toHaveBeenLastCalledWith(range);
    expect(mocks.handoffs).toHaveBeenLastCalledWith(range);
  });
});
