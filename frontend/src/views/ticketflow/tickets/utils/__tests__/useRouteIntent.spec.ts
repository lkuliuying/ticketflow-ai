import { describe, expect, it } from "vitest";
import { parseRouteIntent } from "../useRouteIntent";

describe("parseRouteIntent", () => {
  it("没有意图参数时返回 null", () => {
    expect(parseRouteIntent({})).toBeNull();
    expect(parseRouteIntent({ page: "2", create: "0" })).toBeNull();
  });

  it("create=1 打开新建表单", () => {
    expect(parseRouteIntent({ create: "1" })).toEqual({
      filter: null,
      create: true
    });
  });

  it("按 status、sla、priority 的顺序取第一个作为看板筛选", () => {
    expect(parseRouteIntent({ sla: "OVERDUE", status: "OPEN" })).toEqual({
      filter: { key: "status", value: "OPEN" },
      create: false
    });
    expect(parseRouteIntent({ priority: "P0" })?.filter).toEqual({
      key: "priority",
      value: "P0"
    });
  });

  it("忽略空值与数组形式的参数", () => {
    expect(parseRouteIntent({ status: "", sla: ["OVERDUE"] })).toBeNull();
  });
});
