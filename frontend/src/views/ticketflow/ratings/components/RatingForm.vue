<script lang="ts" setup>
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import {
  RATING_TAGS,
  type RatingPayload,
  type RatingTag
} from "@/api/ticketflow/ratings";

/**
 * 工单评价表单：问题是否解决、满意度、处理人评分、标签与文字评价。
 * 只负责收集与校验，提交由打开它的弹窗完成（getPayload 校验失败返回 null）。
 * 手写原因：提交目标是工单的评价动作，星级与固定词表多选标签无对应模型元数据。
 */
defineOptions({ name: "TicketFlowRatingForm" });

const COMMENT_MAX = 500;

defineProps<{ handlerName?: string | null }>();

const { t } = useI18n();
const formRef = ref<FormInstance>();
const form = reactive<{
  resolved: boolean | undefined;
  satisfaction: number;
  handler_score: number;
  tags: RatingTag[];
  comment: string;
}>({
  resolved: undefined,
  satisfaction: 0,
  handler_score: 0,
  tags: [],
  comment: ""
});

const isScore = (value: number) =>
  Number.isInteger(value) && value >= 1 && value <= 5;

const starRequired = (message: string) => ({
  required: true,
  validator: (
    _rule: unknown,
    value: number,
    callback: (_error?: Error) => void
  ) => (value >= 1 && value <= 5 ? callback() : callback(new Error(message)))
});

const rules: FormRules = {
  resolved: [
    {
      required: true,
      validator: (_rule, value, callback) =>
        value === undefined
          ? callback(new Error(t("ticketflow.rating.resolvedRequired")))
          : callback()
    }
  ],
  satisfaction: [starRequired(t("ticketflow.rating.scoreRequired"))],
  handler_score: [starRequired(t("ticketflow.rating.scoreRequired"))],
  comment: [
    {
      max: COMMENT_MAX,
      message: t("ticketflow.rating.commentTooLong", { max: COMMENT_MAX })
    }
  ]
};

/** 表单校验之外再按同一口径兜底检查，保证提交数据始终满足后端约束 */
async function getPayload(): Promise<RatingPayload | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  if (
    !valid ||
    form.resolved === undefined ||
    !isScore(form.satisfaction) ||
    !isScore(form.handler_score) ||
    form.comment.trim().length > COMMENT_MAX
  )
    return null;
  return {
    resolved: form.resolved,
    satisfaction: form.satisfaction,
    handler_score: form.handler_score,
    tags: [...form.tags],
    comment: form.comment.trim()
  };
}

/** 星级文案：1~5 分各一档 */
const scoreTexts = computed(() =>
  [1, 2, 3, 4, 5].map(score => t(`ticketflow.rating.scoreText.${score}`))
);

defineExpose({ getPayload, form });
</script>

<template>
  <el-form
    ref="formRef"
    :model="form"
    :rules="rules"
    label-position="top"
    data-testid="rating-form"
  >
    <el-form-item :label="t('ticketflow.rating.resolved')" prop="resolved">
      <el-radio-group v-model="form.resolved">
        <el-radio-button :value="true">
          {{ t("ticketflow.rating.resolvedYes") }}
        </el-radio-button>
        <el-radio-button :value="false">
          {{ t("ticketflow.rating.resolvedNo") }}
        </el-radio-button>
      </el-radio-group>
    </el-form-item>
    <el-form-item
      :label="t('ticketflow.rating.satisfaction')"
      prop="satisfaction"
    >
      <el-rate v-model="form.satisfaction" show-text :texts="scoreTexts" />
    </el-form-item>
    <el-form-item
      :label="
        handlerName
          ? t('ticketflow.rating.handlerScoreFor', { name: handlerName })
          : t('ticketflow.rating.handlerScore')
      "
      prop="handler_score"
    >
      <el-rate v-model="form.handler_score" show-text :texts="scoreTexts" />
    </el-form-item>
    <el-form-item :label="t('ticketflow.rating.tags')">
      <el-checkbox-group v-model="form.tags">
        <el-checkbox-button v-for="tag in RATING_TAGS" :key="tag" :value="tag">
          {{ t(`ticketflow.rating.tagValue.${tag}`) }}
        </el-checkbox-button>
      </el-checkbox-group>
    </el-form-item>
    <el-form-item :label="t('ticketflow.rating.comment')" prop="comment">
      <el-input
        v-model="form.comment"
        type="textarea"
        :rows="3"
        :maxlength="COMMENT_MAX"
        show-word-limit
        :placeholder="t('ticketflow.rating.commentPlaceholder')"
      />
    </el-form-item>
  </el-form>
</template>
