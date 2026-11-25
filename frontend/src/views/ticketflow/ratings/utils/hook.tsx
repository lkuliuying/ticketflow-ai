import { reactive, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import { hasAuth, usePageAuth } from "@/router/utils";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import { useUserStoreHook } from "@/store/modules/user";
import { isSuccess } from "@/api/types";
import type { OperationProps } from "@/components/RePlusPage";
import {
  ratingApi,
  type RatingSummary,
  type TicketRating
} from "@/api/ticketflow/ratings";
import { openRatingDetailDialog } from "./ratingDetailDialog";
import {
  buildRatingListColumns,
  buildRatingSearchColumns,
  type RatingsMode
} from "./ratingColumns";
import View from "~icons/ep/view";

/**
 * 评价列表与汇总（技术员“我的评价”与管理员“评价统计”共用）。
 * 范围由后端按身份限定；列表只读，不提供新建、编辑与删除。
 */
export function useRatings(
  componentName: string,
  options: { mode?: RatingsMode } = {}
) {
  const mode: RatingsMode = options.mode ?? "mine";
  const { t } = useI18n();
  const userStore = useUserStoreHook();
  const api = reactive(ratingApi);
  const auth = usePageAuth(componentName, ["summary"]);
  auth.create = false;
  auth.update = false;
  auth.destroy = false;
  auth.batchDestroy = false;
  const canSummary = Boolean(auth.summary);
  const canViewTicket = hasAuth("retrieve:TicketFlowTickets");
  const fixedHandlerName =
    mode === "mine" ? userStore.nickname || userStore.username || "" : "";

  const summary = ref<RatingSummary | null>(null);
  const summaryLoading = ref(false);
  let summarySeq = 0;

  /** 快速切换时间段时只采用最后一次请求的结果；无汇总权限时不请求避免触发 403 */
  async function loadSummary(params?: {
    created_from?: string;
    created_to?: string;
  }) {
    if (!canSummary) {
      summary.value = null;
      return;
    }
    const seq = ++summarySeq;
    summaryLoading.value = true;
    const res = await ratingApi.summary(params).catch(() => null);
    if (seq !== summarySeq) return;
    summaryLoading.value = false;
    summary.value = res && isSuccess(res) ? res.data : null;
  }

  const listColumnsFormat = buildRatingListColumns({
    t,
    canViewTicket,
    fixedHandlerName: mode === "mine" ? fixedHandlerName : undefined
  });

  const searchColumnsFormat = buildRatingSearchColumns({
    t,
    mode,
    fixedHandlerName,
    summary
  });

  const operationButtonsProps = shallowRef<OperationProps>({
    hideDetail: true,
    buttons: [
      {
        code: "ratingDetail",
        props: {
          type: "primary",
          icon: useRenderIcon(View),
          link: true,
          "aria-label": t("ticketflow.rating.detailTitle")
        },
        tooltip: { content: t("ticketflow.rating.detailTitle") },
        onClick: ({ row }) =>
          openRatingDetailDialog(row as TicketRating, {
            canViewTicket,
            fixedHandlerName: mode === "mine" ? fixedHandlerName : undefined
          }),
        index: -10,
        show: Boolean(auth.list)
      }
    ]
  });

  return {
    api,
    auth,
    canSummary,
    summary,
    summaryLoading,
    loadSummary,
    listColumnsFormat,
    searchColumnsFormat,
    operationButtonsProps
  };
}
