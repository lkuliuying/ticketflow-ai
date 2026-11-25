import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TicketChatMessage } from "@/api/ticketflow/tickets";

const apiMocks = vi.hoisted(() => ({ chatMessages: vi.fn() }));

vi.mock("@/api/ticketflow/tickets", () => ({ ticketApi: apiMocks }));
vi.mock("@/utils/websocket", () => ({ WS: class {} }));

import { fetchMissedMessages } from "../chatSocket";

const msg = (id: string) => ({ id }) as TicketChatMessage;
const state = { can_send: true, lock_reason: "" as const };
const page = (ids: string[], hasMore: boolean) => ({
  code: 1000,
  data: { results: ids.map(msg), has_more: hasMore, chat_state: state }
});

describe("fetchMissedMessages 断线补拉", () => {
  beforeEach(() => apiMocks.chatMessages.mockReset());

  it("按 has_more 逐页补拉，游标取上一页最后一条", async () => {
    apiMocks.chatMessages
      .mockResolvedValueOnce(page(["m2", "m3"], true))
      .mockResolvedValueOnce(page(["m4"], false));

    const data = await fetchMissedMessages("t1", "m1");

    expect(data?.results.map(item => item.id)).toEqual(["m2", "m3", "m4"]);
    expect(apiMocks.chatMessages).toHaveBeenCalledTimes(2);
    expect(apiMocks.chatMessages.mock.calls[0][1]).toMatchObject({
      after_id: "m1"
    });
    expect(apiMocks.chatMessages.mock.calls[1][1]).toMatchObject({
      after_id: "m3"
    });
  });

  it("中途失败时保留已拉到的消息，首页失败返回 null", async () => {
    apiMocks.chatMessages
      .mockResolvedValueOnce(page(["m2"], true))
      .mockRejectedValueOnce(new Error("offline"));
    const partial = await fetchMissedMessages("t1", "m1");
    expect(partial?.results.map(item => item.id)).toEqual(["m2"]);

    apiMocks.chatMessages.mockRejectedValueOnce(new Error("offline"));
    expect(await fetchMissedMessages("t1", "m1")).toBeNull();
  });

  it("游标未前进时立即停止，不空转", async () => {
    apiMocks.chatMessages.mockResolvedValue(page(["m1"], true));
    const data = await fetchMissedMessages("t1", "m1");
    expect(apiMocks.chatMessages).toHaveBeenCalledTimes(1);
    expect(data?.results.map(item => item.id)).toEqual(["m1"]);
  });

  it("has_more 恒为 true 时在页数上限处停止", async () => {
    let n = 0;
    apiMocks.chatMessages.mockImplementation(async () =>
      page([`x${++n}`], true)
    );
    const data = await fetchMissedMessages("t1", "m1");
    expect(apiMocks.chatMessages).toHaveBeenCalledTimes(20);
    expect(data?.results).toHaveLength(20);
  });
});
