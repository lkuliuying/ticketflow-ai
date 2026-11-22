import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SseFrame } from "@/utils/sse";

const mocks = vi.hoisted(() => ({ postSse: vi.fn(), request: vi.fn() }));
vi.mock("@/utils/sse", () => ({ postSse: mocks.postSse }));
vi.mock("@/utils/http", () => ({ http: { request: mocks.request } }));

import {
  analyzeTicket,
  applyReplyFrame,
  emptyReply,
  streamReply,
  type ReplyState
} from "./ai";

const frame = (event: string, data: unknown): SseFrame => ({
  event,
  data: JSON.stringify(data)
});
const streaming = (): ReplyState => ({ ...emptyReply(), status: "streaming" });

/** 让 postSse 依次吐出给定帧；`hang` 时在最后挂起直到被中止 */
function emit(frames: SseFrame[], options: { hang?: boolean } = {}) {
  mocks.postSse.mockImplementation(
    async (
      _url: string,
      _body: unknown,
      {
        onFrame,
        signal
      }: { onFrame: (f: SseFrame) => void; signal: AbortSignal }
    ) => {
      for (const item of frames) onFrame(item);
      if (options.hang) {
        await new Promise((_, reject) =>
          signal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          )
        );
      }
    }
  );
}

beforeEach(() => {
  mocks.postSse.mockReset();
  mocks.request.mockReset();
});

describe("applyReplyFrame", () => {
  it("follows meta → delta → done and ignores heartbeats", () => {
    let state = streaming();
    state = applyReplyFrame(
      state,
      frame("meta", { ticket_version: 3, references: ["a1", "a2"] })
    );
    state = applyReplyFrame(state, frame("delta", { text: "您好，" }));
    state = applyReplyFrame(state, frame("ping", {}));
    state = applyReplyFrame(state, frame("delta", { text: "请重启 VPN" }));
    state = applyReplyFrame(state, frame("done", { finish_reason: "stop" }));
    expect(state).toMatchObject({
      status: "done",
      text: "您好，请重启 VPN",
      references: ["a1", "a2"],
      ticketVersion: 3,
      finishReason: "stop"
    });
  });

  it("ends with the error frame details", () => {
    const state = applyReplyFrame(
      applyReplyFrame(streaming(), frame("delta", { text: "部分" })),
      frame("error", { code: 504, detail: "上游超时", retryable: true })
    );
    expect(state.status).toBe("error");
    expect(state.text).toBe("部分");
    expect(state.error).toEqual({
      code: 504,
      detail: "上游超时",
      retryable: true
    });
  });

  it("ignores frames after a terminal state and malformed payloads", () => {
    const done = applyReplyFrame(streaming(), frame("done", {}));
    expect(applyReplyFrame(done, frame("delta", { text: "x" }))).toBe(done);
    const broken = applyReplyFrame(streaming(), {
      event: "delta",
      data: "{not json"
    });
    expect(broken.text).toBe("");
    expect(broken.status).toBe("streaming");
  });
});

describe("streamReply", () => {
  it("posts the ticket id and reports every state change", async () => {
    emit([frame("delta", { text: "A" }), frame("done", {})]);
    const updates: string[] = [];
    const result = await streamReply(
      "t-1",
      s => updates.push(`${s.status}:${s.text}`),
      new AbortController().signal
    );
    expect(mocks.postSse.mock.calls[0][0]).toBe(
      "/ai/v1/tickets/suggest-reply/stream"
    );
    expect(mocks.postSse.mock.calls[0][1]).toEqual({ ticket_id: "t-1" });
    expect(updates).toEqual(["streaming:", "streaming:A", "done:A"]);
    expect(result.status).toBe("done");
  });

  it("treats a stream that ends without done as interrupted", async () => {
    emit([frame("delta", { text: "半句" })]);
    const result = await streamReply(
      "t-1",
      () => undefined,
      new AbortController().signal
    );
    expect(result).toMatchObject({ status: "interrupted", text: "半句" });
  });

  it("marks a cancelled stream as stopped and drops frames after abort", async () => {
    const controller = new AbortController();
    mocks.postSse.mockImplementation(
      async (
        _url: string,
        _body: unknown,
        { onFrame }: { onFrame: (f: SseFrame) => void }
      ) => {
        onFrame(frame("delta", { text: "已生成" }));
        controller.abort();
        // 取消后同一轮事件循环里迟到的一帧
        onFrame(frame("delta", { text: "迟到" }));
        throw new DOMException("aborted", "AbortError");
      }
    );
    const result = await streamReply("t-1", () => undefined, controller.signal);
    expect(result).toMatchObject({ status: "stopped", text: "已生成" });
  });

  it("rethrows errors raised before the stream opens", async () => {
    mocks.postSse.mockRejectedValue(
      Object.assign(new Error("无权使用"), { code: 403 })
    );
    await expect(
      streamReply("t-1", () => undefined, new AbortController().signal)
    ).rejects.toMatchObject({ code: 403 });
  });
});

describe("analyzeTicket", () => {
  it("posts the ticket id to the analysis endpoint", async () => {
    mocks.request.mockResolvedValue({ ticket_id: "t-1", ticket_version: 2 });
    await analyzeTicket("t-1");
    expect(mocks.request).toHaveBeenCalledWith(
      "post",
      "/ai/v1/tickets/analyze",
      { data: { ticket_id: "t-1" } }
    );
  });
});
