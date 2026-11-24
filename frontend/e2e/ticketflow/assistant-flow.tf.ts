import { expect, test } from "@playwright/test";
import { closeDrawer, loginAs, openTicket } from "./support";

/**
 * AI 助手冒烟：员工从工作台进入 → 新建对话提问（流式回答带知识引用）→ 点赞
 * → 转人工提单（AI 草稿预填）→ 会话转为只读；管理员在工单里看只读对话、在 AI 反馈页看到统计。
 * 回答来自交付栈配置的模型（Mock 或真实模型），只断言结构，不断言具体措辞。
 */
const stamp = `${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}-${Math.random().toString(36).slice(2, 6)}`;
const question = `VPN 连不上怎么办？（冒烟 ${stamp}）`;
const ticketTitle = `AI 转人工冒烟 ${stamp}`;

test.describe.configure({ mode: "serial" });

test("员工向 AI 提问、点赞并转人工提单", async ({ page }) => {
  await loginAs(page, "tf_requester");
  await page.getByTestId("workbench-assistant").click();
  await expect(page).toHaveURL(/ticketflow\/assistant\/index/);

  // 进入页面会自动选中最近的会话：等新建返回、切到新会话后再输入，避免输进旧会话
  const created = page.waitForResponse(
    r =>
      r.request().method() === "POST" &&
      /\/api\/assistant\/sessions\/?$/.test(new URL(r.url()).pathname)
  );
  await page.getByTestId("session-create").click();
  const session = (await (await created).json()).data as { pk: string };
  await expect(page.getByTestId(`session-${session.pk}`)).toHaveAttribute(
    "aria-current",
    "true"
  );
  const chat = page.getByTestId("assistant-chat");
  await expect(chat).toBeVisible();
  await chat.getByTestId("assistant-input").fill(question);
  await chat.getByTestId("assistant-send").click();

  // 流结束、服务端记录刷新后，回答下方才出现评价按钮
  const answer = chat.getByTestId("assistant-answer").last();
  await expect(answer.getByTestId("answer-feedback")).toBeVisible({
    timeout: 120_000
  });
  await expect(answer).not.toBeEmpty();
  await answer.getByTestId("vote-up").click();
  await expect(answer.getByTestId("vote-up")).toHaveAttribute(
    "aria-pressed",
    "true"
  );

  await chat.getByTestId("assistant-handoff").click();
  const dialog = page.locator(".el-dialog", { hasText: "转人工提单" }).last();
  await expect(dialog).toBeVisible({ timeout: 120_000 });
  const titleInput = dialog.locator("input").first();
  await expect(titleInput).not.toHaveValue("");
  await expect(dialog.locator("textarea")).not.toHaveValue("");
  await titleInput.fill(ticketTitle);
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();

  // 建单成功会打开新工单详情；关掉后会话应已转为只读
  await expect(page.locator(".el-drawer").last()).toContainText(ticketTitle);
  await closeDrawer(page);
  await expect(chat.getByTestId("assistant-handed-off")).toBeVisible();
  await expect(chat.getByTestId("assistant-input")).toHaveCount(0);
});

test("管理员在工单里查看 AI 对话，并在 AI 反馈页看到转人工", async ({
  page
}) => {
  await loginAs(page, "tf_admin");
  const drawer = await openTicket(page, ticketTitle);
  await drawer.getByTestId("ticket-assistant-transcript").click();
  const transcript = page.getByTestId("assistant-transcript");
  await expect(transcript).toBeVisible();
  await expect(transcript.getByTestId("assistant-question")).toContainText(
    stamp
  );
  await expect(transcript.getByTestId("answer-feedback")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await closeDrawer(page);

  await page.goto("/#/ticketflow/assistant/feedback/index");
  await expect(page.getByTestId("assistant-summary-sessions")).toBeVisible();
  await page.getByRole("tab", { name: "转人工会话" }).click();
  await expect(
    page.getByTestId("assistant-handoffs").locator(".el-table__row").first()
  ).toBeVisible();
});
