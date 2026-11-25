<script lang="ts" setup>
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import { renderMarkdown } from "@/utils/markdown";
import { message } from "@/utils/message";
import { generateKbDraft } from "@/api/ticketflow/ai";
import type { ArticlePayload } from "@/api/ticketflow/knowledge";
import { TICKET_CATEGORIES as CATEGORIES } from "@/api/ticketflow/tickets";

/**
 * 知识库文章编辑表单：标题、分类、标签与 Markdown 正文，正文可切换预览。
 * 只负责收集与校验，提交由打开它的弹窗完成（getPayload 校验失败返回 null）。
 * 手写原因：正文需要预览、标签是可自由新增的字符串数组，元数据表单表达不了。
 */
defineOptions({ name: "TicketFlowArticleEditor" });

const props = defineProps<{
  initial?: Partial<ArticlePayload>;
  sourceTicketId?: string;
}>();
const { t } = useI18n();
const formRef = ref<FormInstance>();
const tab = ref<"edit" | "preview">("edit");
const generatingDraft = ref(false);
const form = reactive<ArticlePayload>({
  title: props.initial?.title ?? "",
  category: props.initial?.category ?? "OTHER",
  tags: [...(props.initial?.tags ?? [])],
  body_markdown: props.initial?.body_markdown ?? ""
});

const rules: FormRules = {
  title: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.kb.titleRequired")
    },
    { max: 200, message: t("ticketflow.kb.titleTooLong") }
  ],
  category: [{ required: true, message: t("ticketflow.kb.categoryRequired") }],
  body_markdown: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.kb.bodyRequired")
    }
  ],
  tags: [
    {
      validator: (_rule, value: string[], callback) => {
        const tags = value.map(tag => tag.trim()).filter(Boolean);
        return tags.length > 12 || tags.some(tag => tag.length > 64)
          ? callback(new Error(t("ticketflow.kb.tagsInvalid")))
          : callback();
      }
    }
  ]
};

const preview = computed(() => renderMarkdown(form.body_markdown));

async function generateFromTicket() {
  if (!props.sourceTicketId || generatingDraft.value) return;
  generatingDraft.value = true;
  try {
    const draft = await generateKbDraft(props.sourceTicketId);
    form.title = draft.title;
    form.category = draft.category;
    form.tags = [...draft.tags];
    form.body_markdown = draft.body_markdown;
    message(t("ticketflow.kb.aiDraftLoaded"), { type: "success" });
  } catch {
    message(t("ticketflow.kb.aiDraftFailed"), { type: "warning" });
  } finally {
    generatingDraft.value = false;
  }
}

async function getPayload(): Promise<ArticlePayload | null> {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return null;
  return {
    title: form.title.trim(),
    category: form.category,
    tags: form.tags.map(tag => tag.trim()).filter(Boolean),
    body_markdown: form.body_markdown
  };
}

defineExpose({ getPayload });
</script>

<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-width="72px">
    <div v-if="sourceTicketId" class="flex justify-end mb-3">
      <el-button
        type="primary"
        plain
        size="small"
        :loading="generatingDraft"
        data-testid="kb-ai-draft"
        @click="generateFromTicket"
      >
        {{ t("ticketflow.kb.aiGenerateDraft") }}
      </el-button>
    </div>
    <el-form-item :label="t('ticketflow.title')" prop="title">
      <el-input v-model="form.title" maxlength="200" show-word-limit />
    </el-form-item>
    <el-form-item :label="t('ticketflow.category')" prop="category">
      <el-select v-model="form.category" class="w-full">
        <el-option
          v-for="value in CATEGORIES"
          :key="value"
          :value="value"
          :label="t(`ticketflow.categoryValue.${value}`)"
        />
      </el-select>
    </el-form-item>
    <el-form-item :label="t('ticketflow.kb.tags')" prop="tags">
      <el-select
        v-model="form.tags"
        class="w-full"
        multiple
        filterable
        allow-create
        default-first-option
        :reserve-keyword="false"
        :placeholder="t('ticketflow.kb.tagsPlaceholder')"
      />
    </el-form-item>
    <el-form-item :label="t('ticketflow.kb.body')" prop="body_markdown">
      <el-tabs v-model="tab" class="w-full">
        <el-tab-pane :label="t('ticketflow.kb.edit')" name="edit">
          <el-input
            v-model="form.body_markdown"
            type="textarea"
            :rows="14"
            maxlength="100000"
            :placeholder="t('ticketflow.kb.bodyPlaceholder')"
          />
        </el-tab-pane>
        <el-tab-pane :label="t('ticketflow.kb.preview')" name="preview">
          <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown 关闭原始 HTML 并经 DOMPurify 净化 -->
          <div class="markdown-body min-h-40" v-html="preview" />
        </el-tab-pane>
      </el-tabs>
    </el-form-item>
  </el-form>
</template>
