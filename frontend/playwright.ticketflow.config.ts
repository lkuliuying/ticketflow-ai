import { defineConfig } from "@playwright/test";

/**
 * TicketFlow 冒烟：针对**运行中的**交付栈（网关）或联调环境，不自起后端与前端。
 *
 * - TF_E2E_BASE_URL   被测地址，默认交付栈网关 http://127.0.0.1:8080
 *                     （联调：http://localhost:8848，需前端 dev server、DRF :8896、AI 服务 :8897 在跑）
 * - TF_E2E_ACCOUNTS   账号口令文件，默认仓库根目录 deploy/.accounts.local.json（不进 Git）
 * - TF_E2E_CHANNEL    浏览器通道（如 chrome / msedge），本机 Playwright 浏览器与版本不匹配时使用已安装的浏览器
 *
 * 用例文件后缀为 `.tf.ts`，不会被上游 playwright.config.ts（`*.e2e.ts`）收集。
 */
export default defineConfig({
  testDir: "./e2e/ticketflow",
  testMatch: /.*\.tf\.ts/,
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"]],
  outputDir: "./test-results/ticketflow",
  use: {
    baseURL: process.env.TF_E2E_BASE_URL || "http://127.0.0.1:8080",
    locale: "zh-CN",
    browserName: "chromium",
    channel: process.env.TF_E2E_CHANNEL || undefined,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 120_000
  }
});
