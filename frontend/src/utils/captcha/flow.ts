import type {
  CaptchaChallenge,
  CaptchaScene,
  CaptchaType,
  CaptchaVerifyRequest
} from "@/api/identity/captcha";
import {
  answerDigest,
  clientEnv,
  randomHex,
  signVerify,
  type TrackPoint
} from "./protocol";

/** 前端已实现的题型：静默 PoW、图片字符、滑动拼图 */
export const SUPPORTED_TYPES: readonly CaptchaType[] = [
  "pow",
  "image",
  "slide"
];

export function isSupportedType(type: string | undefined): boolean {
  return SUPPORTED_TYPES.includes(type as CaptchaType);
}

/**
 * 向服务端声明的题型偏好。服务端在低风险档位恒出 PoW、高风险档位强制难题型，
 * 只有中间档位才尊重这里的请求；图片题只有显式请求时才会出现（无障碍回退）。
 */
export function preferredType(
  enabled: readonly string[] | undefined,
  fallback = false
): CaptchaType | undefined {
  const types = enabled ?? [];
  if (fallback) return types.includes("image") ? "image" : undefined;
  if (types.includes("slide")) return "slide";
  if (types.includes("image")) return "image";
  return undefined;
}

export interface VerifyExtra {
  track?: TrackPoint[];
  input?: "pointer" | "keyboard";
}

/** 组装 verify 请求；挑战带 `ck` 时按服务端时间加签并附一次性 nonce */
export function buildVerifyRequest(
  challenge: CaptchaChallenge,
  scene: CaptchaScene,
  action: string,
  answer: unknown,
  extra: VerifyExtra = {}
): CaptchaVerifyRequest {
  const request: CaptchaVerifyRequest = {
    challenge_id: challenge.challenge_id,
    type: challenge.type,
    scene,
    action,
    answer,
    input: extra.input ?? "pointer",
    env: clientEnv()
  };
  if (extra.track?.length) request.track = extra.track;
  if (challenge.ck) {
    const genTime = challenge.ts ?? Math.floor(Date.now() / 1000);
    request.gen_time = genTime;
    request.nonce = randomHex(16);
    request.sign = signVerify(
      challenge.ck,
      challenge.challenge_id,
      challenge.type,
      scene,
      answerDigest(answer),
      genTime
    );
  }
  return request;
}

/** 后端各入口的人机校验动作常量（`captcha/const.py`） */
export const CAPTCHA_ACTIONS = {
  login: "identity.login.basic",
  inviteAccept: "invite.accept",
  verifyCodeSend: (scene: CaptchaScene) => `auth.verify_code.send:${scene}`
} as const;
