<script lang="ts" setup>
import { reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import {
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  type TicketCreatePayload
} from "@/api/ticketflow/tickets";

/**
 * 转人工提单：AI 草稿预填标题、问题描述与建议分类，员工确认或修改后提交。
 * 只负责收集与校验，提交（带 assistant_session_id 与幂等键）由打开它的弹窗完成。
 * 手写原因：表单同时承担草稿预填与会话关联，提交目标是带会话的建单动作，元数据表单表达不了。
 */
defineOptions({ name: "TicketFlowHandoffForm" });

const TITLE_MAX = 200;
const DESCRIPTION_MAX = 20000;

const props = defineProps<{
  initial?: Partial<Omit<TicketCreatePayload, "assistant_session_id">>;
}>();

const { t } = useI18n();
const formRef = ref<FormInstance>();
const form = reactive({
  title: props.initial?.title ?? "",
  description: props.initial?.description ?? "",
  category: TICKET_CATEGORIES.includes(props.initial?.category ?? "")
    ? props.initial!.category!
    : "OTHER",
  priority: props.initial?.priority ?? "P2"
});

const rules: FormRules = {
  title: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.handoff.titleRequired")
    },
    {
      max: TITLE_MAX,
      message: t("ticketflow.handoff.tooLong", { max: TITLE_MAX })
    }
  ],
  description: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.handoff.descriptionRequired")
    },
    {
      max: DESCRIPTION_MAX,
      message: t("ticketflow.handoff.tooLong", { max: DESCRIPTION_MAX })
    }
  ],
  category: [{ required: true }],
  priority: [{ required: true }]
};

async function getPayload(): Promise<Omit<
  TicketCreatePayload,
  "assistant_session_id"
> | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  const title = form.title.trim();
  const description = form.description.trim();
  if (
    !valid ||
    !title ||
    !description ||
    title.length > TITLE_MAX ||
    description.length > DESCRIPTION_MAX
  )
    return null;
  return {
    title,
    description,
    category: form.category,
    priority: form.priority
  };
}

defineExpose({ getPayload });
</script>

<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="mb-4"
      :title="t('ticketflow.handoff.hint')"
    />
    <el-form-item :label="t('ticketflow.title')" prop="title">
      <el-input v-model="form.title" :maxlength="TITLE_MAX" show-word-limit />
    </el-form-item>
    <el-form-item :label="t('ticketflow.description')" prop="description">
      <el-input
        v-model="form.description"
        type="textarea"
        :rows="8"
        :maxlength="DESCRIPTION_MAX"
      />
    </el-form-item>
    <div class="grid gap-4 md:grid-cols-2">
      <el-form-item :label="t('ticketflow.category')" prop="category">
        <el-select v-model="form.category" data-testid="handoff-category">
          <el-option
            v-for="value in TICKET_CATEGORIES"
            :key="value"
            :label="t(`ticketflow.categoryValue.${value}`)"
            :value="value"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('ticketflow.priority')" prop="priority">
        <el-select v-model="form.priority" data-testid="handoff-priority">
          <el-option
            v-for="value in TICKET_PRIORITIES"
            :key="value"
            :label="value"
            :value="value"
          />
        </el-select>
      </el-form-item>
    </div>
  </el-form>
</template>
