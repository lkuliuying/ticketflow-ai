import { BaseApi } from "@/api/base";
import { isSuccess } from "@/api/types";
import type { DetailResult, ListResult } from "@/api/types";
import type { RatingPayload, TicketRating } from "./ratings";

export type TicketStatus =
  "OPEN" | "IN_PROGRESS" | "PENDING_VERIFY" | "CLOSED" | "REOPENED";
export type TicketPriority = "P0" | "P1" | "P2" | "P3";
export type TicketSlaState = "ON_TRACK" | "DUE_SOON" | "OVERDUE" | "MET";
export type CommentVisibility = "PUBLIC" | "INTERNAL";

export type TicketItem = {
  pk: string;
  number: string;
  title: string;
  description: string;
  category: string;
  priority: TicketPriority;
  status: TicketStatus;
  submitter_id: number;
  submitter_name: string;
  assignee_id: number | null;
  assignee_name: string | null;
  department_id: string;
  department_name: string;
  sla_due_at: string;
  sla_state: TicketSlaState;
  first_response_at: string | null;
  resolved_at: string | null;
  ai_summary: string;
  ai_tags: string[];
  version: number;
  created_time: string;
  updated_time: string;
};

export type TimelineEntry = {
  id: string;
  created_time: string;
  kind: "log" | "comment";
  actor: string;
  body: string;
  action: string;
  from_status: TicketStatus | null;
  to_status: TicketStatus | null;
  visibility: CommentVisibility | "";
};

/** 当前调用者对该工单的能力，前端据此显示操作，不自行推断权限 */
export type TicketViewer = {
  can_handle: boolean;
  /** 可处理且有指派权限，已关闭的工单为 false */
  can_assign: boolean;
  /** 可发对外回复：处理人或提交人，且有评论权限 */
  can_reply: boolean;
  can_comment_internal: boolean;
  can_archive: boolean;
  /** 当前处理人可退回给管理员重新分配 */
  can_return: boolean;
  /** 技术员查看曾经处理、已转交他人的工单：只读，不显示任何操作 */
  read_only: boolean;
  /** 提交人可评价：工单已关闭且尚未评价 */
  can_rate?: boolean;
};

/** 指派维度：管理员看待分配，技术员看当前处理与历史处理 */
export type TicketAssignmentScope = "unassigned" | "current" | "history";

export type TicketDetail = TicketItem & {
  viewer: TicketViewer;
  /** 评价人、被评处理人与管理员可见，其他人或未评价时为 null */
  rating?: TicketRating | null;
  available_transitions: TicketStatus[];
  timeline: { total: number; results: TimelineEntry[] };
};

export type TicketCreatePayload = {
  title: string;
  description: string;
  category: string;
  priority: TicketPriority;
};

export type TicketDashboard = {
  status: Partial<Record<TicketStatus, number>>;
  priority: Partial<Record<TicketPriority, number>>;
  sla: Record<TicketSlaState, number>;
  /** 按身份只返回有意义的键：管理员 unassigned，技术员 current / history，员工为空对象 */
  assignment?: Partial<Record<TicketAssignmentScope, number>>;
};

export type TicketAssignee = {
  pk: number;
  username: string;
  nickname: string;
  department_name: string | null;
};

export type TicketComment = {
  id: string;
  body: string;
  visibility: CommentVisibility;
  author_id: number;
  created_time: string;
};

/** 服务端幂等记录保留 24 小时，客户端提前一小时放弃旧键 */
const PENDING_KEY_TTL_MS = 23 * 60 * 60 * 1000;

function newIdempotencyKey(): string {
  if (typeof crypto === "undefined") {
    return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  }
  if (typeof crypto.randomUUID === "function")
    return crypto.randomUUID().replace(/-/g, "");
  // 非安全上下文没有 randomUUID，仍可用 getRandomValues 取 128 位随机数
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte =>
    byte.toString(16).padStart(2, "0")
  ).join("");
}

/** 按字段名排序后的载荷指纹：同一份表单重试时取回同一个幂等键 */
function payloadFingerprint(data: object): string {
  const source = data as Record<string, unknown>;
  return JSON.stringify(
    Object.keys(source)
      .sort()
      .map(key => [key, source[key]])
  );
}

class TicketApi extends BaseApi {
  /**
   * 未成功的建单请求按内容保留各自的幂等键。网络中断或超时后再次提交同一份
   * 内容（无论是否重开弹窗），服务端会返回首次创建的工单而不是再建一张；
   * 成功后释放该键，之后内容相同的新提交视为新工单。
   *
   * 键跟随内容而不是弹窗：改过内容的提交是另一张工单，复用旧键只会被服务端
   * 以 409 拒绝。旧键超过服务端保留期后作废。
   */
  private pendingKeys = new Map<string, { key: string; createdAt: number }>();

  idempotencyKeyFor = (data: object, now = Date.now()): string => {
    for (const [fingerprint, entry] of this.pendingKeys) {
      if (now - entry.createdAt > PENDING_KEY_TTL_MS) {
        this.pendingKeys.delete(fingerprint);
      }
    }
    const fingerprint = payloadFingerprint(data);
    let entry = this.pendingKeys.get(fingerprint);
    if (!entry) {
      entry = { key: newIdempotencyKey(), createdAt: now };
      this.pendingKeys.set(fingerprint, entry);
    }
    return entry.key;
  };

  create = <T = TicketItem>(data?: object) => {
    const payload = data ?? {};
    const fingerprint = payloadFingerprint(payload);
    const key = this.idempotencyKeyFor(payload);
    return this.request<DetailResult<T>>("post", {}, payload, undefined, {
      headers: { "Idempotency-Key": key }
    }).then(res => {
      if (isSuccess(res)) this.pendingKeys.delete(fingerprint);
      return res;
    });
  };

  timeline = (pk: string, params?: { page?: number; size?: number }) => {
    return this.request<ListResult<TimelineEntry>>(
      "get",
      params,
      {},
      `${this.baseApi}/${pk}/timeline`
    );
  };

  transition = (
    pk: string,
    data: { target_status: TicketStatus; version: number; note?: string }
  ) => {
    return this.request<DetailResult<TicketItem>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/transition`
    );
  };

  assign = (
    pk: string,
    data: { assignee_id: number | null; version: number }
  ) => {
    return this.request<DetailResult<TicketItem>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/assign`
    );
  };

  /** 指派候选人（仅管理员）：在职技术员，可按技能组筛选；最多 20 条，按用户名与主键排序 */
  assignees = (pk: string, q?: string, departmentId?: string) => {
    const keyword = q?.trim();
    return this.request<DetailResult<TicketAssignee[]>>(
      "get",
      {
        ...(keyword ? { q: keyword } : {}),
        ...(departmentId ? { department_id: departmentId } : {})
      },
      undefined,
      `${this.baseApi}/${pk}/assignees`
    );
  };

  /** 提交人评价已关闭的工单：每张工单一次，重复或未关闭返回 409 */
  rate = (pk: string, data: RatingPayload) => {
    return this.request<DetailResult<TicketRating>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/rating`
    );
  };

  /** 当前处理人退回工单：清空处理人、状态不变，进入管理员的待分配；原因必填（1~500 字） */
  returnTicket = (pk: string, data: { version: number; reason: string }) => {
    return this.request<DetailResult<TicketItem>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/return`
    );
  };

  comments = (
    pk: string,
    data: { body: string; visibility: CommentVisibility }
  ) => {
    return this.request<DetailResult<TicketComment>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/comments`
    );
  };

  aiMetadata = (
    pk: string,
    data: {
      version: number;
      summary: string;
      tags: string[];
      category?: string;
      priority?: TicketPriority;
    }
  ) => {
    return this.request<DetailResult<TicketItem>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/ai-metadata`
    );
  };

  dashboard = (params?: object) => {
    return this.request<DetailResult<TicketDashboard>>(
      "get",
      params,
      {},
      `${this.baseApi}/dashboard`
    );
  };
}

export const ticketApi = new TicketApi("/api/tickets");
