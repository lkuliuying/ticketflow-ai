import { reactive, shallowRef, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { usePageAuth } from "@/router/utils";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import type { OperationProps } from "@/components/RePlusPage";
import { accountApi, type BusinessAccount } from "@/api/ticketflow/accounts";
import {
  openAccountForm,
  openResetPassword,
  toggleAccountActive
} from "./accountDialogs";
import { useAccountOptions } from "./accountOptions";
import { useAccountColumns } from "./accountColumns";
import EditPen from "~icons/ep/edit-pen";
import Key from "~icons/ep/key";
import SwitchButton from "~icons/ep/switch-button";

type PageRef = Ref<{ handleGetData?: () => void } | undefined>;

/**
 * 业务账号管理。新建与编辑走自有表单（技能组随角色联动），默认的元数据新建、
 * 编辑、删除关闭；行内提供编辑、重置密码、启用 / 停用。
 */
export function useAccounts(tableRef: PageRef) {
  const { t } = useI18n();
  const api = reactive(accountApi);
  const auth = usePageAuth("TicketFlowAccounts", ["resetPassword"]);
  const canCreate = Boolean(auth.create);
  const canUpdate = Boolean(auth.partialUpdate);
  Object.assign(auth, {
    create: false,
    update: false,
    partialUpdate: false,
    destroy: false,
    batchDestroy: false
  });

  const { groups, passwordRules } = useAccountOptions();
  const reload = () => tableRef.value?.handleGetData?.();
  const openForm = (initial?: BusinessAccount) =>
    openAccountForm({
      initial,
      groups: groups.value,
      passwordRules: passwordRules.value,
      onSaved: reload
    });

  const rowButton = (
    code: string,
    type: "primary" | "warning" | "danger",
    icon: typeof EditPen,
    tip: string,
    index: number,
    show: boolean,
    onClick: (row: BusinessAccount) => unknown
  ) => ({
    code,
    props: { type, icon: useRenderIcon(icon), link: true },
    tooltip: { content: t(tip) },
    onClick: ({ row }: { row: unknown }) => onClick(row as BusinessAccount),
    index,
    show
  });

  const operationButtonsProps = shallowRef<OperationProps>({
    hideEdit: true,
    buttons: [
      rowButton(
        "editAccount",
        "primary",
        EditPen,
        "ticketflow.account.edit",
        -10,
        canUpdate,
        openForm
      ),
      rowButton(
        "resetPassword",
        "warning",
        Key,
        "ticketflow.account.resetPassword",
        -9,
        Boolean(auth.resetPassword),
        row => openResetPassword(row, passwordRules.value)
      ),
      rowButton(
        "toggleActive",
        "danger",
        SwitchButton,
        "ticketflow.account.toggleActive",
        -8,
        canUpdate,
        row => toggleAccountActive(row, reload)
      )
    ]
  });

  const tableBarButtonsProps = shallowRef<OperationProps>({
    buttons: [
      {
        text: t("ticketflow.account.create"),
        code: "createAccount",
        props: { type: "primary" },
        onClick: () => openForm(),
        show: canCreate
      }
    ]
  });

  return {
    api,
    auth,
    groups,
    listColumnsFormat: useAccountColumns(),
    operationButtonsProps,
    tableBarButtonsProps
  };
}
