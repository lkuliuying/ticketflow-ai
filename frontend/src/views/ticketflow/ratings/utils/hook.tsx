import { h, reactive, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import { ElRate, ElTag } from "element-plus";
import { usePageAuth } from "@/router/utils";
import { isSuccess } from "@/api/types";
import {
  formatPageColumns,
  type OperationProps,
  type PageTableColumn
} from "@/components/RePlusPage";
import {
  ratingApi,
  type RatingSummary,
  type TicketRating
} from "@/api/ticketflow/ratings";

/**
 * 评价列表与汇总（技术员“我的评价”与管理员“评价统计”共用）。
 * 范围由后端按身份限定；列表只读，不提供新建、编辑与删除。
 */
export function useRatings(componentName: string) {
  const { t } = useI18n();
  const api = reactive(ratingApi);
  const auth = usePageAuth(componentName);
  auth.create = false;
  auth.update = false;
  auth.destroy = false;
  auth.batchDestroy = false;

  const summary = ref<RatingSummary | null>(null);
  const summaryLoading = ref(false);

  async function loadSummary(params?: {
    created_from?: string;
    created_to?: string;
  }) {
    summaryLoading.value = true;
    const res = await ratingApi.summary(params).catch(() => null);
    summaryLoading.value = false;
    if (res && isSuccess(res)) summary.value = res.data;
  }

  const stars = (value: number) =>
    h(ElRate, { modelValue: value, disabled: true, size: "small" });

  const listColumnsFormat = (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      resolved: column => {
        column["cellRenderer"] = ({ row }) => {
          const resolved = (row as TicketRating).resolved;
          return h(
            ElTag,
            { size: "small", type: resolved ? "success" : "danger" },
            () =>
              resolved
                ? t("ticketflow.rating.resolvedYes")
                : t("ticketflow.rating.resolvedNo")
          );
        };
      },
      satisfaction: column => {
        column["cellRenderer"] = ({ row }) =>
          stars((row as TicketRating).satisfaction);
      },
      handler_score: column => {
        column["cellRenderer"] = ({ row }) =>
          stars((row as TicketRating).handler_score);
      },
      tags: column => {
        column["cellRenderer"] = ({ row }) =>
          h(
            "span",
            { class: "flex flex-wrap gap-1" },
            ((row as TicketRating).tags ?? []).map(tag =>
              h(ElTag, { size: "small", effect: "plain" }, () =>
                t(`ticketflow.rating.tagValue.${tag}`)
              )
            )
          );
      }
    });

  const operationButtonsProps = shallowRef<OperationProps>({
    hideDetail: false
  });

  return {
    api,
    auth,
    summary,
    summaryLoading,
    loadSummary,
    listColumnsFormat,
    operationButtonsProps
  };
}
