import { flushPromises } from "@vue/test-utils";
import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReplyState } from "@/api/ticketflow/ai";

const mocks = vi.hoisted(() => ({
  analyzeTicket: vi.fn(),
  streamReply: vi.fn(),
  aiMetadata: vi.fn(),
  retrieve: vi.fn(),
  getToken: vi.fn()
}));

vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock("@/api/ticketflow/ai", () => ({
  analyzeTicket: mocks.analyzeTicket,
  streamReply: mocks.streamReply,
  emptyReply: () => ({ status: "idle", text: "", references: [] })
}));
vi.mock("@/api/ticketflow/tickets", () => ({
  ticketApi: { aiMetadata: mocks.aiMetadata, retrieve: mocks.retrieve }
}));
vi.mock("@/utils/auth", () => ({ getToken: mocks.getToken }));
vi.mock("vue", async importOriginal => ({
  ...(await importOriginal<typeof import("vue")>()),
  onBeforeUnmount: vi.fn()
}));

import { useReplyStream, useTicketAnalysis } from "../useTicketAi";
import { nextTick } from "vue";
import type { TicketDetail } from "@/api/ticketflow/tickets";

const PK = "2da1c8a8-31ca-40d4-90e3-e3842c849b02";
const analysis = {
  ticket_id: PK,
  ticket_version: 3,
  category: "NETWORK",
  suggested_priority: "P1",
  summary: "VPN 连接超时",
  tags: ["VPN", "网络"]
};

beforeEach(() => {
  Object.values(mocks).forEach(mock => mock.mockReset());
  mocks.getToken.mockReturnValue("access");
});

describe("useTicketAnalysis", () => {
  function setup(version = 3) {
    const ticket = ref({ pk: PK, version } as TicketDetail);
    const run = vi.fn(async (action: () => Promise<unknown>) => {
      await action();
      return true;
    });
    return { ticket, run, ...useTicketAnalysis(() => ticket.value, run) };
  }

  it("adopts with the version the analysis was based on", async () => {
    mocks.analyzeTicket.mockResolvedValue(analysis);
    const { analyze, adopt, run, stale } = setup();

    await analyze();
    expect(stale.value).toBe(false);
    await adopt();

    expect(run).toHaveBeenCalledTimes(1);
    expect(mocks.aiMetadata).toHaveBeenCalledWith(PK, {
      version: 3,
      summary: "VPN 连接超时",
      tags: ["VPN", "网络"],
      category: "NETWORK",
      priority: "P1"
    });
  });

  it("refuses to adopt once the ticket moved past the analysed version", async () => {
    mocks.analyzeTicket.mockResolvedValue(analysis);
    const { analyze, adopt, run, stale, ticket } = setup();

    await analyze();
    ticket.value = { ...ticket.value, version: 4 };
    expect(stale.value).toBe(true);
    await expect(adopt()).resolves.toBe(false);
    expect(run).not.toHaveBeenCalled();
  });

  it("drops the analysis when the panel switches to another ticket", async () => {
    mocks.analyzeTicket.mockResolvedValue(analysis);
    const { analyze, analysis: result, ticket, adopt, run } = setup();

    await analyze();
    ticket.value = { pk: "other-ticket", version: 3 } as TicketDetail;
    await nextTick();
    expect(result.value).toBeNull();
    await expect(adopt()).resolves.toBe(false);
    expect(run).not.toHaveBeenCalled();
  });

  it("keeps the previous result when analysis fails", async () => {
    mocks.analyzeTicket
      .mockResolvedValueOnce(analysis)
      .mockRejectedValueOnce({ code: 503, detail: "上游繁忙" });
    const { analyze, analysis: result, analyzing } = setup();

    await analyze();
    await analyze();
    expect(result.value).toEqual(analysis);
    expect(analyzing.value).toBe(false);
  });
});

describe("useReplyStream", () => {
  it("cancels the previous stream when generating again", async () => {
    const signals: AbortSignal[] = [];
    mocks.streamReply.mockImplementation(
      (_id: string, onUpdate: (s: ReplyState) => void, signal: AbortSignal) => {
        signals.push(signal);
        onUpdate({ status: "streaming", text: "", references: [] });
        return new Promise(() => undefined);
      }
    );
    const { generate, reply } = useReplyStream(() => PK);

    void generate();
    await flushPromises();
    void generate();
    await flushPromises();

    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
    expect(reply.value.status).toBe("streaming");
  });

  it("drops late updates from a stopped stream", async () => {
    let push: (s: ReplyState) => void = () => undefined;
    mocks.streamReply.mockImplementation(
      (_id: string, onUpdate: (s: ReplyState) => void) => {
        push = onUpdate;
        return new Promise(() => undefined);
      }
    );
    const first = useReplyStream(() => PK);
    void first.generate();
    await flushPromises();
    const stalePush = push;
    void first.generate();
    await flushPromises();

    stalePush({ status: "streaming", text: "旧流的字", references: [] });
    expect(first.reply.value.text).toBe("");
  });

  it("shows pre-stream failures with their detail", async () => {
    mocks.streamReply.mockRejectedValue(
      Object.assign(new Error("上游并发额度已用完"), { code: 503 })
    );
    const { generate, reply } = useReplyStream(() => PK);

    await generate();
    expect(reply.value.status).toBe("error");
    expect(reply.value.error).toEqual({
      code: 503,
      detail: "上游并发额度已用完",
      retryable: true
    });
  });

  it("refreshes an expired access token through axios before streaming", async () => {
    mocks.getToken.mockReturnValue("");
    mocks.retrieve.mockResolvedValue({ code: 1000 });
    mocks.streamReply.mockResolvedValue({ status: "done" });
    const { generate } = useReplyStream(() => PK);

    await generate();
    expect(mocks.retrieve).toHaveBeenCalledWith(PK);
    expect(mocks.streamReply).toHaveBeenCalledTimes(1);
  });

  it("hands a 401 to the axios session path and retries the stream once", async () => {
    mocks.retrieve.mockResolvedValue({ code: 1000 });
    mocks.streamReply
      .mockRejectedValueOnce(
        Object.assign(new Error("令牌失效"), { code: 401 })
      )
      .mockResolvedValueOnce({ status: "done" });
    const { generate, reply } = useReplyStream(() => PK);

    await generate();
    expect(mocks.retrieve).toHaveBeenCalledWith(PK);
    expect(mocks.streamReply).toHaveBeenCalledTimes(2);
    expect(reply.value.status).not.toBe("error");
  });

  it("does not retry when the session cannot be restored", async () => {
    mocks.retrieve.mockRejectedValue({ code: 401 });
    mocks.streamReply.mockRejectedValue(
      Object.assign(new Error("令牌失效"), { code: 401 })
    );
    const { generate, reply } = useReplyStream(() => PK);

    await generate();
    expect(mocks.streamReply).toHaveBeenCalledTimes(1);
    expect(reply.value.status).toBe("error");
    expect(reply.value.error?.retryable).toBe(false);
  });

  it("skips streaming when the session cannot be established first", async () => {
    mocks.getToken.mockReturnValue("");
    mocks.retrieve.mockRejectedValue({ code: 401 });
    const { generate } = useReplyStream(() => PK);

    await generate();
    expect(mocks.streamReply).not.toHaveBeenCalled();
  });

  it("does not open a stream after being stopped during session setup", async () => {
    mocks.getToken.mockReturnValue("");
    let finish: (value: unknown) => void = () => undefined;
    mocks.retrieve.mockReturnValue(new Promise(resolve => (finish = resolve)));
    const { generate, stop } = useReplyStream(() => PK);

    const pending = generate();
    stop();
    finish({ code: 1000 });
    await pending;
    expect(mocks.streamReply).not.toHaveBeenCalled();
  });

  it("cancels and clears the reply when the ticket changes", async () => {
    const signals: AbortSignal[] = [];
    mocks.streamReply.mockImplementation(
      (_id: string, onUpdate: (s: ReplyState) => void, signal: AbortSignal) => {
        signals.push(signal);
        onUpdate({ status: "streaming", text: "旧工单", references: [] });
        return new Promise(() => undefined);
      }
    );
    const id = ref(PK);
    const { generate, reply } = useReplyStream(() => id.value);

    void generate();
    await flushPromises();
    id.value = "other-ticket";
    await nextTick();
    expect(signals[0].aborted).toBe(true);
    expect(reply.value).toMatchObject({ status: "idle", text: "" });
  });
});
