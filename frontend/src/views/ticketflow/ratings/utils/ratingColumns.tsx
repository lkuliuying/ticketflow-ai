import { computed, h, type Ref } from "vue";
import { ElInput, ElLink, ElRate, ElTag } from "element-plus";
import {
  formatPageColumns,
  type PageColumn,
  type PageTableColumn
} from "@/components/RePlusPage";
import type { RatingSummary, TicketRating } from "@/api/ticketflow/ratings";
import { openRelatedTicket } from "./ratingDetailDialog";

type Translate = (key: string) => string;

export type RatingsMode = "mine" | "stats";

const stars = (value: number) =>
  h(ElRate, { modelValue: value, disabled: true, size: "small" });

export function buildRatingListColumns(options: {
  t: Translate;
  canViewTicket: boolean;
  fixedHandlerName?: string;
}) {
  const { t, canViewTicket, fixedHandlerName } = options;
  return (columns: PageTableColumn[]) =>
    formatPageColumns(columns, {
      ticket_number: column => {
        column["cellRenderer"] = ({ row }) => {
          const item = row as TicketRating;
          if (!canViewTicket) return h("span", item.ticket_number);
          return h(
            ElLink,
            {
              type: "primary",
              underline: false,
              onClick: () =>
                void openRelatedTicket(item.ticket_id, item.ticket_number)
            },
            () => item.ticket_number
          );
        };
      },
      handler_name: column => {
        column["cellRenderer"] = ({ row }) => {
          const item = row as TicketRating;
          return h("span", fixedHandlerName || item.handler_name || "—");
        };
      },
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
        column["cellRenderer"] = ({ row }) => {
          const tags = (row as TicketRating).tags ?? [];
          if (!tags.length) return h("span", { class: "text-fg-muted" }, "—");
          return h(
            "span",
            { class: "flex flex-wrap gap-1" },
            tags.map(tag =>
              h(ElTag, { size: "small", effect: "plain" }, () =>
                t(`ticketflow.rating.tagValue.${tag}`)
              )
            )
          );
        };
      },
      comment: column => {
        column["cellRenderer"] = ({ row }) => {
          const text = ((row as TicketRating).comment ?? "").trim();
          return h("span", { class: text ? "" : "text-fg-muted" }, text || "—");
        };
      }
    });
}

export function buildRatingSearchColumns(options: {
  t: Translate;
  mode: RatingsMode;
  fixedHandlerName: string;
  summary: Ref<RatingSummary | null>;
}) {
  const { t, mode, fixedHandlerName, summary } = options;
  const handlerOptions = computed(() =>
    (summary.value?.by_handler ?? [])
      .filter(item => item.handler_id != null)
      .map(item => ({
        label: item.handler_name || `#${item.handler_id}`,
        value: item.handler_id as number
      }))
  );

  return (columns: PageColumn[]) =>
    columns.map(column => {
      if (column.prop !== "handler_id") return column;
      if (mode === "mine") {
        return {
          ...column,
          valueType: "input",
          renderField: () =>
            h(ElInput, {
              modelValue: fixedHandlerName,
              disabled: true,
              "data-testid": "my-ratings-handler-fixed"
            })
        } as PageColumn;
      }
      return {
        ...column,
        valueType: "select",
        options: handlerOptions,
        fieldProps: {
          clearable: true,
          filterable: true,
          placeholder: t("ticketflow.rating.selectHandler")
        }
      } as PageColumn;
    });
}
