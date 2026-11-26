import { deflateSync } from "node:zlib";
import { expect, test, type Browser, type Page } from "@playwright/test";
import { choose, loginAs, openTicket, transition } from "./support";

/**
 * 实时排查会话冒烟：员工建单时附截图 → 技术员接单 → 技术员发文字与视频，
 * 员工停留在详情页、不刷新即收到推送 → 员工看到附件缩略图，视频点击后才加载。
 * 员工与技术员各用独立浏览器上下文，互不共享登录态。
 */
const stamp = `${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}-${Math.random().toString(36).slice(2, 6)}`;
const title = `会话冒烟 ${stamp}`;
const greeting = `技术员已接单，请补充报错截图（${stamp}）`;

test.describe.configure({ mode: "serial" });

/** 32×32 纯色 PNG：服务端按文件头校验图片，不能用随意的字节 */
function pngBuffer(): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc32 = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (tag: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(tag, "ascii"), data]);
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(32, 0);
  header.writeUInt32BE(32, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(32 * 3, 0x60)]);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(Array(32).fill(row)))),
    chunk("IEND", Buffer.alloc(0))
  ]);
}

/** 最小 MP4 头（ftyp + free）：满足服务端的扩展名与文件头校验 */
function mp4Buffer(): Buffer {
  const ftyp = Buffer.concat([
    Buffer.from([0, 0, 0, 24]),
    Buffer.from("ftypisom", "ascii"),
    Buffer.from([0, 0, 2, 0]),
    Buffer.from("isomiso2", "ascii")
  ]);
  const free = Buffer.concat([
    Buffer.from([0, 0, 4, 0]),
    Buffer.from("free", "ascii"),
    Buffer.alloc(1016)
  ]);
  return Buffer.concat([ftyp, free]);
}

async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext();
  return context.newPage();
}

test("员工建单时附带截图", async ({ page }) => {
  await loginAs(page, "tf_requester");
  await page.goto("/#/ticketflow/tickets/index");
  await page.getByRole("button", { name: "新建工单" }).click();
  const dialog = page.locator(".el-dialog", { hasText: "新建工单" }).last();
  await dialog.getByRole("textbox", { name: "标题" }).fill(title);
  await dialog
    .getByRole("textbox", { name: "描述" })
    .fill("E2E 会话冒烟：报表页面打不开，附截图。");
  await choose(
    page,
    dialog.locator(".el-form-item", { hasText: "分类" }).locator(".el-select"),
    "权限"
  );
  await dialog.getByTestId("create-ticket-file-input").setInputFiles({
    name: "screen.png",
    mimeType: "image/png",
    buffer: pngBuffer()
  });
  await expect(
    dialog.getByTestId("create-ticket-images").locator("img")
  ).toHaveCount(1);
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();
});

test("技术员接单后发消息，员工不刷新即收到；视频点击后才加载", async ({
  browser
}) => {
  const employee = await newPage(browser);
  const agent = await newPage(browser);

  // 员工先打开详情并停留：接单前会话为锁定态
  await loginAs(employee, "tf_requester");
  const employeeDrawer = await openTicket(employee, title);
  const gallery = employeeDrawer.getByTestId("ticket-attachments-gallery");
  await expect(gallery.locator("img")).toHaveCount(1);
  await expect(employeeDrawer.getByTestId("ticket-chat-locked")).toBeVisible();

  // 技术员接单并发文字、视频
  await loginAs(agent, "tf_agent");
  const agentDrawer = await openTicket(agent, title);
  await transition(agent, agentDrawer, "接单");
  const composer = agentDrawer.getByTestId("ticket-chat-composer");
  await expect(composer).toBeVisible();
  await agentDrawer.getByTestId("ticket-chat-input").fill(greeting);
  await agentDrawer.getByTestId("ticket-chat-send").click();
  await composer.locator('input[type="file"][accept^="video"]').setInputFiles({
    name: "steps.mp4",
    mimeType: "video/mp4",
    buffer: mp4Buffer()
  });
  await expect(
    agentDrawer
      .getByTestId("ticket-chat-messages")
      .getByTestId("ticket-chat-item")
  ).toHaveCount(2);

  // 员工页面未刷新：WS 推送消息，接单后的状态推送解锁输入区
  const messages = employeeDrawer.getByTestId("ticket-chat-messages");
  await expect(messages).toContainText(greeting, { timeout: 20_000 });
  await expect(
    employeeDrawer.getByTestId("ticket-chat-composer")
  ).toBeVisible();

  // 视频不预取：先出现“加载视频”按钮，点击后才渲染 <video>
  const loadVideo = messages.getByTestId("ticket-chat-load-video");
  await expect(loadVideo).toBeVisible({ timeout: 20_000 });
  await expect(messages.locator("video")).toHaveCount(0);
  await loadVideo.click();
  await expect(messages.locator("video")).toHaveCount(1);

  await employee.context().close();
  await agent.context().close();
});
