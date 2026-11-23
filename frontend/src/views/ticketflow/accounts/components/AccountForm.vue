<script lang="ts" setup>
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import { passwordRulesCheck } from "@/utils";
import { generateRandomPassword } from "@/utils/randomPassword";
import type { PasswordRule } from "@/api/auth";
import {
  ACCOUNT_ROLES,
  type AccountPayload,
  type AccountRole,
  type BusinessAccount,
  type SkillGroup
} from "@/api/ticketflow/accounts";

/**
 * 业务账号表单：新建时填用户名与初始密码，编辑时只改资料、角色与技能组。
 * 只负责收集与校验，提交（含密码加密）由打开它的弹窗完成。
 * 手写原因：技能组只在选择技术员时出现且必填、初始密码需按安全策略生成与校验，
 * 这种随角色联动的条件字段元数据表单表达不了。
 */
defineOptions({ name: "TicketFlowAccountForm" });

const props = defineProps<{
  initial?: BusinessAccount;
  groups: SkillGroup[];
  passwordRules: PasswordRule[];
}>();

const { t } = useI18n();
const formRef = ref<FormInstance>();
const isCreate = computed(() => !props.initial);
const form = reactive({
  username: props.initial?.username ?? "",
  name: props.initial?.name ?? "",
  phone: props.initial?.phone ?? "",
  email: props.initial?.email ?? "",
  role: (props.initial?.role ?? "requester") as AccountRole,
  skill_group: props.initial?.skill_group ?? null,
  password: ""
});

/** 只列启用的技能组；编辑时保留当前所在组（即使已停用）以便看清现状 */
const groupOptions = computed(() =>
  props.groups.filter(
    group => group.is_active || group.pk === props.initial?.skill_group
  )
);

watch(
  () => form.role,
  role => {
    if (role !== "agent") form.skill_group = null;
  }
);

const rules = computed<FormRules>(() => ({
  username: isCreate.value
    ? [
        {
          required: true,
          whitespace: true,
          message: t("ticketflow.account.usernameRequired")
        },
        {
          pattern: /^[A-Za-z0-9_.@+-]{3,64}$/,
          message: t("ticketflow.account.usernameInvalid")
        }
      ]
    : [],
  name: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.account.nameRequired")
    }
  ],
  email: [{ type: "email", message: t("ticketflow.account.emailInvalid") }],
  role: [{ required: true, message: t("ticketflow.account.roleRequired") }],
  skill_group:
    form.role === "agent"
      ? [{ required: true, message: t("ticketflow.account.groupRequired") }]
      : [],
  password: isCreate.value
    ? [
        {
          required: true,
          message: t("ticketflow.account.passwordRequired")
        },
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
    : []
}));

function generatePassword() {
  form.password = generateRandomPassword(props.passwordRules);
  void formRef.value?.validateField("password").catch(() => undefined);
}

/** 返回明文载荷（密码由弹窗按底座约定加密后再提交）；校验失败返回 null */
async function getPayload(): Promise<AccountPayload | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return null;
  if (form.role === "agent" && !form.skill_group) return null;
  return {
    ...(isCreate.value
      ? { username: form.username.trim(), password: form.password }
      : {}),
    name: form.name.trim(),
    phone: form.phone.trim(),
    email: form.email.trim(),
    role: form.role,
    skill_group: form.role === "agent" ? form.skill_group : null
  };
}

defineExpose({ getPayload, form, generatePassword });
</script>

<template>
  <el-form
    ref="formRef"
    :model="form"
    :rules="rules"
    label-width="96px"
    data-testid="account-form"
  >
    <el-form-item :label="t('ticketflow.account.username')" prop="username">
      <el-input
        v-model="form.username"
        :disabled="!isCreate"
        maxlength="64"
        autocomplete="off"
      />
    </el-form-item>
    <el-form-item :label="t('ticketflow.account.name')" prop="name">
      <el-input v-model="form.name" maxlength="64" />
    </el-form-item>
    <el-form-item :label="t('ticketflow.account.role')" prop="role">
      <el-radio-group v-model="form.role">
        <el-radio-button
          v-for="role in ACCOUNT_ROLES"
          :key="role"
          :value="role"
        >
          {{ t(`ticketflow.account.roleValue.${role}`) }}
        </el-radio-button>
      </el-radio-group>
    </el-form-item>
    <el-form-item
      v-if="form.role === 'agent'"
      :label="t('ticketflow.account.skillGroup')"
      prop="skill_group"
    >
      <el-select v-model="form.skill_group" class="w-full">
        <el-option
          v-for="group in groupOptions"
          :key="group.pk"
          :label="group.name"
          :value="group.pk"
          :disabled="!group.is_active"
        />
      </el-select>
    </el-form-item>
    <el-form-item :label="t('ticketflow.account.phone')" prop="phone">
      <el-input v-model="form.phone" maxlength="32" />
    </el-form-item>
    <el-form-item :label="t('ticketflow.account.email')" prop="email">
      <el-input v-model="form.email" maxlength="128" />
    </el-form-item>
    <el-form-item
      v-if="isCreate"
      :label="t('ticketflow.account.password')"
      prop="password"
    >
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
