import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({
  requestMock: vi.fn()
}));

vi.mock("@/utils/http", () => ({
  http: { request: requestMock }
}));

import { ticketApi } from "./tickets";

const payload = {
  title: "VPN 无法连接",
  description: "早上开始连不上",
  category: "NETWORK",
  priority: "P1"
} as const;

function sentKey(callIndex: number): string {
  const config = requestMock.mock.calls[callIndex][3] as {
    headers: Record<string, string>;
  };
  return config.headers["Idempotency-Key"];
}

/**
 * 工单接口契约：建单必须携带幂等键，失败重试复用同一个键，
 * 成功后释放；流转、指派等写操作命中设计文档约定的路径。
 */
describe("ticketApi 建单幂等键", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("失败后用同一份内容重试，沿用同一个幂等键", async () => {
    requestMock.mockRejectedValueOnce(new Error("timeout"));
    requestMock.mockResolvedValueOnce({ code: 1000, data: {} });

    await expect(ticketApi.create({ ...payload })).rejects.toThrow("timeout");
    await ticketApi.create({ ...payload });

    expect(requestMock).toHaveBeenCalledTimes(2);
    expect(requestMock.mock.calls[0][0]).toBe("post");
    expect(requestMock.mock.calls[0][1]).toBe("/api/tickets");
    expect(sentKey(0)).toMatch(/^[0-9a-z]{16,}$/);
    expect(sentKey(1)).toBe(sentKey(0));
  });

  it("成功后释放幂等键，同样内容的下一次提交视为新工单", async () => {
    requestMock.mockResolvedValue({ code: 1000, data: {} });

    await ticketApi.create({ ...payload });
    await ticketApi.create({ ...payload });

    expect(sentKey(1)).not.toBe(sentKey(0));
  });

  it("字段顺序不同的同一份内容视为同一次提交", async () => {
    requestMock.mockResolvedValueOnce({ code: 1001, data: {} });
    requestMock.mockResolvedValueOnce({ code: 1000, data: {} });

    await ticketApi.create({ ...payload });
    await ticketApi.create({
      priority: payload.priority,
      category: payload.category,
      description: payload.description,
      title: payload.title
    });

    expect(sentKey(1)).toBe(sentKey(0));
  });
});

describe("ticketApi 幂等键保留期", () => {
  it("未成功的键在服务端保留期内复用，超过后换新键", () => {
    const content = { ...payload, title: "保留期用例" };
    const start = 1_700_000_000_000;
    const first = ticketApi.idempotencyKeyFor(content, start);

    expect(ticketApi.idempotencyKeyFor(content, start + 60 * 60 * 1000)).toBe(
      first
    );
    expect(
      ticketApi.idempotencyKeyFor(content, start + 24 * 60 * 60 * 1000)
    ).not.toBe(first);
  });
});

describe("ticketApi 写操作路径", () => {
  beforeEach(() => {
    requestMock.mockReset();
    requestMock.mockResolvedValue({ code: 1000, data: {} });
  });

  it("流转、指派、回复、时间线与看板", () => {
    const pk = "7f1c2d1e-0000-4000-8000-000000000001";
    ticketApi.transition(pk, { target_status: "IN_PROGRESS", version: 3 });
    ticketApi.assign(pk, { assignee_id: 9, version: 4 });
    ticketApi.comments(pk, { body: "已处理", visibility: "INTERNAL" });
    ticketApi.timeline(pk, { page: 2, size: 20 });
    ticketApi.dashboard({ status: "OPEN" });

    const calls = requestMock.mock.calls.map(call => [call[0], call[1]]);
    expect(calls).toEqual([
      ["post", `/api/tickets/${pk}/transition`],
      ["post", `/api/tickets/${pk}/assign`],
      ["post", `/api/tickets/${pk}/comments`],
      ["get", `/api/tickets/${pk}/timeline`],
      ["get", "/api/tickets/dashboard"]
    ]);
    expect(requestMock.mock.calls[0][2].data).toEqual({
      target_status: "IN_PROGRESS",
      version: 3
    });
  });
});
