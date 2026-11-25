import { reactive, shallowRef, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { usePageAuth } from "@/router/utils";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import type { OperationProps } from "@/components/RePlusPage";
import {
  ticketApi,
  type TicketDetail,
  type TicketItem
} from "@/api/ticketflow/tickets";
import { openArticleEditor } from "../../knowledge/utils/articleEditorDialog";
import { useTicketColumns } from "./ticketColumns";
import { openTicketCreateDialog } from "./ticketCreateDialog";
import { openTicketDetail } from "./ticketDetailDrawer";
import View from "~icons/ep/view";
import Plus from "~icons/ep/plus";

type PageRef = Ref<{ handleGetData?: () => void } | undefined>;

/**
 * 工单列表页：列表、筛选和新建表单由后端元数据驱动。
 *
 * 新建走 `ticketApi.create`，它为每份待提交内容附带 `Idempotency-Key`，
 * 重复提交同一份内容不会生成第二张工单。工单没有通用的编辑和删除接口，
 * 状态变化统一在详情抽屉里经流转、指派、回复完成；框架默认的只读“查看”
 * 换成工单详情抽屉，写操作后刷新列表。
 */
export function useTickets(tableRef: PageRef) {
  const { t, te } = useI18n();
  const api = reactive(ticketApi);
  const auth = usePageAuth("TicketFlowTickets", ["chatFile"]);

  const { listColumnsFormat } = useTicketColumns({ t, te });
  const reload = () => tableRef.value?.handleGetData?.();

  function openCreate() {
    if (!auth.create) return;
    openTicketCreateDialog({
      title: t("ticketflow.detail.createTitle"),
      createdText: t("ticketflow.detail.created"),
      failedText: t("ticketflow.detail.createFailed"),
      onCreated: reload
    });
  }

  /** 已关闭工单转存知识库草稿：预填标题、分类与问题描述，保存后刷新详情 */
  function archive(ticket: TicketDetail, reloadDetail: () => void) {
    openArticleEditor({
      title: t("ticketflow.kb.archiveTitle"),
      savedText: t("ticketflow.kb.archived"),
      sourceTicketId: ticket.pk,
      initial: {
        title: ticket.title,
        category: ticket.category,
        tags: ticket.ai_tags,
        body_markdown: [
          `## ${t("ticketflow.kb.problem")}`,
          ticket.description,
          `## ${t("ticketflow.kb.solution")}`,
          ""
        ].join("\n\n")
      },
      onSaved: reloadDetail
    });
  }

  const operationButtonsProps = shallowRef<OperationProps>({
    hideDetail: true,
    buttons: [
      {
        code: "ticketDetail",
        props: {
          type: "primary",
          icon: useRenderIcon(View),
          link: true,
          "aria-label": t("ticketflow.detail.open")
        },
        tooltip: { content: t("ticketflow.detail.open") },
        onClick: ({ row }) =>
          openTicketDetail(row as TicketItem, {
            onChanged: reload,
            onArchive: archive
          }),
        index: -10,
        show: Boolean(auth.retrieve)
      }
    ]
  });

  const tableBarButtonsProps = shallowRef<OperationProps>({
    buttons: [
      {
        code: "ticketCreate",
        text: t("ticketflow.detail.createTitle"),
        props: {
          type: "primary",
          icon: useRenderIcon(Plus)
        },
        onClick: openCreate,
        show: Boolean(auth.create)
      }
    ]
  });

  return {
    api,
    auth: { ...auth, create: false },
    canCreate: Boolean(auth.create),
    openCreate,
    listColumnsFormat,
    operationButtonsProps,
    tableBarButtonsProps
  };
}
