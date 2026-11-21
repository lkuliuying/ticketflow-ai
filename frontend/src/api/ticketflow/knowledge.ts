import { BaseApi } from "@/api/base";
import type { DetailResult, ListResult } from "@/api/types";

export type ArticleStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";

export type ArticleItem = {
  pk: string;
  title: string;
  category: string;
  tags: string[];
  status: ArticleStatus;
  view_count: number;
  created_time: string;
  updated_time: string;
};

/** 当前调用者对文章的能力，前端据此显示编辑与发布入口 */
export type ArticleViewer = { can_edit: boolean; can_publish: boolean };

export type ArticleDetail = ArticleItem & {
  body_markdown: string;
  /** 仅管理员或文章创建者可见，其他人为 null */
  source_ticket_id: string | null;
  viewer: ArticleViewer;
};

export type ArticlePayload = {
  title: string;
  body_markdown: string;
  category: string;
  tags: string[];
};

/** 列表顶层附带“能否新建不关联工单的文章”，空列表同样返回 */
export type ArticleListResult = ListResult<ArticleItem> & {
  data: ListResult<ArticleItem>["data"] & { can_create_standalone?: boolean };
};

class KnowledgeApi extends BaseApi {
  /** 新建草稿；带 source_ticket_id 时为从已关闭工单转存 */
  createArticle = (
    data: ArticlePayload & { source_ticket_id?: string | null }
  ) => {
    return this.request<DetailResult<ArticleDetail>>("post", {}, data);
  };

  updateArticle = (
    pk: string,
    data: Partial<ArticlePayload> & { status?: ArticleStatus }
  ) => {
    return this.request<DetailResult<ArticleDetail>>(
      "patch",
      {},
      data,
      `${this.baseApi}/${pk}`
    );
  };
}

export const knowledgeApi = new KnowledgeApi("/api/knowledge/articles");
