import { flushPromises, mount } from "@vue/test-utils";
import ElementPlus from "element-plus";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  openArticleDetail: vi.fn(),
  message: vi.fn(),
  handoffDraft: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});
vi.mock("@/utils/message", () => ({ message: mocks.message }));
vi.mock("../../knowledge/utils/articleDetailDrawer", () => ({
  openArticleDetail: mocks.openArticleDetail
}));
vi.mock("@/api/ticketflow/assistantStream", () => ({
  handoffDraft: mocks.handoffDraft
}));

import MessageBubble from "../components/MessageBubble.vue";
import HandoffForm from "../components/HandoffForm.vue";
import FeedbackForm from "../components/FeedbackForm.vue";
import { fallbackDraft, loadHandoffDraft } from "../utils/assistantDialogs";

const global = { plugins: [ElementPlus], stubs: { AiMarkdown: true } };

const answer = {
  role: "assistant" as const,
  content: "先重连",
  references: [{ article_id: "a1", title: "VPN 指南" }],
  status: "complete" as const,
  feedback: null
};

describe("MessageBubble", () => {
  beforeEach(() => vi.clearAllMocks());

  it("回答可评价时点赞点踩发出 vote，引用可打开原文", async () => {
    const wrapper = mount(MessageBubble, {
      props: { message: answer, feedbackable: true },
      global
    });
    await wrapper.get('[data-testid="vote-up"]').trigger("click");
    await wrapper.get('[data-testid="vote-down"]').trigger("click");
    expect(wrapper.emitted("vote")).toEqual([["up"], ["down"]]);
    await wrapper
      .get('[data-testid="answer-references"] button')
      .trigger("click");
    expect(mocks.openArticleDetail).toHaveBeenCalledWith({
      pk: "a1",
      title: "VPN 指南"
    });
  });

  it("只读或流式中的回答不显示评价；未完成的回答给出状态", () => {
    const readOnly = mount(MessageBubble, {
      props: { message: { ...answer, status: "interrupted" } },
      global
    });
    expect(readOnly.find('[data-testid="answer-feedback"]').exists()).toBe(
      false
    );
    expect(readOnly.get('[data-testid="answer-status"]').text()).toBe(
      "ticketflow.assistant.answerStatus.interrupted"
    );
    const streaming = mount(MessageBubble, {
      props: { message: answer, feedbackable: true, streaming: true },
      global
    });
    expect(streaming.find('[data-testid="answer-feedback"]').exists()).toBe(
      false
    );
  });
});

describe("HandoffForm", () => {
  it("提交前去掉首尾空白，草稿里不在词表内的分类回落为 OTHER", async () => {
    const wrapper = mount(HandoffForm, {
      props: {
        initial: {
          title: "  VPN 无法连接 ",
          description: " 已重连 ",
          category: "BOGUS"
        }
      },
      global
    });
    const payload = await wrapper.vm.getPayload();
    expect(payload).toEqual({
      title: "VPN 无法连接",
      description: "已重连",
      category: "OTHER",
      priority: "P2"
    });
  });

  it("标题为空时校验失败返回 null", async () => {
    const wrapper = mount(HandoffForm, {
      props: {
        initial: { title: "   ", description: "描述", category: "NETWORK" }
      },
      global
    });
    const payload = await wrapper.vm.getPayload();
    expect(payload).toBeNull();
  });
});

describe("FeedbackForm", () => {
  it("点踩载荷带原因与去空白的补充，改投时带出上次的原因", async () => {
    const wrapper = mount(FeedbackForm, {
      props: {
        initial: {
          vote: "down",
          reason: "UNRESOLVED",
          comment: " 重试仍报错 ",
          created_time: "",
          updated_time: ""
        }
      },
      global
    });
    const payload = await wrapper.vm.getPayload();
    expect(payload).toEqual({
      vote: "down",
      reason: "UNRESOLVED",
      comment: "重试仍报错"
    });
  });
});

describe("转人工草稿", () => {
  beforeEach(() => vi.clearAllMocks());

  it("草稿接口失败时用首个问题兜底并提示", async () => {
    mocks.handoffDraft.mockRejectedValue(new Error("503"));
    const draft = await loadHandoffDraft("s1", ["VPN 连不上", "重连也不行"]);
    expect(draft).toEqual(fallbackDraft(["VPN 连不上", "重连也不行"]));
    expect(draft.description).toBe("VPN 连不上\n\n重连也不行");
    expect(mocks.message).toHaveBeenCalledWith(expect.any(String), {
      type: "warning"
    });
  });

  it("草稿接口成功时原样使用", async () => {
    const draft = { title: "VPN", description: "d", category: "NETWORK" };
    mocks.handoffDraft.mockResolvedValue(draft);
    await expect(loadHandoffDraft("s1", [])).resolves.toEqual(draft);
    await flushPromises();
    expect(mocks.message).not.toHaveBeenCalled();
  });
});
