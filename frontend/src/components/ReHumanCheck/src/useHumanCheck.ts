import { ref, shallowRef } from "vue";
import type { CaptchaChallenge } from "@/api/identity/captcha";
import type { VerifyExtra } from "@/utils/captcha/flow";
import { solvePow } from "@/utils/captcha/protocol";
import {
  fetchChallenge,
  HumanCheckCancelled,
  MAX_ROUNDS,
  verifyAnswer,
  type HumanCheckOptions
} from "./humanCheckSteps";

export { HumanCheckCancelled, type HumanCheckOptions };

/**
 * 出题 → 作答 → 换取一次性 ticket。PoW 题不弹窗，后台算完直接校验；
 * 图片题附带的 PoW 在用户输入期间并行计算；校验失败自动换题。
 */
export function useHumanCheck(options: HumanCheckOptions) {
  const visible = ref(false);
  const loading = ref(false);
  const challenge = shallowRef<CaptchaChallenge | null>(null);
  let pending: {
    resolve: (v: string) => void;
    reject: (e: Error) => void;
  } | null = null;
  let controller: AbortController | null = null;
  let powTask: Promise<number> | null = null;
  let rounds = 0;

  function settle(ticket: string | null, error?: Error) {
    controller?.abort();
    visible.value = false;
    challenge.value = null;
    const current = pending;
    pending = null;
    if (ticket) current?.resolve(ticket);
    else current?.reject(error ?? new HumanCheckCancelled());
  }

  async function load(fallback = false): Promise<void> {
    controller?.abort();
    const own = new AbortController();
    controller = own;
    rounds += 1;
    if (rounds > MAX_ROUNDS) return settle(null, new Error("too many rounds"));
    loading.value = true;
    try {
      const next = await fetchChallenge(options, fallback);
      if (own.signal.aborted) return;
      challenge.value = next;
      const pow = next.pow;
      powTask = pow
        ? solvePow(pow.challenge, pow.difficulty_bits, { signal: own.signal })
        : null;
      powTask?.catch(() => undefined);
      if (next.type === "pow") await submit({ nonce: await powTask });
      else visible.value = true;
    } catch (error) {
      if (own.signal.aborted || (error as Error)?.name === "AbortError") return;
      settle(null, error instanceof Error ? error : new Error(String(error)));
    } finally {
      if (controller === own) loading.value = false;
    }
  }

  async function submit(answer: unknown, extra: VerifyExtra = {}) {
    const current = challenge.value;
    if (!current || !pending) return;
    loading.value = true;
    const ticket = await verifyAnswer(current, options, answer, extra, powTask);
    // 失败的挑战已在服务端作废，直接换一题
    if (ticket) settle(ticket);
    else await load(current.type === "image");
  }

  /** 取得一张一次性 ticket；用户关闭弹窗时以 HumanCheckCancelled 拒绝 */
  function obtain(): Promise<string> {
    settle(null);
    rounds = 0;
    return new Promise<string>((resolve, reject) => {
      pending = { resolve, reject };
      void load();
    });
  }

  return {
    visible,
    loading,
    challenge,
    obtain,
    submit,
    refresh: () => load(challenge.value?.type === "image"),
    cancel: () => settle(null)
  };
}
