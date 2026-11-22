import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";

export type Role = "tf_requester" | "tf_agent" | "tf_admin";

/** 演示账号口令：由部署的种子脚本生成在本机文件里，用例只读取、不打印 */
function loadAccounts(): Record<string, string> {
  const file = resolve(
    process.env.TF_E2E_ACCOUNTS ?? "../deploy/.accounts.local.json"
  );
  const raw = JSON.parse(readFileSync(file, "utf-8")) as Record<
    string,
    string | { password?: string }
  >;
  return Object.fromEntries(
    Object.entries(raw).map(([name, value]) => [
      name,
      typeof value === "string" ? value : String(value?.password ?? "")
    ])
  );
}

const accounts = loadAccounts();

/** 表单登录；登录页的验证码与临时令牌在演示环境关闭 */
export async function loginAs(page: Page, role: Role) {
  const password = accounts[role];
  expect(password, `账号文件缺少 ${role}`).toBeTruthy();
  await page.context().clearCookies();
  await page.goto("/#/login");
  const account = page.getByPlaceholder("账号");
  await account.waitFor({ state: "visible" });
  await account.fill(role);
  await page.getByPlaceholder("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).not.toHaveURL(/#\/login/, { timeout: 30_000 });
}

export async function openTickets(page: Page) {
  await page.goto("/#/ticketflow/tickets/index");
  await expect(page.getByTestId("ticket-dashboard")).toBeVisible();
}

/** 在列表中按标题找到工单并打开详情抽屉 */
export async function openTicket(page: Page, title: string): Promise<Locator> {
  await openTickets(page);
  const row = page.locator(".el-table__row", { hasText: title }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "工单详情" }).click();
  const drawer = page.locator(".el-drawer").last();
  await expect(drawer.getByTestId("ticket-header")).toBeVisible();
  return drawer;
}

export async function closeDrawer(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page.locator(".el-drawer")).toHaveCount(0);
}

/** 点击流转按钮并在备注弹窗中确认；确认按钮文字与动作同名 */
export async function transition(page: Page, drawer: Locator, action: string) {
  await drawer
    .getByTestId("ticket-transitions")
    .getByRole("button", { name: action, exact: true })
    .click();
  const box = page.locator(".el-message-box");
  await expect(box).toBeVisible();
  await box.getByRole("button", { name: action, exact: true }).click();
  await expect(box).toBeHidden();
}

/** 选择 el-select 的选项：点开下拉后按可见文字选中 */
export async function choose(page: Page, select: Locator, option: string) {
  await select.click();
  await page
    .locator(".el-select-dropdown:visible .el-select-dropdown__item", {
      hasText: option
    })
    .first()
    .click();
}
