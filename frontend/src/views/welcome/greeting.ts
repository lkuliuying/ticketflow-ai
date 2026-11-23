/** 按小时取问候语词条：5–11 点上午好，12–17 点下午好，其余晚上好 */
export function greetingKey(hour: number) {
  if (hour >= 5 && hour < 12) return "workbench.greeting.morning";
  if (hour >= 12 && hour < 18) return "workbench.greeting.afternoon";
  return "workbench.greeting.evening";
}
