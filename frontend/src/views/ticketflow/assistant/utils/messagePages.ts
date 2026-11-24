import type { AssistantMessage } from "@/api/ticketflow/assistant";
import type { ChatState } from "@/api/ticketflow/assistantStream";

const PAGE_SIZE = 100;
/** 单个会话最多取回的页数，防止异常数据导致无限翻页 */
const MAX_PAGES = 10;
/** 本地补位消息的主键前缀：没有服务端主键，不能评价 */
export const LOCAL_PREFIX = "local-";

type Page = { total?: number; results: AssistantMessage[] };

/**
 * 逐页取回会话消息。第一页就失败时返回 null，由调用方保留现有内容；
 * 后续页失败或返回空页时停止翻页，返回已取到的部分。
 */
export async function fetchAllMessages(
  fetchPage: (page: number, size: number) => Promise<Page | null>,
  isStale: () => boolean = () => false
): Promise<AssistantMessage[] | null> {
  const rows: AssistantMessage[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const data = await fetchPage(page, PAGE_SIZE).catch(() => null);
    if (isStale()) return null;
    if (!data) return page === 1 ? null : rows;
    rows.push(...data.results);
    if (data.results.length === 0 || rows.length >= (data.total ?? 0)) break;
  }
  return rows;
}

/** 停止或断线时，服务端写回可能晚于刷新：用流里已收到的内容补一条未完成的回答 */
export function localAnswer(
  state: ChatState,
  questionId: string
): AssistantMessage {
  return {
    pk: `${LOCAL_PREFIX}${questionId}`,
    role: "assistant",
    content: state.text,
    references: state.references,
    status: state.status === "error" ? "failed" : "interrupted",
    user_message_id: questionId,
    feedback: null,
    created_time: new Date().toISOString()
  };
}
