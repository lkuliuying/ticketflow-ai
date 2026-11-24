import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

const mocks = vi.hoisted(() => ({ dashboard: vi.fn() }));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) };
});
vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { dashboard: mocks.dashboard }
}));

import TicketDashboard from "../TicketDashboard.vue";

/** el-check-tag 在单测环境不解析，用最小桩把点击转成 change 事件 */
const CheckTag = defineComponent({
  emits: ["change"],
  setup(_, { slots, emit }) {
    return () =>
      h(
        "button",
        { class: "check-tag", onClick: () => emit("change") },
        slots.default?.()
      );
  }
});

async function mountWith(assignment: Record<string, number> | undefined) {
  mocks.dashboard.mockResolvedValue({
    code: 1000,
    detail: "",
    data: { status: {}, priority: {}, sla: {}, assignment }
  });
  const wrapper = mount(TicketDashboard, {
    props: { active: null },
    global: { stubs: { "el-check-tag": CheckTag } }
  });
  await wrapper.vm.refresh();
  await flushPromises();
  return wrapper;
}

const assignmentCard = '[data-testid="ticket-dashboard-assignment"]';

describe("TicketDashboard 指派维度", () => {
  it("员工（assignment 为空）不显示指派卡", async () => {
    const wrapper = await mountWith({});
    expect(wrapper.find(assignmentCard).exists()).toBe(false);
  });

  it("管理员只显示待分配，点击发出筛选", async () => {
    const wrapper = await mountWith({ unassigned: 3 });
    const card = wrapper.get(assignmentCard);
    expect(card.text()).toContain("ticketflow.assignmentValue.unassigned");
    expect(card.text()).toContain("3");
    expect(card.text()).not.toContain("ticketflow.assignmentValue.current");
    await card.get(".check-tag").trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual([
      { key: "assignment", value: "unassigned" }
    ]);
  });

  it("技术员显示处理中与历史处理，计数为 0 也展示", async () => {
    const wrapper = await mountWith({ current: 2, history: 0 });
    const text = wrapper.get(assignmentCard).text();
    expect(text).toContain("ticketflow.assignmentValue.current");
    expect(text).toContain("ticketflow.assignmentValue.history");
    expect(text).not.toContain("ticketflow.assignmentValue.unassigned");
  });
});
