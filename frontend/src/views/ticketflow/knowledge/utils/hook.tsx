import { h, reactive, ref, shallowRef, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElTag } from "element-plus";
import { usePageAuth } from "@/router/utils";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import {
  formatPageColumns,
  type OperationProps,
  type PageTableColumn
} from "@/components/RePlusPage";
import { knowledgeApi, type ArticleItem } from "@/api/ticketflow/knowledge";
import { ARTICLE_STATUS_TONE } from "./articleStatus";
import { openArticleDetail } from "./articleDetailDrawer";
import { openArticleEditor } from "./articleEditorDialog";
import View from "~icons/ep/view";

type PageRef = Ref<{ handleGetData?: () => void } | undefined>;

/**
 * 知识库列表页。框架默认的新建（元数据表单）与查看换成自有入口：
 * 新建走文章编辑弹窗，且只有列表返回 `can_create_standalone` 时才出现；
 * 查看打开文章详情抽屉，编辑与发布在详情里按 `viewer` 操作。
 */
export function useArticles(tableRef: PageRef) {
  const { t, te } = useI18n();
  const api = reactive(knowledgeApi);
  const auth = usePageAuth("TicketFlowKnowledge");
  // 默认新建与编辑走元数据表单，无法编辑字符串数组标签与 Markdown 预览，统一关闭
  auth.create = false;
  const canCreate = ref(false);
  const reload = () => tableRef.value?.handleGetData?.();

  const listColumnsFormat = (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      status: column => {
        column["cellRenderer"] = ({ row }) => {
          const status = (row as ArticleItem).status;
          return h(
            ElTag,
            { size: "small", type: ARTICLE_STATUS_TONE[status] },
            () => t(`ticketflow.kb.statusValue.${status}`)
          );
        };
      },
      category: column => {
        column["cellRenderer"] = ({ row }) => {
          const key = `ticketflow.categoryValue.${(row as ArticleItem).category}`;
          return h("span", te(key) ? t(key) : (row as ArticleItem).category);
        };
      },
      tags: column => {
        column["cellRenderer"] = ({ row }) =>
          h(
            "span",
            { class: "flex flex-wrap gap-1" },
            ((row as ArticleItem).tags ?? []).map(tag =>
              h(
                ElTag,
                { size: "small", type: "info", effect: "plain" },
                () => tag
              )
            )
          );
      }
    });

  const operationButtonsProps = shallowRef<OperationProps>({
    hideDetail: true,
    hideEdit: true,
    buttons: [
      {
        code: "articleDetail",
        props: {
          type: "primary",
          icon: useRenderIcon(View),
          link: true,
          "aria-label": t("ticketflow.kb.open")
        },
        tooltip: { content: t("ticketflow.kb.open") },
        onClick: ({ row }) => openArticleDetail(row as ArticleItem, reload),
        index: -10,
        show: Boolean(auth.retrieve)
      }
    ]
  });

  const tableBarButtonsProps = shallowRef<OperationProps>({
    buttons: [
      {
        text: t("ticketflow.kb.create"),
        code: "createArticle",
        props: { type: "primary" },
        onClick: () =>
          openArticleEditor({
            title: t("ticketflow.kb.createTitle"),
            savedText: t("ticketflow.kb.created"),
            onSaved: reload
          }),
        show: canCreate
      }
    ]
  });

  /** 列表响应顶层的 can_create_standalone 决定是否显示新建入口 */
  function onSearchComplete({ res }: { res: Record<string, unknown> }) {
    const data = res?.data as { can_create_standalone?: boolean } | undefined;
    canCreate.value = Boolean(data?.can_create_standalone);
  }

  return {
    api,
    auth,
    listColumnsFormat,
    operationButtonsProps,
    tableBarButtonsProps,
    onSearchComplete
  };
}
