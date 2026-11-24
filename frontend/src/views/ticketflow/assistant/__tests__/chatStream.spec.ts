import { defineComponent } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatState } from "@/api/ticketflow/assistantStream";

const mocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  list: vi.fn(),
  getToken: vi.fn()
}));

vi.mock("@/api/ticketflow/assistantStream", () => ({
  emptyChat: () => ({ status: "idle", text: "", references: [] }),
  streamChat: mocks.streamChat
}));
vi.mock("@/api/ticketflow/assistant", () => ({
  assistantSessionApi: { list: mocks.list }
}));
vi.mock("@/utils/auth", () => ({ getToken: mocks.getToken }));

import { useChatStream } from "../utils/useChatStream";

function host() {
  let api: ReturnType<typeof useChatStream> | undefined;
  const wrapper = mount(
    defineComponent({
      setup() {
        api = useChatStream();
        return () => null;
      }
    })
  );
  return { wrapper, api: api! };
}

const done: ChatState = {
  status: "done",
  text: "好",
  references: [],
  userMessageId: "q1"
};

describe("useChatStream", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getToken.mockReturnValue({ accessToken: "x" });
  });

  it("建流 401 时经 axios 刷新登录态后重试一次", async () => {
    mocks.streamChat
      .mockRejectedValueOnce(Object.assign(new Error("expired"), { code: 401 }))
      .mockImplementationOnce(async (_s, _m, onUpdate) => {
        onUpdate(done);
        return done;
      });
    mocks.list.mockResolvedValue({
      code: 1000,
      data: { total: 0, results: [] }
    });
    const { api } = host();
    const state = await api.send("s1", "VPN");
    expect(mocks.streamChat).toHaveBeenCalledTimes(2);
    expect(state).toMatchObject({ status: "done", userMessageId: "q1" });
  });

  it("刷新失败时以错误结束，限流类错误标记可重试", async () => {
    mocks.streamChat.mockRejectedValue(
      Object.assign(new Error("太频繁"), { code: 429 })
    );
    const { api } = host();
    const state = await api.send("s1", "VPN");
    expect(state).toMatchObject({
      status: "error",
      error: { code: 429, detail: "太频繁", retryable: true }
    });
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it("卸载时取消在途的流，send 返回 null", async () => {
    let signal: AbortSignal | undefined;
    mocks.streamChat.mockImplementation(
      (_s, _m, _onUpdate, own: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal = own;
          own.addEventListener("abort", () => reject(new Error("aborted")));
        })
    );
    const { wrapper, api } = host();
    const sending = api.send("s1", "VPN");
    await flushPromises();
    wrapper.unmount();
    await expect(sending).resolves.toBeNull();
    expect(signal?.aborted).toBe(true);
  });
});
