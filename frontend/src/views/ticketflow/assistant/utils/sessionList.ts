import type { AssistantSession } from "@/api/ticketflow/assistant";

/**
 * 合并列表响应：列表请求在途期间本地新建的会话还不在响应里，保留在最前，
 * 避免当前会话被迟到的响应换掉；其余以服务端为准。
 */
export function mergeFetched(
  local: AssistantSession[],
  fetched: AssistantSession[],
  createdWhileLoading: ReadonlySet<string>
): AssistantSession[] {
  const created = local.filter(
    s => createdWhileLoading.has(s.pk) && !fetched.some(f => f.pk === s.pk)
  );
  return [...created, ...fetched];
}
