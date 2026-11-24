<script lang="ts" setup>
import { reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import { passwordRulesCheck } from "@/utils";
import { generateRandomPassword } from "@/utils/randomPassword";
import type { PasswordRule } from "@/api/auth";

/**
 * 重置业务账号密码：输入或按安全策略生成新密码。
 * 只负责收集与校验，加密与提交由打开它的弹窗完成。
 * 手写原因：提交目标是重置密码动作而非模型字段，无对应元数据面。
 */
defineOptions({ name: "TicketFlowPasswordForm" });

const props = defineProps<{
  username: string;
  passwordRules: PasswordRule[];
}>();

const { t } = useI18n();
const formRef = ref<FormInstance>();
const form = reactive({ password: "" });

const rules: FormRules = {
  password: [
    { required: true, message: t("ticketflow.account.passwordRequired") },
    {
      validator: (_rule, value: string, callback) => {
        const { result, msg } = passwordRulesCheck(
          value,
          props.passwordRules,
          t
        );
        return result ? callback() : callback(new Error(msg));
      }
    }
  ]
};

function generatePassword() {
  form.password = generateRandomPassword(props.passwordRules);
  void formRef.value?.validateField("password").catch(() => undefined);
}

async function getPassword(): Promise<string | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  return valid ? form.password : null;
}

defineExpose({ getPassword, form, generatePassword });
</script>

<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
    <p class="mt-0 text-sm text-fg-muted">
      {{ t("ticketflow.account.resetHint", { username }) }}
    </p>
    <el-form-item :label="t('ticketflow.account.newPassword')" prop="password">
      <div class="flex w-full gap-2">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password"
          class="flex-1"
        />
        <el-button @click="generatePassword">
          {{ t("ticketflow.account.generatePassword") }}
        </el-button>
      </div>
    </el-form-item>
  </el-form>
</template>
