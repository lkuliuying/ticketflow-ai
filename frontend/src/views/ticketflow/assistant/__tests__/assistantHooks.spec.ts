import { nextTick, ref } from "vue";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatState } from "@/api/ticketflow/assistantStream";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  messages: vi.fn(),
  send: vi.fn()
}));

vi.mock("@/api/ticketflow/assistant", () => ({
  assistantSessionApi: {
    list: mocks.list,
    create: mocks.create,
    rename: mocks.rename,
    remove: mocks.remove,
    messages: mocks.messages
  }
}));
vi.mock("../utils/useChatStream", async () => {
  const { ref: vueRef } = await import("vue");
  return {
    useChatStream: () => {
      const chat = vueRef({ status: "idle", text: "", references: [] });
      return { chat, send: mocks.send, stop: vi.fn(), reset: vi.fn() };
    }
  };
});

import { useAssistantSessions } from "../utils/useAssistantSessions";
import { LOCAL_PREFIX, useAssistantChat } from "../utils/useAssistantChat";

const session = (pk: string, title = pk) => ({
  pk,
  title,
  ticket_id: null,
  created_time: "2026-11-23T10:00:00+08:00",
  updated_time: "2026-11-23T10:00:00+08:00"
});
const ok = (data: unknown) => ({ code: 1000, data });
const page = (results: unknown[]) => ok({ total: results.length, results });

describe("useAssistantSessions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("加载后选中第一条，新建的会话排到最前并选中", async () => {
    mocks.list.mockResolvedValue(page([session("s1"), session("s2")]));
    mocks.create.mockResolvedValue(ok(session("s3")));
    const s = useAssistantSessions();
    await s.load();
    expect(s.activeId.value).toBe("s1");
    await s.create();
    expect(s.sessions.value.map(x => x.pk)).toEqual(["s3", "s1", "s2"]);
    expect(s.activeId.value).toBe("s3");
  });

  it("删除当前会话后选中下一条；204 空响应也视为成功", async () => {
    mocks.list.mockResolvedValue(page([session("s1"), session("s2")]));
    mocks.remove.mockResolvedValue("");
    const s = useAssistantSessions();
    await s.load();
    expect(await s.remove("s1")).toBe(true);
    expect(s.sessions.value.map(x => x.pk)).toEqual(["s2"]);
    expect(s.activeId.value).toBe("s2");
  });

  it("删除失败时保留会话", async () => {
    mocks.list.mockResolvedValue(page([session("s1")]));
    mocks.remove.mockRejectedValue(new Error("403"));
    const s = useAssistantSessions();
    await s.load();
    expect(await s.remove("s1")).toBe(false);
    expect(s.sessions.value).toHaveLength(1);
  });

  it("改名用服务端返回值替换并移到最前", async () => {
    mocks.list.mockResolvedValue(page([session("s1"), session("s2")]));
    mocks.rename.mockResolvedValue(ok(session("s2", "VPN 排查")));
    const s = useAssistantSessions();
    await s.load();
    await s.rename("s2", "VPN 排查");
    expect(s.sessions.value[0]).toMatchObject({ pk: "s2", title: "VPN 排查" });
  });
});

describe("useAssistantChat", () => {
  beforeEach(() => vi.clearAllMocks());

  const question = {
    pk: "q1",
    role: "user",
    content: "VPN 连不上",
    references: [],
    status: "complete",
    user_message_id: null,
    created_time: ""
  };
  const answer = {
    ...question,
    pk: "a1",
    role: "assistant",
    content: "先重连",
    user_message_id: "q1",
    feedback: null
  };

  async function setup() {
    const id = ref<string | null>("s1");
    mocks.messages.mockResolvedValue(page([]));
    const chat = useAssistantChat(() => id.value);
    await flushPromises();
    return { id, chat };
  }

  it("问题写入后以服务端消息为准刷新", async () => {
    const { chat } = await setup();
    mocks.send.mockResolvedValue({
      status: "done",
      text: "先重连",
      references: [],
      userMessageId: "q1"
    } satisfies ChatState);
    mocks.messages.mockResolvedValue(page([question, answer]));
    expect(await chat.ask("VPN 连不上")).toBe(true);
    expect(mocks.send).toHaveBeenCalledWith("s1", "VPN 连不上");
    expect(chat.messages.value.map(m => m.pk)).toEqual(["q1", "a1"]);
    expect(chat.pending.value).toBeNull();
  });

  it("问题没能写入（没有 meta）时返回 false，便于放回输入框", async () => {
    const { chat } = await setup();
    mocks.send.mockResolvedValue({
      status: "error",
      text: "",
      references: [],
      error: { code: 429, detail: "太频繁", retryable: true }
    } satisfies ChatState);
    expect(await chat.ask("VPN 连不上")).toBe(false);
    expect(mocks.messages).toHaveBeenCalledTimes(1);
    expect(chat.pending.value).toBeNull();
  });

  it("停止后服务端尚未写回时，用已收到的内容补一条中断回答", async () => {
    const { chat } = await setup();
    mocks.send.mockResolvedValue({
      status: "stopped",
      text: "先",
      references: [],
      userMessageId: "q1"
    } satisfies ChatState);
    mocks.messages.mockResolvedValue(page([question]));
    await chat.ask("VPN 连不上");
    const last = chat.messages.value.at(-1);
    expect(last).toMatchObject({
      pk: `${LOCAL_PREFIX}q1`,
      content: "先",
      status: "interrupted"
    });
  });

  it("切换会话时清空并加载新会话的消息", async () => {
    const { id, chat } = await setup();
    mocks.messages.mockResolvedValue(page([question]));
    id.value = "s2";
    await nextTick();
    await flushPromises();
    expect(mocks.messages).toHaveBeenLastCalledWith("s2", {
      page: 1,
      size: 100
    });
    expect(chat.messages.value).toHaveLength(1);
  });
});
