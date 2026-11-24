import { BaseApi } from "@/api/base";
import type { DetailResult } from "@/api/types";

/** 处理人评价标签（固定词表，显示名走词条 ticketflow.rating.tagValue.*） */
export const RATING_TAGS = [
  "FAST",
  "PROFESSIONAL",
  "FRIENDLY",
  "CLEAR"
] as const;
export type RatingTag = (typeof RATING_TAGS)[number];

export type TicketRating = {
  pk: string;
  ticket_id: string;
  ticket_number: string;
  rater_id: number;
  rater_name: string;
  /** 关闭时的处理人；工单关闭时没有处理人则为空 */
  handler_id: number | null;
  handler_name: string | null;
  resolved: boolean;
  satisfaction: number;
  handler_score: number;
  tags: RatingTag[];
  comment: string;
  created_time: string;
};

export type RatingPayload = {
  resolved: boolean;
  satisfaction: number;
  handler_score: number;
  tags: RatingTag[];
  comment: string;
};

/** 汇总口径：平均分保留两位小数，解决率为 0~1 比例；无评价时平均分与解决率为 null */
export type RatingStats = {
  count: number;
  avg_satisfaction: number | null;
  avg_handler_score: number | null;
  resolved_rate: number | null;
  tags: Partial<Record<RatingTag, number>>;
};

export type HandlerRatingStats = RatingStats & {
  handler_id: number | null;
  handler_name: string | null;
};

/** 技术员只返回本人汇总；管理员另含 by_handler 明细 */
export type RatingSummary = RatingStats & { by_handler?: HandlerRatingStats[] };

export type RatingSummaryParams = {
  created_from?: string;
  created_to?: string;
};

class TicketRatingApi extends BaseApi {
  summary = (params?: RatingSummaryParams) => {
    return this.request<DetailResult<RatingSummary>>(
      "get",
      params ?? {},
      undefined,
      `${this.baseApi}/summary`
    );
  };
}

/** 评价列表：员工看自己给出的、技术员看收到的、管理员看全部（范围由后端限定） */
export const ratingApi = new TicketRatingApi("/api/ticket-ratings");
