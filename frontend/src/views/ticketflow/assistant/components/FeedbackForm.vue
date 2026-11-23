<script lang="ts" setup>
import { reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import {
  FEEDBACK_REASONS,
  type AssistantFeedback,
  type FeedbackPayload,
  type FeedbackReason
} from "@/api/ticketflow/assistant";

/**
 * 点踩反馈：原因（可选）与一句补充。只负责收集与校验，提交由打开它的弹窗完成。
 * 手写原因：提交目标是回答的反馈动作，固定词表单选与补充说明无对应模型元数据。
 */
defineOptions({ name: "TicketFlowAssistantFeedbackForm" });

const COMMENT_MAX = 300;

const props = defineProps<{ initial?: AssistantFeedback | null }>();

const { t } = useI18n();
const formRef = ref<FormInstance>();
const form = reactive<{ reason: FeedbackReason | undefined; comment: string }>({
  reason:
    props.initial?.vote === "down"
      ? (props.initial.reason ?? undefined)
      : undefined,
  comment: props.initial?.vote === "down" ? props.initial.comment : ""
});

const rules: FormRules = {
  comment: [
    {
      max: COMMENT_MAX,
      message: t("ticketflow.assistant.commentTooLong", { max: COMMENT_MAX })
    }
  ]
};

async function getPayload(): Promise<FeedbackPayload | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  const comment = form.comment.trim();
  if (!valid || comment.length > COMMENT_MAX) return null;
  return { vote: "down", reason: form.reason ?? null, comment };
}

defineExpose({ getPayload });
</script>

<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
    <el-form-item :label="t('ticketflow.assistant.reason')" prop="reason">
      <el-radio-group v-model="form.reason">
        <el-radio
          v-for="reason in FEEDBACK_REASONS"
          :key="reason"
          :value="reason"
          :data-testid="`reason-${reason}`"
        >
          {{ t(`ticketflow.assistant.reasonValue.${reason}`) }}
        </el-radio>
      </el-radio-group>
    </el-form-item>
    <el-form-item :label="t('ticketflow.assistant.comment')" prop="comment">
      <el-input
        v-model="form.comment"
        type="textarea"
        :rows="3"
        :maxlength="COMMENT_MAX"
        show-word-limit
        :placeholder="t('ticketflow.assistant.commentPlaceholder')"
      />
    </el-form-item>
  </el-form>
</template>
