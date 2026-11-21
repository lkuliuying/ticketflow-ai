import { h } from "vue";
import { deviceDetection } from "@pureadmin/utils";
import { addDrawer } from "@/components/ReDrawer";
import { drawerSize } from "@/components/ReDialog/size";
import ArticleDetailView from "../components/ArticleDetail.vue";

/** 打开文章详情抽屉；编辑或状态变更后通过 onChanged 通知列表刷新 */
export function openArticleDetail(
  row: { pk: string; title: string },
  onChanged?: () => void
) {
  addDrawer({
    title: row.title,
    size: deviceDetection() ? drawerSize("full") : drawerSize("md"),
    destroyOnClose: true,
    closeOnClickModal: true,
    hideFooter: true,
    contentRenderer: () => h(ArticleDetailView, { pk: row.pk, onChanged })
  });
}
