import { beforeEach, describe, expect, it, vi } from "vitest";

type BeforeSure = (
  done: () => void,
  ctx: { closeLoading: () => void }
) => Promise<void>;

const dialogState = vi.hoisted(() => ({
  beforeSure: null as BeforeSure | null,
  getPayload: vi.fn()
}));
const apiMocks = vi.hoisted(() => ({ create: vi.fn() }));
const messageMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/ReDialog", () => ({
  addDialog: (options: { beforeSure: BeforeSure }) => {
    dialogState.beforeSure = options.beforeSure;
  }
}));
vi.mock("@/components/ReDialog/size", () => ({ dialogSize: () => "640px" }));
vi.mock("@/utils/message", () => ({ message: messageMock }));
vi.mock("@/api/ticketflow/tickets", () => ({ ticketApi: apiMocks }));
vi.mock("../../components/TicketCreateForm.vue", () => ({
  default: { name: "TicketCreateForm", render: () => null }
}));
// 表单引用由弹窗内部 ref 持有：让 ref() 返回带 getPayload 的固定对象
vi.mock("vue", async importOriginal => {
  const actual = await importOriginal<typeof import("vue")>();
  return {
    ...actual,
    ref: (value?: unknown) =>
      value === undefined
        ? { value: { getPayload: dialogState.getPayload } }
        : actual.ref(value)
  };
});

import { openTicketCreateDialog } from "../ticketCreateDialog";

async function submit() {
  const done = vi.fn();
  const closeLoading = vi.fn();
  await dialogState.beforeSure?.(done, { closeLoading });
  return { done, closeLoading };
}

describe("新建工单弹窗", () => {
  beforeEach(() => {
    apiMocks.create.mockReset();
    messageMock.mockReset();
    dialogState.getPayload.mockResolvedValue({
      title: "VPN",
      description: "无法连接",
      category: "NETWORK",
      priority: "P2"
    });
    openTicketCreateDialog({
      title: "新建工单",
      createdText: "created",
      failedText: "failed"
    });
  });

  it("业务码失败时提示后端原因并保持弹窗", async () => {
    apiMocks.create.mockResolvedValueOnce({ code: 9999, detail: "分类无效" });
    const { done, closeLoading } = await submit();
    expect(closeLoading).toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    expect(messageMock).toHaveBeenCalledWith("分类无效", { type: "error" });
  });

  it("业务码失败且无原因时使用兜底文案", async () => {
    apiMocks.create.mockResolvedValueOnce({ code: 9999 });
    await submit();
    expect(messageMock).toHaveBeenCalledWith("failed", { type: "error" });
  });

  it("请求异常由拦截器提示，不重复弹错", async () => {
    apiMocks.create.mockRejectedValueOnce(new Error("500"));
    const { done, closeLoading } = await submit();
    expect(closeLoading).toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    expect(messageMock).not.toHaveBeenCalled();
  });

  it("表单校验失败时不提交", async () => {
    dialogState.getPayload.mockResolvedValueOnce(null);
    const { closeLoading } = await submit();
    expect(closeLoading).toHaveBeenCalled();
    expect(apiMocks.create).not.toHaveBeenCalled();
  });

  it("成功时提示并关闭弹窗", async () => {
    apiMocks.create.mockResolvedValueOnce({ code: 1000, data: { pk: "t1" } });
    const { done } = await submit();
    expect(done).toHaveBeenCalled();
    expect(messageMock).toHaveBeenCalledWith("created", { type: "success" });
  });
});
