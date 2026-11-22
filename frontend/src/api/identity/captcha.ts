import { BaseApi } from "@/api/base";

/** 人机校验场景，与后端 `captcha/const.py` 的 scene 一致 */
export type CaptchaScene =
  "login" | "register" | "reset" | "bind_email" | "bind_phone" | "invite";

export type CaptchaType =
  "image" | "slide" | "rotate" | "click" | "pow" | "wordorder" | "icon";

export type PowPayload = {
  algorithm: string;
  challenge: string;
  difficulty_bits: number;
  ttl: number;
};

/** `POST /api/identity/auth/captcha/challenge` 的 data；字段随题型出现 */
export type CaptchaChallenge = {
  challenge_id: string;
  type: CaptchaType;
  ttl: number;
  /** 校验签名会话密钥；服务端关闭签名时为空 */
  ck?: string;
  /** 服务端时间（秒），校验签名用它作 gen_time */
  ts?: number;
  background?: string;
  piece?: string;
  width?: number;
  height?: number;
  piece_size?: number;
  /** 图片题答案长度 */
  length?: number;
  /** 纯 PoW 题，或图片题附带的 PoW */
  pow?: PowPayload;
};

export type CaptchaChallengeResult = {
  code: number;
  detail?: string;
  data: CaptchaChallenge;
};

export type CaptchaVerifyResult = {
  code: number;
  detail?: string;
  data: { passed: boolean; ticket?: string; expires_in?: number };
};

export type CaptchaChallengeRequest = {
  scene: CaptchaScene;
  action: string;
  type?: CaptchaType;
  env: Record<string, unknown>;
};

export type CaptchaVerifyRequest = {
  challenge_id: string;
  type: CaptchaType;
  scene: CaptchaScene;
  action: string;
  answer: unknown;
  track?: { x: number; y: number; t: number }[];
  input?: "pointer" | "keyboard";
  gen_time?: number;
  nonce?: string;
  sign?: string;
  env: Record<string, unknown>;
};

/** 交互式人机校验：出题 → 作答换取一次性 ticket，业务请求携带 `captcha_ticket` */
class CaptchaApi extends BaseApi {
  challenge = (data: CaptchaChallengeRequest) => {
    return this.request<CaptchaChallengeResult>(
      "post",
      {},
      data,
      `${this.baseApi}/challenge`
    );
  };

  verify = (data: CaptchaVerifyRequest) => {
    return this.request<CaptchaVerifyResult>(
      "post",
      {},
      data,
      `${this.baseApi}/verify`
    );
  };
}

export const captchaApi = new CaptchaApi("/api/identity/auth/captcha");
