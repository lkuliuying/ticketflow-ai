import { ref, shallowRef } from "vue";
import type { CaptchaChallenge } from "@/api/identity/captcha";
import type { VerifyExtra } from "@/utils/captcha/flow";
import { solvePow } from "@/utils/captcha/protocol";
import {
  fetchChallenge,
  HumanCheckCancelled,
  isAbort,
  MAX_FAILURES,
  verifyAnswer,
  type HumanCheckOptions
} from "./humanCheckSteps";

export { HumanCheckCancelled, type HumanCheckOptions };

/**
 * 出题 → 作答 → 换取一次性 ticket。PoW 题不弹窗，后台算完直接校验；
 * 图片题附带的 PoW 在用户输入期间并行计算；答错自动换题，连续答错达上限才放弃。
 * 每一轮挑战有自己的 AbortController：关闭弹窗、换题都会让在途的出题、PoW 与校验结果作废。
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
  let failures = 0;

  function settle(ticket: string | null, error?: Error) {
    controller?.abort();
    controller = null;
    visible.value = false;
    loading.value = false;
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
    loading.value = true;
    try {
      const next = await fetchChallenge(options, fallback);
      if (controller !== own) return;
      challenge.value = next;
      const pow = next.pow;
      powTask = pow
        ? solvePow(pow.challenge, pow.difficulty_bits, { signal: own.signal })
        : null;
      powTask?.catch(() => undefined);
      if (next.type === "pow") await submit({ nonce: await powTask });
      else visible.value = true;
    } catch (error) {
      if (controller !== own || isAbort(error)) return;
      settle(null, error instanceof Error ? error : new Error(String(error)));
    } finally {
      if (controller === own) loading.value = false;
    }
  }

  async function submit(answer: unknown, extra: VerifyExtra = {}) {
    const current = challenge.value;
    const own = controller;
    if (!current || !pending || !own) return;
    loading.value = true;
    let ticket: string | null = null;
    try {
      ticket = await verifyAnswer(current, options, answer, extra, powTask);
    } catch (error) {
      if (!isAbort(error)) throw error;
    } finally {
      if (controller === own) loading.value = false;
    }
    // 弹窗已关闭或用户已换题：这一轮的结果作废
    if (!pending || controller !== own) return;
    if (ticket) return settle(ticket);
    failures += 1;
    if (failures >= MAX_FAILURES) {
      return settle(null, new Error(options.failedMessage()));
    }
    // 失败的挑战已在服务端作废，直接换一题
    await load(current.type === "image");
  }

  /** 取得一张一次性 ticket；用户关闭弹窗时以 HumanCheckCancelled 拒绝 */
  function obtain(): Promise<string> {
    settle(null);
    failures = 0;
    return new Promise<string>((resolve, reject) => {
      pending = { resolve, reject };
      void load();
    });
  }

  /** 用户主动换题，不计入失败次数；加载或校验中忽略 */
  function refresh() {
    if (loading.value || !pending) return;
    void load(challenge.value?.type === "image");
  }

  return {
    visible,
    loading,
    challenge,
    obtain,
    submit,
    refresh,
    cancel: () => settle(null)
  };
}
