import reHumanCheck from "./src/index.vue";
import { withInstall } from "@pureadmin/utils";

/** 交互式人机校验：obtain() 返回一次性 captcha_ticket */
export const ReHumanCheck = withInstall(reHumanCheck);
export { HumanCheckCancelled } from "./src/useHumanCheck";

export default ReHumanCheck;
