import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({
  requestMock: vi.fn()
}));

vi.mock("@/utils/http", () => ({
  http: { request: requestMock }
}));

import { knowledgeApi } from "./knowledge";
import { nextStatuses } from "@/views/ticketflow/knowledge/utils/articleStatus";

const payload = {
  title: "VPN 连接失败排查",
  body_markdown: "## 步骤",
  category: "NETWORK",
  tags: ["vpn"]
};

/** 知识库接口契约与文章状态流转规则 */
describe("knowledgeApi", () => {
  beforeEach(() => {
    requestMock.mockReset();
    requestMock.mockResolvedValue({ code: 1000, data: {} });
  });

  it("新建、转存与更新命中设计文档约定的路径和方法", () => {
    const pk = "c1f5e1c6-9859-470a-9b3c-34beb406c95c";
    knowledgeApi.createArticle(payload);
    knowledgeApi.createArticle({ ...payload, source_ticket_id: "t-1" });
    knowledgeApi.updateArticle(pk, { status: "PUBLISHED" });

    const calls = requestMock.mock.calls;
    expect(calls.map(call => [call[0], call[1]])).toEqual([
      ["post", "/api/knowledge/articles"],
      ["post", "/api/knowledge/articles"],
      ["patch", `/api/knowledge/articles/${pk}`]
    ]);
    expect(calls[1][2].data).toMatchObject({ source_ticket_id: "t-1" });
    expect(calls[2][2].data).toEqual({ status: "PUBLISHED" });
  });
});

describe("文章状态流转", () => {
  it("草稿只能发布，已发布可归档或退回，已归档可重新发布或退回", () => {
    expect(nextStatuses("DRAFT")).toEqual(["PUBLISHED"]);
    expect(nextStatuses("PUBLISHED")).toEqual(["ARCHIVED", "DRAFT"]);
    expect(nextStatuses("ARCHIVED")).toEqual(["PUBLISHED", "DRAFT"]);
  });
});
