import { onBeforeUnmount, reactive } from "vue";
import { getToken } from "@/utils/auth";

/**
 * 受鉴权媒体加载器：<img> / <video> 原生请求不携带 Bearer 令牌，
 * 通过 fetch 附带授权头拉取后生成短生命周期 Blob URL，组件卸载时统一释放。
 */
export function useAuthorizedMedia() {
  const urls = reactive<Record<string, string>>({});
  const inflight = new Set<string>();
  let disposed = false;

  /** 拉取并缓存 Blob URL；返回是否可用（重复调用、并发中的请求返回 false 不重复拉取） */
  async function ensure(url: string | null | undefined): Promise<boolean> {
    if (!url) return false;
    if (urls[url]) return true;
    if (inflight.has(url)) return false;
    inflight.add(url);
    try {
      const token = getToken();
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok || disposed) return false;
      const blob = await res.blob();
      if (disposed) return false;
      urls[url] = URL.createObjectURL(blob);
      return true;
    } catch {
      // 网络异常时保持空，界面展示占位或重试
      return false;
    } finally {
      inflight.delete(url);
    }
  }

  onBeforeUnmount(() => {
    disposed = true;
    for (const blobUrl of Object.values(urls)) {
      URL.revokeObjectURL(blobUrl);
    }
  });

  return { urls, ensure };
}
