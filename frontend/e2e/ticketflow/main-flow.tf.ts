import { expect, test } from "@playwright/test";
import {
  choose,
  closeDrawer,
  loginAs,
  openTicket,
  openTickets,
  transition
} from "./support";

/**
 * 工单主流程冒烟：建单（按分类路由自动派给技术员）→ 接单 → AI 分析采纳与回复建议 → 提交验收
 * → 确认解决并在弹出的评价框里评价 → 技术员在“我的评价”看到评价 → 转存知识库草稿。
 * 每次运行用唯一标题，互不干扰；只读写本次新建的工单、评价与草稿。
 */
// 毫秒时间戳加随机后缀，同一秒内连续或并行运行也不会撞标题
const title = `冒烟工单 ${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}-${Math.random().toString(36).slice(2, 6)}`;
const description = "E2E 冒烟：月度报表权限同步后无法打开，请协助排查。";
// 评价补充带上本次标题，便于在“我的评价”里唯一定位
const ratingComment = `评价 ${title}`;

test.describe.configure({ mode: "serial" });

test("提交人建单", async ({ page }) => {
  await loginAs(page, "tf_requester");
  await openTickets(page);
  await page.getByRole("button", { name: "新建工单" }).click();
  const dialog = page.locator(".el-dialog", { hasText: "新建工单" }).last();
  await dialog.getByRole("textbox", { name: "标题" }).fill(title);
  await dialog.getByRole("textbox", { name: "描述" }).fill(description);
  const select = (label: string) =>
    dialog
      .locator(".el-form-item", { hasText: label })
      .locator(".el-select")
      .first();
  await choose(page, select("分类"), "权限");
  await choose(page, select("优先级"), "P2");
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page.locator(".el-table__row", { hasText: title }).first()
  ).toBeVisible();
});

test("技术员接单，AI 分析采纳并生成回复", async ({ page }) => {
  await loginAs(page, "tf_agent");
  const drawer = await openTicket(page, title);
  await transition(page, drawer, "接单");
  await expect(drawer.getByTestId("ticket-header")).toContainText("处理中");

  const panel = drawer.getByTestId("ticket-ai-panel");
  await panel.getByTestId("ai-analyze").click();
  await expect(panel.getByTestId("ai-adopt")).toBeEnabled({ timeout: 30_000 });
  await panel.getByTestId("ai-adopt").click();
  await expect(drawer.getByTestId("ticket-ai-summary")).toBeVisible();
  await expect(drawer.getByTestId("ticket-timeline")).toContainText(
    "采纳 AI 建议"
  );

  await panel.getByTestId("ai-generate").click();
  const fill = panel.getByTestId("ai-fill");
  await expect(fill).toBeEnabled({ timeout: 60_000 });
  const suggestion = (await panel.getByTestId("ai-reply-text").innerText())
    .trim()
    .slice(0, 12);
  expect(suggestion.length).toBeGreaterThan(0);
  await fill.click();

  // AI 建议填入实时排查会话的输入框（对外回复已统一走会话），发送后出现在消息列表
  // el-input 把 data-testid 透传到 textarea 本身
  const input = drawer.getByTestId("ticket-chat-input");
  await expect(input).toHaveValue(/.+/);
  await drawer.getByTestId("ticket-chat-send").click();
  await expect(drawer.getByTestId("ticket-chat-messages")).toContainText(
    suggestion
  );

  await transition(page, drawer, "提交验收");
  await expect(drawer.getByTestId("ticket-header")).toContainText("待验收");
  await closeDrawer(page);
});

test("提交人确认解决，关闭后弹出评价并提交", async ({ page }) => {
  await loginAs(page, "tf_requester");
  const drawer = await openTicket(page, title);
  await expect(drawer.getByTestId("ticket-ai-panel")).toHaveCount(0);
  await transition(page, drawer, "确认解决");
  await expect(drawer.getByTestId("ticket-header")).toContainText("已关闭");

  // 关闭后自动弹出评价框：问题已解决、满意度与处理人评分各给 5 星
  const dialog = page.locator(".el-dialog", { hasText: "评价一下这次处理" });
  await expect(dialog).toBeVisible();
  await dialog.getByText("已解决", { exact: true }).click();
  const rates = dialog.locator(".el-rate");
  await rates.nth(0).locator(".el-rate__item").nth(4).click();
  await rates.nth(1).locator(".el-rate__item").nth(4).click();
  await dialog.getByPlaceholder("说说这次处理的体验").fill(ratingComment);
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();
  await expect(drawer.getByTestId("ticket-rating")).toContainText(
    ratingComment
  );
  await closeDrawer(page);
});

test("技术员在我的评价里看到这条评价", async ({ page }) => {
  await loginAs(page, "tf_agent");
  await page.goto("/#/ticketflow/ratings/mine/index");
  await expect(
    page.locator(".el-table__row", { hasText: ratingComment }).first()
  ).toBeVisible();
});

test("技术员把已关闭工单转存为知识库草稿", async ({ page }) => {
  await loginAs(page, "tf_agent");
  const drawer = await openTicket(page, title);
  await drawer.getByTestId("ticket-archive").click();
  const editor = page.locator(".el-dialog", {
    hasText: "从工单转存知识库草稿"
  });
  // 预填：标题、分类来自工单，标签来自刚采纳的 AI 建议
  await expect(editor.locator("input").first()).toHaveValue(title);
  await expect(editor.locator("textarea")).toHaveValue(/E2E 冒烟/);
  await editor.getByRole("button", { name: "保存" }).click();
  await expect(editor).toBeHidden();
  await expect(drawer.getByTestId("ticket-archive")).toHaveCount(0);
});
