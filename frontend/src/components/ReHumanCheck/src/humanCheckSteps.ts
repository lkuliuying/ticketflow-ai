import { isSuccess } from "@/api/types";
import {
  captchaApi,
  type CaptchaChallenge,
  type CaptchaScene
} from "@/api/identity/captcha";
import {
  buildVerifyRequest,
  isSupportedType,
  preferredType,
  type VerifyExtra
} from "@/utils/captcha/flow";
import { clientEnv } from "@/utils/captcha/protocol";

/** 用户关闭校验弹窗；调用方据此静默结束提交 */
export class HumanCheckCancelled extends Error {
  constructor() {
    super("human check cancelled");
    this.name = "HumanCheckCancelled";
  }
}

export interface HumanCheckOptions {
  scene: () => CaptchaScene;
  action: () => string;
  /** 服务端启用的题型（能力探测的 `captcha_types`） */
  types: () => readonly string[] | undefined;
  /** 服务端出了前端未实现的题型且无法回退时的提示 */
  unsupportedMessage: () => string;
  /** 连续答错达上限时的提示 */
  failedMessage: () => string;
}

/** 连续答错（含静默 PoW 被拒）的上限；用户主动换题不计入 */
export const MAX_FAILURES = 5;

export function isAbort(error: unknown): boolean {
  return (error as Error | null)?.name === "AbortError";
}

/** 出题；服务端按风险出了前端未实现的题型时，能回退图片题就换一次，否则报错 */
export async function fetchChallenge(
  options: HumanCheckOptions,
  fallback: boolean
): Promise<CaptchaChallenge> {
  const res = await captchaApi.challenge({
    scene: options.scene(),
    action: options.action(),
    type: preferredType(options.types(), fallback),
    env: clientEnv()
  });
  if (!isSuccess(res)) throw new Error(res.detail);
  if (isSupportedType(res.data.type)) return res.data;
  if (!fallback && preferredType(options.types(), true)) {
    return fetchChallenge(options, true);
  }
  throw new Error(options.unsupportedMessage());
}

/**
 * 校验答案，通过时返回 ticket。图片题统一提交 `{code}`，附带 PoW 时再加 `pow_answer`；
 * PoW 被中止时抛 AbortError，由调用方按“本轮作废”处理。
 */
export async function verifyAnswer(
  current: CaptchaChallenge,
  options: HumanCheckOptions,
  answer: unknown,
  extra: VerifyExtra,
  powTask: Promise<number> | null
): Promise<string | null> {
  let payload = answer;
  if (current.type === "image") {
    payload = powTask
      ? { code: answer, pow_answer: { nonce: await powTask } }
      : { code: answer };
  }
  const request = buildVerifyRequest(
    current,
    options.scene(),
    options.action(),
    payload,
    extra
  );
  const res = await captchaApi.verify(request).catch(() => null);
  return res && isSuccess(res) && res.data.passed
    ? (res.data.ticket ?? null)
    : null;
}
