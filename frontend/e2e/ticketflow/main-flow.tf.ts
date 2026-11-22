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
 * 工单主流程冒烟：建单 → 接单 → AI 分析采纳与回复建议 → 提交验收 → 确认解决 → 转存知识库草稿。
 * 每次运行用唯一标题，互不干扰；只读写本次新建的工单与草稿。
 */
const title = `冒烟工单 ${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}`;
const description = "E2E 冒烟：月度报表权限同步后无法打开，请协助排查。";

test.describe.configure({ mode: "serial" });

test("提交人建单", async ({ page }) => {
  await loginAs(page, "tf_requester");
  await openTickets(page);
  await page.getByRole("button", { name: "新增" }).click();
  const dialog = page.locator(".el-dialog", { hasText: "新增" }).last();
  await dialog.getByPlaceholder("请输入标题").fill(title);
  await dialog.getByPlaceholder("请输入描述").fill(description);
  await choose(page, dialog.locator(".el-select").nth(0), "权限");
  await choose(page, dialog.locator(".el-select").nth(1), "P2");
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page.locator(".el-table__row", { hasText: title }).first()
  ).toBeVisible();
});

test("客服接单，AI 分析采纳并生成回复", async ({ page }) => {
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

  const reply = drawer.getByTestId("ticket-reply");
  await expect(reply.locator("textarea")).toHaveValue(/.+/);
  await reply.getByRole("button", { name: "发送" }).click();
  await expect(drawer.getByTestId("ticket-timeline")).toContainText(suggestion);

  await transition(page, drawer, "提交验收");
  await expect(drawer.getByTestId("ticket-header")).toContainText("待验收");
  await closeDrawer(page);
});

test("提交人确认解决，看不到 AI 面板", async ({ page }) => {
  await loginAs(page, "tf_requester");
  const drawer = await openTicket(page, title);
  await expect(drawer.getByTestId("ticket-ai-panel")).toHaveCount(0);
  await transition(page, drawer, "确认解决");
  await expect(drawer.getByTestId("ticket-header")).toContainText("已关闭");
});

test("客服把已关闭工单转存为知识库草稿", async ({ page }) => {
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
