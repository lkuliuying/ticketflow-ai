<script lang="ts" setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import { renderMarkdown } from "@/utils/markdown";
import {
  knowledgeApi,
  type ArticleDetail,
  type ArticleStatus
} from "@/api/ticketflow/knowledge";
import { ARTICLE_STATUS_TONE, nextStatuses } from "../utils/articleStatus";
import { openArticleEditor } from "../utils/articleEditorDialog";

/**
 * 文章详情：元信息、经过净化的 Markdown 正文，以及按 `viewer` 显示的
 * 编辑与发布操作。打开详情会累加浏览次数（由后端处理）。
 */
defineOptions({ name: "TicketFlowArticleDetail" });

const props = defineProps<{ pk: string; onChanged?: () => void }>();
const { t, te } = useI18n();
const article = ref<ArticleDetail | null>(null);
const loading = ref(false);
const notFound = ref(false);

const busy = ref(false);

/** 只有 404（不存在或不可见）显示“不存在”；网络异常与 5xx 保留已加载内容，提示由拦截器展示 */
async function load() {
  loading.value = true;
  try {
    const res = await knowledgeApi.retrieve<ArticleDetail>(props.pk);
    if (isSuccess(res)) {
      article.value = res.data;
      notFound.value = false;
    }
  } catch (error) {
    if ((error as { code?: number } | null)?.code === 404)
      notFound.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const html = computed(() => renderMarkdown(article.value?.body_markdown ?? ""));
const transitions = computed(() =>
  article.value?.viewer.can_publish ? nextStatuses(article.value.status) : []
);

function categoryLabel(value: string) {
  const key = `ticketflow.categoryValue.${value}`;
  return te(key) ? t(key) : value;
}

/** 状态变更直接采用 PATCH 返回的文章，不再重新拉详情（详情读取会累加浏览数） */
async function changeStatus(status: ArticleStatus) {
  if (!article.value || busy.value) return;
  busy.value = true;
  const res = await knowledgeApi
    .updateArticle(article.value.pk, { status })
    .catch(() => null);
  busy.value = false;
  if (res && isSuccess(res)) {
    message(t(`ticketflow.kb.statusChanged.${status}`), { type: "success" });
    article.value = res.data;
    props.onChanged?.();
  }
}

function edit() {
  const current = article.value;
  if (!current) return;
  openArticleEditor({
    title: t("ticketflow.kb.editTitle"),
    savedText: t("ticketflow.kb.saved"),
    pk: current.pk,
    initial: current,
    onSaved: saved => {
      article.value = saved;
      props.onChanged?.();
    }
  });
}
</script>

<template>
  <div v-loading="loading" class="flex flex-col gap-4 min-h-40">
    <el-result
      v-if="notFound"
      icon="warning"
      :title="t('ticketflow.kb.notFound')"
    />
    <template v-else-if="article">
      <header class="flex flex-col gap-2" data-testid="article-header">
        <div class="flex items-center gap-2 flex-wrap">
          <el-tag :type="ARTICLE_STATUS_TONE[article.status]">
            {{ t(`ticketflow.kb.statusValue.${article.status}`) }}
          </el-tag>
          <el-tag effect="plain">{{ categoryLabel(article.category) }}</el-tag>
          <el-tag
            v-for="tag in article.tags"
            :key="tag"
            type="info"
            effect="plain"
          >
            {{ tag }}
          </el-tag>
          <span class="text-sm text-(--el-text-color-secondary)">
            {{ t("ticketflow.kb.views", { count: article.view_count }) }}
            · {{ new Date(article.updated_time).toLocaleString() }}
          </span>
        </div>
        <h3 class="m-0">{{ article.title }}</h3>
        <span
          v-if="article.source_ticket_id"
          class="text-sm text-(--el-text-color-secondary)"
        >
          {{ t("ticketflow.kb.fromTicket", { id: article.source_ticket_id }) }}
        </span>
      </header>

      <div
        v-if="article.viewer.can_edit || transitions.length"
        class="flex flex-wrap gap-2"
        data-testid="article-actions"
      >
        <el-button v-if="article.viewer.can_edit" @click="edit">
          {{ t("ticketflow.kb.edit") }}
        </el-button>
        <el-button
          v-for="status in transitions"
          :key="status"
          :type="status === 'PUBLISHED' ? 'success' : 'warning'"
          :loading="busy"
          @click="changeStatus(status)"
        >
          {{ t(`ticketflow.kb.toStatus.${status}`) }}
        </el-button>
      </div>

      <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown 关闭原始 HTML 并经 DOMPurify 净化 -->
      <article class="markdown-body" data-testid="article-body" v-html="html" />
    </template>
  </div>
</template>
