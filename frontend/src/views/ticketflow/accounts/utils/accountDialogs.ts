import { h, ref } from "vue";
import type { Composer } from "vue-i18n";
import { deviceDetection } from "@pureadmin/utils";
import { ElMessageBox } from "element-plus";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import { AesEncrypted } from "@/utils/aes";
import { i18n } from "@/plugins/i18n";
import type { PasswordRule } from "@/api/auth";
import {
  accountApi,
  type AccountPayload,
  type BusinessAccount,
  type SkillGroup
} from "@/api/ticketflow/accounts";
import AccountForm from "../components/AccountForm.vue";
import PasswordForm from "../components/PasswordForm.vue";

/** 组件外翻译（legacy: false 下 global 为 Composer） */
const t = (key: string, params: Record<string, unknown> = {}) =>
  (i18n.global as Composer).t(key, params);

type AccountFormRef = { getPayload: () => Promise<AccountPayload | null> };
type PasswordFormRef = { getPassword: () => Promise<string | null> };

/**
 * 新建或编辑业务账号。新建时密码按底座约定以目标用户名为密钥加密后提交；
 * 失败（如 403 越权、用户名重复）时保持弹层，错误提示由拦截器给出。
 */
export function openAccountForm(options: {
  initial?: BusinessAccount;
  groups: SkillGroup[];
  passwordRules: PasswordRule[];
  onSaved?: () => void;
}) {
  const formRef = ref<AccountFormRef>();
  const editing = options.initial;
  addDialog({
    title: editing
      ? t("ticketflow.account.editTitle", { username: editing.username })
      : t("ticketflow.account.createTitle"),
    width: deviceDetection() ? "100%" : dialogSize("md"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () =>
      h(AccountForm, {
        ref: formRef,
        initial: editing,
        groups: options.groups,
        passwordRules: options.passwordRules
      }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await formRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      if (payload.password && payload.username) {
        payload.password = await AesEncrypted(
          payload.username,
          payload.password
        );
      }
      const res = await (
        editing
          ? accountApi.partialUpdate<BusinessAccount>(editing.pk, payload)
          : accountApi.create<BusinessAccount>(payload)
      ).catch(() => null);
      closeLoading();
      if (res && isSuccess(res)) {
        message(t("ticketflow.account.saved"), { type: "success" });
        done();
        options.onSaved?.();
      }
    }
  });
}

/** 重置密码：成功后该账号已有会话全部失效 */
export function openResetPassword(
  account: Pick<BusinessAccount, "pk" | "username">,
  passwordRules: PasswordRule[]
) {
  const formRef = ref<PasswordFormRef>();
  addDialog({
    title: t("ticketflow.account.resetTitle", { username: account.username }),
    width: deviceDetection() ? "100%" : dialogSize("sm"),
    draggable: true,
    closeOnClickModal: false,
    sureBtnLoading: true,
    contentRenderer: () =>
      h(PasswordForm, {
        ref: formRef,
        username: account.username,
        passwordRules
      }),
    beforeSure: async (done, { closeLoading }) => {
      const password = await formRef.value?.getPassword();
      if (!password) {
        closeLoading();
        return;
      }
      const res = await accountApi
        .resetPassword(account.pk, {
          password: await AesEncrypted(account.username, password)
        })
        .catch(() => null);
      closeLoading();
      if (res && isSuccess(res)) {
        message(t("ticketflow.account.resetDone"), { type: "success" });
        done();
      }
    }
  });
}

/**
 * 启用 / 停用前确认。停用技术员会把他名下未关闭的工单放回待分配，
 * 停用或改角色后该账号已有会话立即失效。
 */
export async function toggleAccountActive(
  account: BusinessAccount,
  onChanged?: () => void
): Promise<boolean> {
  const enabling = !account.is_active;
  const confirmed = await ElMessageBox.confirm(
    enabling
      ? t("ticketflow.account.enableConfirm", { username: account.username })
      : t(
          account.role === "agent"
            ? "ticketflow.account.disableAgentConfirm"
            : "ticketflow.account.disableConfirm",
          { username: account.username }
        ),
    enabling ? t("ticketflow.account.enable") : t("ticketflow.account.disable"),
    { type: enabling ? "info" : "warning" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed) return false;
  const res = await accountApi
    .setActive(account.pk, enabling)
    .catch(() => null);
  if (!res || !isSuccess(res)) return false;
  message(
    enabling
      ? t("ticketflow.account.enabled")
      : t("ticketflow.account.disabled"),
    { type: "success" }
  );
  onChanged?.();
  return true;
}
