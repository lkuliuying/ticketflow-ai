import { flushPromises } from "@vue/test-utils";
import { SHA256 } from "crypto-es";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { leadingZeroBits } from "@/utils/captcha/protocol";

const mocks = vi.hoisted(() => ({ challenge: vi.fn(), verify: vi.fn() }));
vi.mock("@/api/identity/captcha", () => ({
  captchaApi: { challenge: mocks.challenge, verify: mocks.verify }
}));

import { HumanCheckCancelled, useHumanCheck } from "../src/useHumanCheck";

const ok = <T>(data: T) => ({ code: 1000, data });
const pow = {
  algorithm: "sha256",
  challenge: "pow-seed",
  difficulty_bits: 6,
  ttl: 60
};

function setup(types: string[] = ["slide", "image"]) {
  return useHumanCheck({
    scene: () => "login",
    action: () => "identity.login.basic",
    types: () => types,
    unsupportedMessage: () => "unsupported"
  });
}

beforeEach(() => {
  mocks.challenge.mockReset();
  mocks.verify.mockReset();
});

describe("useHumanCheck", () => {
  it("solves a PoW challenge silently and returns the ticket", async () => {
    mocks.challenge.mockResolvedValue(
      ok({ challenge_id: "c1", type: "pow", ttl: 60, pow })
    );
    mocks.verify.mockResolvedValue(ok({ passed: true, ticket: "T-1" }));
    const check = setup();

    await expect(check.obtain()).resolves.toBe("T-1");
    expect(check.visible.value).toBe(false);
    expect(mocks.challenge.mock.calls[0][0]).toMatchObject({
      scene: "login",
      action: "identity.login.basic",
      type: "slide"
    });
    const { answer } = mocks.verify.mock.calls[0][0];
    const digest = SHA256(`pow-seed${answer.nonce}`).toString();
    expect(leadingZeroBits(digest)).toBeGreaterThanOrEqual(6);
  });

  it("falls back to the image challenge when given an unsupported type", async () => {
    mocks.challenge
      .mockResolvedValueOnce(
        ok({ challenge_id: "c1", type: "wordorder", ttl: 60 })
      )
      .mockResolvedValueOnce(
        ok({ challenge_id: "c2", type: "image", ttl: 60, length: 4, pow })
      );
    mocks.verify.mockResolvedValue(ok({ passed: true, ticket: "T-2" }));
    const check = setup();

    const ticket = check.obtain();
    await flushPromises();
    expect(mocks.challenge.mock.calls[1][0].type).toBe("image");
    expect(check.visible.value).toBe(true);

    await check.submit("ab12", { input: "keyboard" });
    await expect(ticket).resolves.toBe("T-2");
    const request = mocks.verify.mock.calls[0][0];
    expect(request.answer.code).toBe("ab12");
    expect(request.answer.pow_answer.nonce).toEqual(expect.any(Number));
    expect(request.input).toBe("keyboard");
  });

  it("loads a fresh challenge after a failed answer", async () => {
    mocks.challenge
      .mockResolvedValueOnce(ok({ challenge_id: "c1", type: "slide", ttl: 60 }))
      .mockResolvedValueOnce(
        ok({ challenge_id: "c2", type: "slide", ttl: 60 })
      );
    mocks.verify
      .mockRejectedValueOnce({ code: 400, error: "captcha_invalid" })
      .mockResolvedValueOnce(ok({ passed: true, ticket: "T-3" }));
    const check = setup();

    const ticket = check.obtain();
    await flushPromises();
    await check.submit({ x: 10 });
    expect(check.challenge.value?.challenge_id).toBe("c2");
    await check.submit({ x: 12 });
    await expect(ticket).resolves.toBe("T-3");
  });

  it("rejects with HumanCheckCancelled when the dialog is closed", async () => {
    mocks.challenge.mockResolvedValue(
      ok({ challenge_id: "c1", type: "slide", ttl: 60 })
    );
    const check = setup();

    const ticket = check.obtain();
    await flushPromises();
    check.cancel();
    await expect(ticket).rejects.toBeInstanceOf(HumanCheckCancelled);
    expect(check.visible.value).toBe(false);
  });

  it("gives up when the server insists on a type the client cannot render", async () => {
    mocks.challenge.mockResolvedValue(
      ok({ challenge_id: "c1", type: "click", ttl: 60 })
    );
    const check = setup(["click", "rotate"]);

    await expect(check.obtain()).rejects.toThrow("unsupported");
    expect(mocks.verify).not.toHaveBeenCalled();
  });
});
