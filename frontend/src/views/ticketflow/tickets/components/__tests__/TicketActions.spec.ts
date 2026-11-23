import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  prompt: vi.fn(),
  returnTicket: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) };
});
vi.mock("element-plus", async importOriginal => {
  const actual = await importOriginal<typeof import("element-plus")>();
  return { ...actual, ElMessageBox: { prompt: mocks.prompt } };
});
vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { returnTicket: mocks.returnTicket }
}));

import TicketActions from "../TicketActions.vue";

function mountWith(viewer: Record<string, boolean>) {
  const run = vi.fn(async (action: () => Promise<unknown>) => {
    await action();
    return true;
  });
  const wrapper = mount(TicketActions, {
    props: {
      ticket: {
        pk: "t1",
        status: "IN_PROGRESS",
        version: 4,
        available_transitions: [],
        viewer: {
          can_handle: true,
          can_assign: false,
          can_reply: true,
          can_comment_internal: true,
          can_archive: false,
          can_return: false,
          read_only: false,
          ...viewer
        }
      } as never,
      run,
      busy: false
    }
  });
  return { wrapper, run };
}

describe("TicketActions 退回重派", () => {
  beforeEach(() => vi.clearAllMocks());

  it("can_return 为假时不显示退回按钮", () => {
    const { wrapper } = mountWith({});
    expect(wrapper.find('[data-testid="ticket-return"]').exists()).toBe(false);
  });

  it("填写原因后带版本号提交，原因去掉首尾空白", async () => {
    mocks.prompt.mockResolvedValue({ value: "  不属于本组  " });
    mocks.returnTicket.mockResolvedValue({ code: 1000 });
    const { wrapper, run } = mountWith({ can_return: true });

    await wrapper.get('[data-testid="ticket-return"]').trigger("click");
    await flushPromises();

    expect(run).toHaveBeenCalledTimes(1);
    expect(mocks.returnTicket).toHaveBeenCalledWith("t1", {
      version: 4,
      reason: "不属于本组"
    });
  });

  it("取消对话框时不提交", async () => {
    mocks.prompt.mockRejectedValue("cancel");
    const { wrapper, run } = mountWith({ can_return: true });

    await wrapper.get('[data-testid="ticket-return"]').trigger("click");
    await flushPromises();

    expect(run).not.toHaveBeenCalled();
  });

  it("原因校验：必填且不超过 500 字", async () => {
    mocks.prompt.mockRejectedValue("cancel");
    const { wrapper } = mountWith({ can_return: true });
    await wrapper.get('[data-testid="ticket-return"]').trigger("click");
    const validator = mocks.prompt.mock.calls[0][2].inputValidator;

    expect(validator("   ")).toBe("ticketflow.detail.returnRequired");
    expect(validator("a".repeat(501))).toBe("ticketflow.detail.returnTooLong");
    expect(validator("原因")).toBe(true);
  });
});
