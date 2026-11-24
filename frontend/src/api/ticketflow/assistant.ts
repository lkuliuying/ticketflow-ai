import { http } from "@/utils/http";
import { BaseApi } from "@/api/base";
import type { DetailResult, ListResult } from "@/api/types";

/**
 * 员工 AI 知识问答（DRF `/api/assistant/...`）。会话、消息和反馈存在 DRF；
 * 流式生成与转人工草稿走 FastAPI，见 `assistantStream.ts`。
 */

export type AssistantSession = {
  pk: string;
  title: string;
  /** 转人工后关联的工单；未转人工为 null */
  ticket_id: string | null;
  created_time: string;
  updated_time: string;
};

export type AssistantReference = { article_id: string; title: string };

export const FEEDBACK_REASONS = [
  "INACCURATE",
  "UNRESOLVED",
  "IRRELEVANT",
  "OTHER"
] as const;
export type FeedbackReason = (typeof FEEDBACK_REASONS)[number];
export type FeedbackVote = "up" | "down";

export type AssistantFeedback = {
  vote: FeedbackVote;
  reason: FeedbackReason | null;
  comment: string;
  created_time: string;
  updated_time: string;
};

export type FeedbackPayload = {
  vote: FeedbackVote;
  reason?: FeedbackReason | null;
  comment?: string;
};

export type AnswerStatus = "complete" | "interrupted" | "failed";

/** 工单只读对话里的消息不带 feedback */
export type AssistantMessage = {
  pk: string;
  role: "user" | "assistant";
  content: string;
  references: AssistantReference[];
  status: AnswerStatus;
  /** 回答对应的问题；问题本身为 null */
  user_message_id: string | null;
  feedback?: AssistantFeedback | null;
  created_time: string;
};

type Page = { page?: number; size?: number };

class AssistantSessionApi extends BaseApi {
  rename = (pk: string, title: string) =>
    this.request<DetailResult<AssistantSession>>(
      "patch",
      {},
      { title },
      `${this.baseApi}/${pk}`
    );

  /** 成功时 DRF 返回 204 空响应：只要请求未抛错即视为删除成功 */
  remove = (pk: string) =>
    this.request<unknown>("delete", {}, undefined, `${this.baseApi}/${pk}`);

  messages = (pk: string, params?: Page) =>
    this.request<ListResult<AssistantMessage>>(
      "get",
      params ?? {},
      undefined,
      `${this.baseApi}/${pk}/messages`
    );

  feedback = (pk: string, messageId: string, data: FeedbackPayload) =>
    this.request<DetailResult<AssistantFeedback>>(
      "put",
      {},
      data,
      `${this.baseApi}/${pk}/messages/${encodeURIComponent(messageId)}/feedback`
    );
}

/** 本人会话：列表按更新时间倒序，消息按创建时间正序 */
export const assistantSessionApi = new AssistantSessionApi(
  "/api/assistant/sessions"
);

export type TicketAssistantSession = {
  session: AssistantSession;
  messages: { total: number; results: AssistantMessage[] };
};

/** 工单关联的 AI 对话（只读，提交人、当前处理人和管理员可见） */
export const ticketAssistantSession = (ticketId: string, params?: Page) =>
  http.request<DetailResult<TicketAssistantSession>>(
    "get",
    `/api/tickets/${ticketId}/assistant-session`,
    { params: params ?? {} }
  );

/** 管理员视角的会话：带提问人和工单号 */
export type FeedbackSession = AssistantSession & {
  user_id: number;
  username: string;
  ticket_number: string | null;
};

export type DownvoteRow = {
  session: FeedbackSession;
  question: AssistantMessage;
  answer: AssistantMessage;
};

export type AssistantFeedbackSummary = {
  sessions: number;
  questions: number;
  up: number;
  down: number;
  handoffs: number;
};

export type FeedbackRange = { created_from?: string; created_to?: string };

const FEEDBACK_BASE = "/api/assistant/feedback";

/** 管理员 AI 反馈页：只能看点踩回答和转人工会话，其余只有统计 */
export const assistantFeedbackApi = {
  downvotes: (params?: Page & FeedbackRange) =>
    http.request<ListResult<DownvoteRow>>("get", `${FEEDBACK_BASE}/downvotes`, {
      params: params ?? {}
    }),
  handoffs: (params?: Page & FeedbackRange) =>
    http.request<ListResult<FeedbackSession>>(
      "get",
      `${FEEDBACK_BASE}/handoffs`,
      { params: params ?? {} }
    ),
  summary: (params?: FeedbackRange) =>
    http.request<DetailResult<AssistantFeedbackSummary>>(
      "get",
      `${FEEDBACK_BASE}/summary`,
      { params: params ?? {} }
    )
};
