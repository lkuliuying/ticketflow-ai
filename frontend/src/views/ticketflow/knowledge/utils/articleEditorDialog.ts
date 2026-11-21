import { h, ref } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDialog } from "@/components/ReDialog";
import { dialogSize } from "@/components/ReDialog/size";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import {
  knowledgeApi,
  type ArticleDetail,
  type ArticlePayload
} from "@/api/ticketflow/knowledge";
import ArticleEditor from "../components/ArticleEditor.vue";

type EditorRef = { getPayload: () => Promise<ArticlePayload | null> };

/**
 * 打开文章编辑弹窗。
 *
 * - 不带 pk：新建草稿；带 sourceTicketId 时为从已关闭工单转存；
 * - 带 pk：编辑已有文章（只提交内容字段，状态变更在详情里单独操作）。
 * 先 done() 关弹层再回调刷新，失败时保持弹层便于修改。
 */
export function openArticleEditor(options: {
  title: string;
  savedText: string;
  pk?: string;
  sourceTicketId?: string;
  initial?: Partial<ArticlePayload>;
  onSaved?: (article: ArticleDetail) => void;
}) {
  const editorRef = ref<EditorRef>();
  addDialog({
    title: options.title,
    width: deviceDetection() ? "100%" : dialogSize("lg"),
    draggable: true,
    closeOnClickModal: false,
    // 确认按钮提交中显示 loading 并阻止重复点击，避免重复新建或重复转存
    sureBtnLoading: true,
    contentRenderer: () =>
      h(ArticleEditor, { ref: editorRef, initial: options.initial }),
    beforeSure: async (done, { closeLoading }) => {
      const payload = await editorRef.value?.getPayload();
      if (!payload) {
        closeLoading();
        return;
      }
      const res = await (
        options.pk
          ? knowledgeApi.updateArticle(options.pk, payload)
          : knowledgeApi.createArticle({
              ...payload,
              ...(options.sourceTicketId
                ? { source_ticket_id: options.sourceTicketId }
                : {})
            })
      ).catch(() => null);
      closeLoading();
      if (res && isSuccess(res)) {
        message(options.savedText, { type: "success" });
        done();
        options.onSaved?.(res.data);
      }
    }
  });
}
