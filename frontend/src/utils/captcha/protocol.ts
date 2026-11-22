import { HmacSHA256, SHA256 } from "crypto-es";

/**
 * 人机校验协议的纯函数部分，与后端 `captcha/tickets.py`、`captcha/backends/pow.py` 同口径：
 * - 答案摘要：紧凑 JSON 的 SHA-256（键序保持提交序，前后端都按原样序列化）；
 * - verify 签名：HMAC-SHA256(ck, "challenge_id|type|scene|digest|gen_time")，gen_time 取挑战下发的服务端 ts；
 * - PoW：SHA-256(challenge + nonce) 的前导零比特数不少于 difficulty_bits。
 */

/** 答案摘要（十六进制） */
export function answerDigest(answer: unknown): string {
  return SHA256(JSON.stringify(answer)).toString();
}

/** verify 请求签名（十六进制） */
export function signVerify(
  ck: string,
  challengeId: string,
  captchaType: string,
  scene: string,
  digest: string,
  genTime: number
): string {
  const canonical = [
    challengeId,
    captchaType,
    scene,
    digest,
    String(Math.trunc(genTime))
  ].join("|");
  return HmacSHA256(canonical, ck).toString();
}

/** 随机十六进制串；nonce 要求 16~128 字符 */
export function randomHex(bytes = 16): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return Array.from(buffer, value => value.toString(16).padStart(2, "0")).join(
    ""
  );
}

/** 十六进制摘要的前导零比特数 */
export function leadingZeroBits(hex: string): number {
  let total = 0;
  for (const char of hex) {
    const value = parseInt(char, 16);
    if (value === 0) {
      total += 4;
      continue;
    }
    total += 4 - value.toString(2).length;
    break;
  }
  return total;
}

export interface PowOptions {
  signal?: AbortSignal;
  /** 每批计算的次数，批与批之间让出主线程 */
  batch?: number;
}

/** 求解 PoW，返回满足难度的整数 nonce；被中止时抛 AbortError */
export async function solvePow(
  challenge: string,
  bits: number,
  options: PowOptions = {}
): Promise<number> {
  const batch = options.batch ?? 4000;
  let nonce = 0;
  for (;;) {
    if (options.signal?.aborted) {
      throw new DOMException("PoW aborted", "AbortError");
    }
    for (let i = 0; i < batch; i += 1, nonce += 1) {
      if (leadingZeroBits(SHA256(`${challenge}${nonce}`).toString()) >= bits) {
        return nonce;
      }
    }
    await new Promise(resolve => setTimeout(resolve, 0));
  }
}

const FP_STORAGE_KEY = "captcha-client-fp";
let memoryFp = "";

/**
 * 客户端指纹：每个浏览器一个随机 ID。挑战时作为 `env.fp` 上送，业务请求以
 * `X-Captcha-Fp` 回传，票据按两者一致性强绑定。只是随机标识，不采集设备特征。
 */
export function clientFingerprint(): string {
  if (memoryFp) return memoryFp;
  try {
    const stored = localStorage.getItem(FP_STORAGE_KEY);
    if (stored && stored.length >= 16 && stored.length <= 128) {
      memoryFp = stored;
      return memoryFp;
    }
  } catch {
    // 隐私模式等禁用存储时退回内存值
  }
  memoryFp = randomHex(16);
  try {
    localStorage.setItem(FP_STORAGE_KEY, memoryFp);
  } catch {
    // 同上
  }
  return memoryFp;
}

/** 请求体是否携带人机校验票据（普通对象，非 FormData） */
export function carriesCaptchaTicket(data: unknown): boolean {
  return (
    typeof data === "object" &&
    data !== null &&
    !(typeof FormData !== "undefined" && data instanceof FormData) &&
    Boolean((data as Record<string, unknown>).captcha_ticket)
  );
}

/** 挑战与校验共用的环境包；字段是后端 CaptchaEnv 的子集 */
export function clientEnv(): Record<string, unknown> {
  const env: Record<string, unknown> = { fp: clientFingerprint() };
  if (typeof navigator !== "undefined" && navigator.language) {
    env.language = navigator.language.slice(0, 64);
  }
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (timezone) env.timezone = timezone.slice(0, 64);
  } catch {
    // 无 Intl 时省略
  }
  return env;
}

export interface TrackPoint {
  x: number;
  y: number;
  t: number;
}

/** 拖动轨迹采样：时间相对起点（毫秒），相邻点至少间隔 1ms，最多保留 200 个点 */
export function createTrackRecorder(
  now: () => number = () => performance.now()
) {
  let start = 0;
  const points: TrackPoint[] = [];
  return {
    begin(x: number, y: number) {
      start = now();
      points.length = 0;
      points.push({ x: Math.round(x), y: Math.round(y), t: 0 });
    },
    move(x: number, y: number) {
      if (!points.length) return;
      const t = Math.round(now() - start);
      const last = points[points.length - 1];
      if (t <= last.t) return;
      if (points.length >= 200) points.splice(1, 1);
      points.push({ x: Math.round(x), y: Math.round(y), t });
    },
    points(): TrackPoint[] {
      return points.map(point => ({ ...point }));
    }
  };
}
