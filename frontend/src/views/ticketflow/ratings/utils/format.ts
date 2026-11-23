/** 平均分：两位小数，无评价时显示 — */
export function formatScore(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}

/** 解决率：后端给 0~1 比例，显示为百分比（一位小数），无评价时显示 — */
export function formatPercent(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}
