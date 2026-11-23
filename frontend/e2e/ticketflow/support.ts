import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";

export type Role = "tf_requester" | "tf_agent" | "tf_admin";

/** 演示账号口令：由部署的种子脚本生成在本机文件里，用例只读取、不打印 */
function loadAccounts(): Record<string, string> {
  // 默认路径相对本文件而不是执行目录，从仓库根目录用 -c 指定配置运行时也能找到
  const file =
    process.env.TF_E2E_ACCOUNTS ||
    resolve(import.meta.dirname, "../../../deploy/.accounts.local.json");
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

/**
 * 在列表中找到工单并打开详情抽屉：先用列表的“关键字”筛选到这张工单，
 * 与列表数据量、排序和分页无关（只看首屏时，工单多了会被挤到后面的页）。
 */
export async function openTicket(page: Page, title: string): Promise<Locator> {
  await openTickets(page);
  // “关键字”默认收在搜索区的“展开”里；标签带冒号，按前缀匹配
  const keyword = page.getByRole("textbox", { name: /^关键字/ });
  const expand = page.getByRole("link", { name: "展开", exact: true });
  if (!(await keyword.isVisible()) && (await expand.isVisible())) {
    await expand.click();
  }
  await keyword.fill(title);
  await keyword.press("Enter");
  const rows = page.locator(".el-table__row");
  const row = rows.filter({ hasText: title }).first();
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

/**
 * 选择 el-select 的选项：只在这个下拉框自己弹出的列表里找。
 * 输入框的 aria-controls 指向它的选项列表，页面上同时存在别的下拉层或同名选项时不会点错。
 */
export async function choose(page: Page, select: Locator, option: string) {
  const combobox = select.getByRole("combobox");
  await select.click();
  await expect(combobox).toHaveAttribute("aria-expanded", "true");
  const listId = await combobox.getAttribute("aria-controls");
  expect(listId, "下拉框缺少 aria-controls").toBeTruthy();
  const list = page.locator(`[id="${listId}"]`);
  await list.getByRole("option", { name: option, exact: true }).click();
  await expect(combobox).toHaveAttribute("aria-expanded", "false");
}
