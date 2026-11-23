import { h } from "vue";
import { useI18n } from "vue-i18n";
import { ElTag } from "element-plus";
import {
  formatPageColumns,
  type PageTableColumn
} from "@/components/RePlusPage";
import type { AccountRole, BusinessAccount } from "@/api/ticketflow/accounts";

export const ROLE_TONE: Record<AccountRole, "info" | "primary" | "danger"> = {
  requester: "info",
  agent: "primary",
  admin: "danger"
};

/** 账号列表列渲染：角色与启用状态显示为标签 */
export function useAccountColumns() {
  const { t } = useI18n();
  return (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      role: column => {
        column["cellRenderer"] = ({ row }) => {
          const role = (row as BusinessAccount).role;
          return h(ElTag, { size: "small", type: ROLE_TONE[role] }, () =>
            t(`ticketflow.account.roleValue.${role}`)
          );
        };
      },
      is_active: column => {
        column["cellRenderer"] = ({ row }) => {
          const active = (row as BusinessAccount).is_active;
          return h(
            ElTag,
            { size: "small", type: active ? "success" : "info" },
            () =>
              active
                ? t("ticketflow.account.active")
                : t("ticketflow.account.inactive")
          );
        };
      }
    });
}
