<script lang="ts" setup>
import { useI18n } from "vue-i18n";
import { View } from "@element-plus/icons-vue";
import type { ArticleItem } from "@/api/ticketflow/knowledge";

/** 工作台“最新知识”：最近更新的已发布文章，点击打开文章详情 */
defineOptions({ name: "WorkbenchLatestArticles" });

defineProps<{ articles: ArticleItem[]; loading: boolean }>();
const emit = defineEmits<{ open: [article: ArticleItem]; more: [] }>();

const { t, te } = useI18n();

function categoryLabel(category: string) {
  const key = `ticketflow.categoryValue.${category}`;
  return te(key) ? t(key) : category;
}
</script>

<template>
  <el-card shadow="never" class="h-full" body-class="p-0!">
    <template #header>
      <div class="flex-bc">
        <span class="font-medium">{{ t("workbench.latestArticles") }}</span>
        <el-button link type="primary" @click="emit('more')">
          {{ t("workbench.viewAll") }}
        </el-button>
      </div>
    </template>
    <div v-loading="loading" class="min-h-40">
      <el-empty
        v-if="!loading && articles.length === 0"
        :image-size="72"
        :description="t('workbench.noArticles')"
      />
      <button
        v-for="article in articles"
        :key="article.pk"
        type="button"
        class="article-row"
        data-testid="workbench-article"
        @click="emit('open', article)"
      >
        <span class="truncate text-fg">{{ article.title }}</span>
        <span class="flex items-center gap-2 text-xs text-fg-muted">
          <span>{{ categoryLabel(article.category) }}</span>
          <span class="inline-flex items-center gap-0.5">
            <el-icon><View /></el-icon>{{ article.view_count }}
          </span>
        </span>
      </button>
    </div>
  </el-card>
</template>

<style lang="scss" scoped>
.article-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
  width: 100%;
  padding: 12px 20px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);

  &:last-child {
    border-bottom: 0;
  }

  &:hover,
  &:focus-visible {
    outline: none;
    background: var(--el-fill-color-light);
  }

  > .truncate {
    max-width: 100%;
  }
}
</style>
