import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

const mocks = vi.hoisted(() => ({ openArticleDetail: vi.fn() }));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({
      t: (key: string, params?: Record<string, unknown>) =>
        params ? `${key}:${JSON.stringify(params)}` : key,
      te: () => false
    })
  };
});

vi.mock("../../../knowledge/utils/articleDetailDrawer", () => ({
  openArticleDetail: mocks.openArticleDetail
}));

const initialReply = () => ({
  status: "done",
  text: "您好",
  references: [
    { article_id: "0fc760c7-193c-41e9", title: "VPN 连接失败排查指南" },
    { article_id: "9a8b7c6d5e4f3a2b", title: "" }
  ]
});
const reply = ref(initialReply());
vi.mock("../../utils/useTicketAi", () => ({
  useTicketAnalysis: () => ({
    analysis: ref(null),
    analyzing: ref(false),
    stale: ref(false),
    analyze: vi.fn(),
    adopt: vi.fn()
  }),
  useReplyStream: () => ({ reply, generate: vi.fn(), stop: vi.fn() })
}));

import TicketAiPanel from "../TicketAiPanel.vue";

/** 回复建议的引用：列出标题、无标题时用 ID 前 8 位，点击在知识库抽屉中打开 */
function mountPanel() {
  return mount(TicketAiPanel, {
    props: {
      ticket: { pk: "t1", version: 2 } as never,
      run: vi.fn(),
      busy: false,
      canFill: true
    }
  });
}

describe("TicketAiPanel 引用文章", () => {
  beforeEach(() => {
    reply.value = initialReply();
    mocks.openArticleDetail.mockReset();
  });

  it("列出引用标题，标题缺失时显示 ID 前 8 位", () => {
    const refs = mountPanel().get('[data-testid="ai-references"]');
    const buttons = refs.findAll("el-button");
    expect(buttons.map(b => b.text())).toEqual([
      "VPN 连接失败排查指南",
      "9a8b7c6d"
    ]);
    expect(refs.text()).toContain('"count":2');
  });

  it("点击引用用同一显示名打开文章抽屉", async () => {
    const buttons = mountPanel().findAll(
      '[data-testid="ai-references"] el-button'
    );
    await buttons[0].trigger("click");
    await buttons[1].trigger("click");
    expect(mocks.openArticleDetail.mock.calls).toEqual([
      [{ pk: "0fc760c7-193c-41e9", title: "VPN 连接失败排查指南" }],
      [{ pk: "9a8b7c6d5e4f3a2b", title: "9a8b7c6d" }]
    ]);
  });

  it("没有引用时不渲染引用区", () => {
    reply.value = { ...reply.value, references: [] };
    expect(mountPanel().find('[data-testid="ai-references"]').exists()).toBe(
      false
    );
  });
});
