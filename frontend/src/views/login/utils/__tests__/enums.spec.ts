import { describe, expect, it, vi } from "vitest";

vi.mock("@/plugins/i18n", () => ({ $t: (key: string) => key }));

import { LOGIN_PAGE, visibleOperates } from "../enums";

const pages = (caps: Parameters<typeof visibleOperates>[0]) =>
  visibleOperates(caps).map(item => item.page);

describe("visibleOperates", () => {
  it("注册关闭、验证码通道都未开时不显示任何入口", () => {
    expect(pages({})).toEqual([]);
  });

  it("邮箱或短信任一开启时显示验证码登录", () => {
    expect(pages({ email: true })).toEqual([LOGIN_PAGE.verifyCode]);
    expect(pages({ sms: true })).toEqual([LOGIN_PAGE.verifyCode]);
  });

  it("开放注册时显示注册入口，顺序不变", () => {
    expect(pages({ register: true })).toEqual([LOGIN_PAGE.register]);
    expect(pages({ email: true, register: true })).toEqual([
      LOGIN_PAGE.verifyCode,
      LOGIN_PAGE.register
    ]);
  });
});
