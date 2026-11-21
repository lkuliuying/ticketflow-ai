import type { ArticleStatus } from "@/api/ticketflow/knowledge";

export const ARTICLE_STATUS_TONE: Record<
  ArticleStatus,
  "info" | "success" | "warning"
> = {
  DRAFT: "info",
  PUBLISHED: "success",
  ARCHIVED: "warning"
};

/**
 * 知识维护人员可做的状态变更：草稿发布、已发布归档、已归档重新发布，
 * 已发布与已归档也可退回草稿继续修改。
 */
export function nextStatuses(status: ArticleStatus): ArticleStatus[] {
  if (status === "DRAFT") return ["PUBLISHED"];
  if (status === "PUBLISHED") return ["ARCHIVED", "DRAFT"];
  return ["PUBLISHED", "DRAFT"];
}
