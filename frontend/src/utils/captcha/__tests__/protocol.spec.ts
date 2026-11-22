import { describe, expect, it } from "vitest";
import { SHA256 } from "crypto-es";
import type { CaptchaChallenge } from "@/api/identity/captcha";
import {
  answerDigest,
  carriesCaptchaTicket,
  createTrackRecorder,
  leadingZeroBits,
  signVerify,
  solvePow
} from "../protocol";
import { buildVerifyRequest, isSupportedType, preferredType } from "../flow";

// 期望值由后端 captcha/tickets.py 的 answer_digest / compute_verify_sign 原样计算
describe("captcha protocol matches the server", () => {
  it("digests answers as compact JSON in submission order", () => {
    expect(answerDigest({ code: "Ab3d", pow_answer: { nonce: 1234 } })).toBe(
      "37bc8d401b849742a4e40eda72045256c17be10996985668af3edbb9c7d87dd3"
    );
    expect(answerDigest({ x: 128 })).toBe(
      "a3c47be2c70aa9137d886adfc29eb556c8f90a8bec2cb2f690d9d773c6937dc7"
    );
  });

  it("signs verify requests with HMAC over the canonical string", () => {
    const digest = answerDigest({ x: 128 });
    expect(
      signVerify("ck-secret", "c0ffee", "slide", "login", digest, 1795300000)
    ).toBe("c9604c3c2328995183d17e206d85e85fc1ab8ae28c018787dca3317c83d4ba4c");
  });

  it("counts leading zero bits like the PoW backend", () => {
    expect(leadingZeroBits("0f")).toBe(4);
    expect(leadingZeroBits("00ff")).toBe(8);
    expect(leadingZeroBits("8a")).toBe(0);
    expect(leadingZeroBits("1")).toBe(3);
    expect(leadingZeroBits("0000")).toBe(16);
  });

  it("solves PoW with the first qualifying nonce", async () => {
    const nonce = await solvePow("abcdef0123456789", 8, { batch: 64 });
    expect(nonce).toBe(235);
    expect(
      leadingZeroBits(SHA256(`abcdef0123456789${nonce}`).toString())
    ).toBeGreaterThanOrEqual(8);
  });

  it("stops solving when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      solvePow("x", 30, { batch: 1, signal: controller.signal })
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("captcha request helpers", () => {
  const challenge: CaptchaChallenge = {
    challenge_id: "c0ffee",
    type: "slide",
    ttl: 120,
    ck: "ck-secret",
    ts: 1795300000
  };

  it("signs with the server time and a fresh nonce when ck is present", () => {
    const track = [
      { x: 0, y: 5, t: 0 },
      { x: 128, y: 6, t: 400 }
    ];
    const request = buildVerifyRequest(
      challenge,
      "login",
      "a",
      { x: 128 },
      {
        track
      }
    );
    expect(request.gen_time).toBe(1795300000);
    expect(request.sign).toBe(
      "c9604c3c2328995183d17e206d85e85fc1ab8ae28c018787dca3317c83d4ba4c"
    );
    expect(request.nonce).toMatch(/^[0-9a-f]{32}$/);
    expect(request.track).toEqual(track);
    expect(request.env).toHaveProperty("fp");
    const again = buildVerifyRequest(challenge, "login", "a", { x: 128 });
    expect(again.nonce).not.toBe(request.nonce);
  });

  it("omits the signature when the server does not issue ck", () => {
    const request = buildVerifyRequest(
      { ...challenge, ck: undefined },
      "login",
      "a",
      { x: 1 }
    );
    expect(request).not.toHaveProperty("sign");
    expect(request).not.toHaveProperty("nonce");
  });

  it("prefers the slider, falls back to the image only when asked", () => {
    expect(preferredType(["slide", "rotate", "image"])).toBe("slide");
    expect(preferredType(["rotate", "image"])).toBe("image");
    expect(preferredType(["rotate", "click"])).toBeUndefined();
    expect(preferredType(["slide", "image"], true)).toBe("image");
    expect(preferredType(["slide"], true)).toBeUndefined();
    expect(isSupportedType("pow")).toBe(true);
    expect(isSupportedType("wordorder")).toBe(false);
  });

  it("detects ticket-bearing request bodies", () => {
    expect(carriesCaptchaTicket({ captcha_ticket: "t" })).toBe(true);
    expect(carriesCaptchaTicket({ captcha_ticket: "" })).toBe(false);
    expect(carriesCaptchaTicket(undefined)).toBe(false);
    const form = new FormData();
    form.append("captcha_ticket", "t");
    expect(carriesCaptchaTicket(form)).toBe(false);
  });

  it("records a monotonic drag track relative to its start", () => {
    let now = 1000;
    const recorder = createTrackRecorder(() => now);
    recorder.begin(0, 10.4);
    now = 1000; // 同一毫秒的重复采样丢弃
    recorder.move(3, 10);
    now = 1120;
    recorder.move(40.6, 12);
    now = 1300;
    recorder.move(90, 11);
    expect(recorder.points()).toEqual([
      { x: 0, y: 10, t: 0 },
      { x: 41, y: 12, t: 120 },
      { x: 90, y: 11, t: 300 }
    ]);
  });
});
