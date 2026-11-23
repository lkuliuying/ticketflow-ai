import { BaseApi } from "@/api/base";
import type { DetailResult } from "@/api/types";

/** 业务角色：普通员工 / 技术员 / 管理员（技术员必须归属技能组） */
export const ACCOUNT_ROLES = ["requester", "agent", "admin"] as const;
export type AccountRole = (typeof ACCOUNT_ROLES)[number];

export type BusinessAccount = {
  pk: number;
  username: string;
  name: string;
  phone: string;
  email: string;
  role: AccountRole;
  skill_group: string | null;
  skill_group_name: string | null;
  is_active: boolean;
};

/** 可写字段；password 只在新建时提交（底座加密约定：以目标用户名为密钥加密） */
export type AccountPayload = {
  username?: string;
  name: string;
  phone: string;
  email: string;
  role: AccountRole;
  skill_group: string | null;
  password?: string;
};

class AccountApi extends BaseApi {
  /** 重置密码：撤销该用户已有会话 */
  resetPassword = (pk: number, data: { password: string }) => {
    return this.request<DetailResult<null>>(
      "post",
      {},
      data,
      `${this.baseApi}/${pk}/reset-password`
    );
  };

  /** 启用 / 停用：停用技术员会把其未关闭工单放回待分配 */
  setActive = (pk: number, isActive: boolean) => {
    return this.request<DetailResult<BusinessAccount>>(
      "patch",
      {},
      { is_active: isActive },
      `${this.baseApi}/${pk}`
    );
  };
}

export const accountApi = new AccountApi("/api/ticketflow/accounts");

export type SkillGroup = {
  pk: string;
  name: string;
  description: string;
  is_active: boolean;
  /** 默认组：未配置路由的分类走这里，不能停用 */
  is_default: boolean;
};

export type CategoryRoute = {
  category: string;
  label: string;
  /** null 表示未配置，走默认组 */
  skill_group: string | null;
  skill_group_name: string | null;
};

class SkillGroupApi extends BaseApi {
  categoryRoutes = () => {
    return this.request<DetailResult<CategoryRoute[]>>(
      "get",
      {},
      undefined,
      `${this.baseApi}/category-routes`
    );
  };

  /** 设置分类路由；传 null 清除配置，后续工单走默认组 */
  updateRoute = (category: string, skillGroup: string | null) => {
    return this.request<DetailResult<CategoryRoute>>(
      "patch",
      {},
      { skill_group: skillGroup },
      `${this.baseApi}/category-routes/${category}`
    );
  };
}

export const skillGroupApi = new SkillGroupApi("/api/ticketflow/skill-groups");
