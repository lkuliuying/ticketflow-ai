<script lang="ts" setup>
import { computed, onActivated, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
import { Plus, Reading, Tickets, User } from "@element-plus/icons-vue";
import { useUserStoreHook } from "@/store/modules/user";
import { usePageAuth } from "@/router/utils";
import type { TicketItem } from "@/api/ticketflow/tickets";
import type { ArticleItem } from "@/api/ticketflow/knowledge";
import { openTicketDetail } from "@/views/ticketflow/tickets/utils/ticketDetailDrawer";
import { openArticleDetail } from "@/views/ticketflow/knowledge/utils/articleDetailDrawer";
import ReSkeleton from "@/components/ReSkeleton";
import WorkbenchStats from "./components/WorkbenchStats.vue";
import RecentTickets from "./components/RecentTickets.vue";
import LatestArticles from "./components/LatestArticles.vue";
import { useWorkbench } from "./useWorkbench";
import { cardsFor, workbenchRole } from "./cards";
import { greetingKey } from "./greeting";

defineOptions({
  name: "Welcome"
});

/** 站点根目录的 Logo（public 静态资源，运行时按路径引用，不经构建导入） */
const LOGO_URL = "/logo.svg";
const TICKETS_PATH = "/ticketflow/tickets/index";
const KNOWLEDGE_PATH = "/ticketflow/knowledge/index";

const { t, locale } = useI18n();
const router = useRouter();
const user = useUserStoreHook();
const ticketAuth = usePageAuth("TicketFlowTickets");
const articleAuth = usePageAuth("TicketFlowKnowledge");
const { dashboard, tickets, articles, loading, loaded, stats, reload } =
  useWorkbench({
    tickets: () => Boolean(ticketAuth.list),
    articles: () => Boolean(articleAuth.list)
  });

/** 视角由看板的指派维度推断：管理员突出待分配，技术员突出我的待办，员工突出建单 */
const role = computed(() => workbenchRole(dashboard.value));
const cards = computed(() => cardsFor(role.value));
/** 看板返回前不渲染随视角变化的卡片与入口，避免先闪出员工视角再跳变；看板失败时按员工视角兜底 */
const roleReady = computed(() => dashboard.value !== null || loaded.value);

const displayName = computed(() => user.nickname || user.username || "");
/** 日期用浏览器内置的本地化格式（含星期），随界面语言切换 */
const today = computed(() =>
  new Intl.DateTimeFormat(locale.value === "en" ? "en-US" : "zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long"
  }).format(new Date())
);

function goTickets(query: Record<string, string> = {}) {
  router.push({ path: TICKETS_PATH, query });
}

function openTicket(ticket: TicketItem) {
  openTicketDetail(ticket, { onChanged: reload });
}

function openArticle(article: ArticleItem) {
  openArticleDetail(article);
}

/** 页面被缓存时，从工单页等处返回首页要刷新计数；首次挂载由 onMounted 负责 */
let mounted = false;
onMounted(async () => {
  await reload();
  mounted = true;
});
onActivated(() => {
  if (mounted) reload();
});
</script>

<template>
  <div class="workbench flex flex-col gap-4">
    <el-card shadow="never" body-class="p-6!">
      <div
        class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
      >
        <div class="flex items-center gap-4">
          <img :src="LOGO_URL" alt="" class="size-12" />
          <div>
            <h2 class="workbench-title" data-testid="workbench-greeting">
              {{ t(greetingKey(dayjs().hour()), { name: displayName }) }}
            </h2>
            <p class="text-sm text-fg-muted mt-1">
              {{ today }} · {{ t("workbench.subtitle") }}
            </p>
          </div>
        </div>
        <div v-if="roleReady" class="flex flex-wrap gap-2">
          <el-button
            v-if="ticketAuth.create && role === 'requester'"
            type="primary"
            :icon="Plus"
            data-testid="workbench-create"
            @click="goTickets({ create: '1' })"
          >
            {{ t("workbench.createTicket") }}
          </el-button>
          <el-button
            v-if="role === 'admin'"
            type="primary"
            :icon="User"
            data-testid="workbench-unassigned"
            @click="goTickets({ assignment: 'unassigned' })"
          >
            {{ t("workbench.unassignedTickets") }}
          </el-button>
          <el-button
            v-if="role === 'agent'"
            type="primary"
            :icon="Tickets"
            data-testid="workbench-current"
            @click="goTickets({ assignment: 'current' })"
          >
            {{ t("workbench.myTodo") }}
          </el-button>
          <el-button :icon="Tickets" @click="goTickets()">
            {{
              role === "admin"
                ? t("workbench.allTickets")
                : t("workbench.myTickets")
            }}
          </el-button>
          <el-button :icon="Reading" @click="router.push(KNOWLEDGE_PATH)">
            {{ t("workbench.knowledge") }}
          </el-button>
        </div>
      </div>
    </el-card>

    <WorkbenchStats
      v-if="roleReady"
      :stats="stats"
      :cards="cards"
      @open="goTickets"
    />
    <ReSkeleton v-else variant="fill" class="h-20!" />

    <div class="grid gap-4 lg:grid-cols-3">
      <RecentTickets
        class="lg:col-span-2"
        :tickets="tickets"
        :loading="loading"
        @open="openTicket"
        @more="goTickets()"
      />
      <LatestArticles
        :articles="articles"
        :loading="loading"
        @open="openArticle"
        @more="router.push(KNOWLEDGE_PATH)"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.workbench-title {
  margin: 0;
  font-size: var(--font-size-xl);
  font-weight: 600;
  color: var(--el-text-color-primary);
}
</style>
