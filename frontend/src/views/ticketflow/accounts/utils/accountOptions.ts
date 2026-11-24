import { onMounted, ref } from "vue";
import { isSuccess } from "@/api/types";
import { rulesPasswordApi, type PasswordRule } from "@/api/auth";
import { skillGroupApi, type SkillGroup } from "@/api/ticketflow/accounts";

/** 账号表单依赖的选项：技能组（含停用，表单内按需过滤）与全局密码规则：挂载时加载，打开弹窗前再刷新 */
export function useAccountOptions() {
  const groups = ref<SkillGroup[]>([]);
  const passwordRules = ref<PasswordRule[]>([]);

  async function loadOptions() {
    const [groupRes, ruleRes] = await Promise.all([
      skillGroupApi.list<SkillGroup>({ page: 1, size: 200 }).catch(() => null),
      rulesPasswordApi().catch(() => null)
    ]);
    if (groupRes && isSuccess(groupRes))
      groups.value = groupRes.data?.results ?? [];
    if (ruleRes && isSuccess(ruleRes))
      passwordRules.value = ruleRes.data?.password_rules ?? [];
  }
  onMounted(() => void loadOptions());

  return { groups, passwordRules, loadOptions };
}
