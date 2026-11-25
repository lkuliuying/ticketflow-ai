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

  async function ensure(url: string | null | undefined) {
    if (!url || urls[url] || inflight.has(url)) return;
    inflight.add(url);
    try {
      const token = getToken();
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok || disposed) return;
      const blob = await res.blob();
      if (disposed) return;
      urls[url] = URL.createObjectURL(blob);
    } catch {
      // 网络异常时保持空，界面展示占位或重试
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
