import type { Component } from "vue";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import type { BusinessAccount } from "@/api/ticketflow/accounts";

type RowButtonType = "primary" | "warning" | "danger";

/** 账号行内按钮：链接样式 + 图标 + 提示，点击时把行数据收窄为业务账号 */
export function rowButton(
  t: (key: string) => string,
  code: string,
  type: RowButtonType,
  icon: Component,
  tip: string,
  index: number,
  show: boolean,
  onClick: (row: BusinessAccount) => unknown
) {
  return {
    code,
    props: { type, icon: useRenderIcon(icon), link: true },
    tooltip: { content: t(tip) },
    onClick: ({ row }: { row: unknown }) => onClick(row as BusinessAccount),
    index,
    show
  };
}
