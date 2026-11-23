import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({
  requestMock: vi.fn()
}));

vi.mock("@/utils/http", () => ({
  http: { request: requestMock }
}));

import { loginAuthApi, toAuthInfo } from "./auth";

/**
 * 登录页能力探测：后端按登录方式分组返回能力清单，登录页仍按平铺字段消费，
 * 这里守护端点路径与字段折算，避免能力开关丢失导致登录表单不渲染或跳过加密。
 */
describe("登录页能力探测", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("请求能力清单端点并折算为平铺结构", async () => {
    requestMock.mockResolvedValue({
      code: 1000,
      detail: "ok",
      data: {
        access: true,
        lifetime: 15,
        basic: {
          enabled: true,
          captcha: true,
          captcha_types: ["slide", "image"],
          token: false,
          encrypted: true
        },
        code: { enabled: true, email: true, sms: false },
        register: { enabled: false },
        reset: { enabled: true }
      }
    });

    const res = await loginAuthApi();

    expect(requestMock.mock.calls[0][0]).toBe("get");
    expect(requestMock.mock.calls[0][1]).toBe(
      "/api/identity/auth/capabilities"
    );
    expect(res.data).toEqual({
      access: true,
      lifetime: 15,
      basic: true,
      captcha: true,
      captcha_types: ["slide", "image"],
      token: false,
      encrypted: true,
      reset: true,
      register: false,
      email: true,
      sms: false
    });
  });

  it("验证码登录总开关关闭时，邮箱与短信入口一并关闭", () => {
    expect(
      toAuthInfo({ code: { enabled: false, email: true, sms: true } })
    ).toMatchObject({ email: false, sms: false });
  });

  it("缺失字段一律视为关闭", () => {
    expect(toAuthInfo(undefined)).toMatchObject({
      access: false,
      basic: false,
      captcha: false,
      encrypted: false
    });
  });

  it("后端开放自助注册时映射为 register: true", () => {
    expect(toAuthInfo({ register: { enabled: true } }).register).toBe(true);
    expect(toAuthInfo({ register: { enabled: false } }).register).toBe(false);
  });
});
