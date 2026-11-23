/**
 * 站点对外链接：about 页、登录页版权与布局页脚共用。
 * 平台配置（public/platform-config.json）不承载链接类信息，这里以具名常量收敛，
 * 避免仓库地址在视图里四处散落。
 */
const REPO = "https://github.com/lkuliuying/ticketflow-ai";

export const SITE_LINKS = {
  /** 本项目仓库（页脚与登录页版权署名链接） */
  repo: REPO,
  /** 使用文档：仓库首页 README（快速开始、架构、演示账号） */
  docs: `${REPO}#readme`,
  /** 部署说明 */
  deployDocs: `${REPO}/blob/main/deploy/README.md`,
  /** 上游前端底座（二次开发来源，按上游许可证保留致谢） */
  upstreamClient: "https://github.com/nineaiyu/xadmin-client",
  /** 上游后端底座 */
  upstreamServer: "https://github.com/nineaiyu/xadmin-server"
} as const;
