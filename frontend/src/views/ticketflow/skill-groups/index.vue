<script lang="ts" setup>
import { ref } from "vue";
import CategoryRoutes from "./components/CategoryRoutes.vue";
import { useSkillGroups } from "./utils/hook";

defineOptions({
  name: "TicketFlowSkillGroups" // 必须定义，用于菜单自动匹配组件
});

const tableRef = ref();
const {
  api,
  auth,
  groups,
  listColumnsFormat,
  operationButtonsProps,
  onSearchComplete
} = useSkillGroups(tableRef);
</script>

<template>
  <div class="main flex flex-col gap-4">
    <CategoryRoutes :groups="groups" :can-edit="Boolean(auth.categoryRoute)" />
    <RePlusPage
      ref="tableRef"
      :api="api"
      :auth="auth"
      locale-name="ticketflow.skillGroup"
      :selection="false"
      :listColumnsFormat="listColumnsFormat"
      :operationButtonsProps="operationButtonsProps"
      @search-complete="onSearchComplete"
    />
  </div>
</template>
