import { beforeEach, describe, expect, it, vi } from "vitest";

const { retrieveMock, messageMock } = vi.hoisted(() => ({
  retrieveMock: vi.fn(),
  messageMock: vi.fn()
}));

vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { retrieve: retrieveMock }
}));
vi.mock("@/utils/message", () => ({ message: messageMock }));

import { useTicketDetail } from "../useTicketDetail";
import {
  logActionKey,
  transitionButtonType,
  transitionLabelKey
} from "../ticketActions";

const PK = "93ef9340-fc5d-4440-8f1b-896c12607ea5";
const ticket = (version: number) => ({ pk: PK, version });

/** 工单详情的写操作执行器与流转动作命名 */
describe("useTicketDetail", () => {
  beforeEach(() => {
    retrieveMock.mockReset();
    messageMock.mockReset();
  });

  it("成功后提示、重新加载并通知列表", async () => {
    retrieveMock.mockResolvedValue({ code: 1000, data: ticket(2) });
    const onChanged = vi.fn();
    const { detail, run } = useTicketDetail(PK, onChanged);

    const ok = await run(async () => ({ code: 1000 }), "已接单");

    expect(ok).toBe(true);
    expect(messageMock).toHaveBeenCalledWith("已接单", { type: "success" });
    expect(detail.value).toEqual(ticket(2));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("409 冲突时重新加载到最新版本并通知列表，不重复提示", async () => {
    retrieveMock.mockResolvedValue({ code: 1000, data: ticket(4) });
    const onChanged = vi.fn();
    const { detail, run } = useTicketDetail(PK, onChanged);

    const ok = await run(() => Promise.reject({ code: 409 }), "已提交验收");

    expect(ok).toBe(false);
    expect(detail.value).toEqual(ticket(4));
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(messageMock).not.toHaveBeenCalled();
  });

  it("执行中再次提交直接拒绝", async () => {
    let finish!: (value: { code: number }) => void;
    const pending = new Promise<{ code: number }>(
      resolve => (finish = resolve)
    );
    retrieveMock.mockResolvedValue({ code: 1000, data: ticket(2) });
    const { busy, run } = useTicketDetail(PK);

    const first = run(() => pending, "已指派");
    expect(busy.value).toBe(true);
    expect(await run(async () => ({ code: 1000 }), "已指派")).toBe(false);

    finish({ code: 1000 });
    expect(await first).toBe(true);
    expect(busy.value).toBe(false);
  });

  it("只有 404 进入不存在状态，网络错误保留已加载的详情", async () => {
    const { detail, notFound, load } = useTicketDetail(PK);
    retrieveMock.mockResolvedValueOnce({ code: 1000, data: ticket(3) });
    await load();

    retrieveMock.mockRejectedValueOnce(new Error("Network Error"));
    await load();
    expect(notFound.value).toBe(false);
    expect(detail.value).toEqual(ticket(3));

    retrieveMock.mockRejectedValueOnce({ code: 404 });
    await load();
    expect(notFound.value).toBe(true);
  });
});

describe("流转动作命名", () => {
  it("同一目标状态按来源状态区分动作", () => {
    expect(transitionLabelKey("OPEN", "IN_PROGRESS")).toBe(
      "ticketflow.action.accept"
    );
    expect(transitionLabelKey("PENDING_VERIFY", "IN_PROGRESS")).toBe(
      "ticketflow.action.reject"
    );
    expect(transitionLabelKey("REOPENED", "IN_PROGRESS")).toBe(
      "ticketflow.action.resume"
    );
    expect(transitionLabelKey("IN_PROGRESS", "PENDING_VERIFY")).toBe(
      "ticketflow.action.submitVerify"
    );
    expect(transitionLabelKey("PENDING_VERIFY", "CLOSED")).toBe(
      "ticketflow.action.close"
    );
    expect(transitionLabelKey("CLOSED", "REOPENED")).toBe(
      "ticketflow.action.reopen"
    );
  });

  it("关闭用成功色，退回与重开用警示色", () => {
    expect(transitionButtonType("PENDING_VERIFY", "CLOSED")).toBe("success");
    expect(transitionButtonType("PENDING_VERIFY", "IN_PROGRESS")).toBe(
      "warning"
    );
    expect(transitionButtonType("CLOSED", "REOPENED")).toBe("warning");
    expect(transitionButtonType("OPEN", "IN_PROGRESS")).toBe("primary");
  });

  it("未知日志动作回退到通用文案", () => {
    expect(logActionKey("ASSIGN")).toBe("ticketflow.log.ASSIGN");
    expect(logActionKey("SOMETHING_NEW")).toBe("ticketflow.log.OTHER");
  });
});
