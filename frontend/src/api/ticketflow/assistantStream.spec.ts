import { describe, expect, it } from "vitest";
import { applyChatFrame, emptyChat, type ChatState } from "./assistantStream";

const streaming = (): ChatState => ({ ...emptyChat(), status: "streaming" });
const frame = (event: string, data: unknown) => ({
  event,
  data: JSON.stringify(data)
});

describe("applyChatFrame", () => {
  it("按 meta → delta → done 推进，记录问题与回答 ID", () => {
    let state = applyChatFrame(
      streaming(),
      frame("meta", {
        session_id: "s1",
        user_message_id: "q1",
        references: [
          { article_id: " a1 ", title: " VPN 指南 " },
          { article_id: "", title: "无效" },
          "bad"
        ]
      })
    );
    expect(state.userMessageId).toBe("q1");
    expect(state.references).toEqual([{ article_id: "a1", title: "VPN 指南" }]);

    state = applyChatFrame(state, frame("delta", { text: "先" }));
    state = applyChatFrame(state, frame("delta", { text: "重连" }));
    state = applyChatFrame(state, frame("ping", {}));
    expect(state.text).toBe("先重连");

    state = applyChatFrame(
      state,
      frame("done", { finish_reason: "stop", assistant_message_id: "a9" })
    );
    expect(state).toMatchObject({
      status: "done",
      finishReason: "stop",
      assistantMessageId: "a9"
    });
  });

  it("终态之后的帧一律忽略", () => {
    const done = applyChatFrame(streaming(), frame("done", {}));
    expect(applyChatFrame(done, frame("delta", { text: "残帧" }))).toBe(done);
  });

  it("error 帧结束流并保留可重试标记", () => {
    const state = applyChatFrame(
      streaming(),
      frame("error", { code: 503, detail: "繁忙", retryable: true })
    );
    expect(state).toMatchObject({
      status: "error",
      error: { code: 503, detail: "繁忙", retryable: true }
    });
  });

  it("无法解析的 delta 不改变状态", () => {
    const state = streaming();
    expect(applyChatFrame(state, { event: "delta", data: "{bad" })).toBe(state);
  });
});
