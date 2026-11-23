<script lang="ts" setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import {
  skillGroupApi,
  type CategoryRoute,
  type SkillGroup
} from "@/api/ticketflow/accounts";

/**
 * 分类路由：每个工单分类选择一个技能组，新建工单按此路由并在组内自动派单；
 * 清空表示走默认组。改动即保存，失败时回退到保存前的值。
 */
defineOptions({ name: "TicketFlowCategoryRoutes" });

const props = defineProps<{ groups: SkillGroup[]; canEdit: boolean }>();

const { t, te } = useI18n();
const routes = ref<CategoryRoute[]>([]);
const loading = ref(false);
const saving = ref<string | null>(null);

const activeGroups = computed(() => props.groups.filter(g => g.is_active));
const defaultGroup = computed(() => props.groups.find(g => g.is_default));

async function load() {
  loading.value = true;
  const res = await skillGroupApi.categoryRoutes().catch(() => null);
  loading.value = false;
  if (res && isSuccess(res)) routes.value = res.data ?? [];
}

async function change(route: CategoryRoute, value: string | null) {
  const previous = route.skill_group;
  route.skill_group = value;
  saving.value = route.category;
  const res = await skillGroupApi
    .updateRoute(route.category, value)
    .catch(() => null);
  saving.value = null;
  if (res && isSuccess(res)) {
    Object.assign(route, res.data);
    message(t("ticketflow.skillGroup.routeSaved"), { type: "success" });
  } else {
    route.skill_group = previous;
  }
}

function categoryLabel(route: CategoryRoute) {
  const key = `ticketflow.categoryValue.${route.category}`;
  return te(key) ? t(key) : route.label || route.category;
}

defineExpose({ load, change });
onMounted(load);
</script>

<template>
  <el-card shadow="never" data-testid="category-routes">
    <template #header>
      <div class="flex flex-col">
        <span class="font-medium">{{ t("ticketflow.skillGroup.routes") }}</span>
        <span class="text-xs text-fg-muted mt-1">
          {{
            t("ticketflow.skillGroup.routesHint", {
              name: defaultGroup?.name ?? "—"
            })
          }}
        </span>
      </div>
    </template>
    <div v-loading="loading" class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div
        v-for="route in routes"
        :key="route.category"
        class="flex items-center gap-3"
        :data-testid="`route-${route.category}`"
      >
        <span class="w-16 shrink-0 text-sm">{{ categoryLabel(route) }}</span>
        <el-select
          :model-value="route.skill_group"
          class="flex-1"
          clearable
          :disabled="!canEdit"
          :loading="saving === route.category"
          :placeholder="t('ticketflow.skillGroup.useDefault')"
          @update:model-value="
            (value: string | null | undefined) => change(route, value ?? null)
          "
        >
          <el-option
            v-for="group in activeGroups"
            :key="group.pk"
            :label="group.name"
            :value="group.pk"
          />
        </el-select>
      </div>
    </div>
  </el-card>
</template>
