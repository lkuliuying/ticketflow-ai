<script lang="ts" setup>
import { ref } from "vue";
import { useArticles } from "./utils/hook";

defineOptions({
  name: "TicketFlowKnowledge" // 必须定义，用于菜单自动匹配组件
});

const tableRef = ref();
const {
  api,
  auth,
  listColumnsFormat,
  operationButtonsProps,
  tableBarButtonsProps,
  onSearchComplete
} = useArticles(tableRef);
</script>

<template>
  <RePlusPage
    ref="tableRef"
    :api="api"
    :auth="auth"
    locale-name="ticketflow.kb"
    :selection="false"
    :listColumnsFormat="listColumnsFormat"
    :operationButtonsProps="operationButtonsProps"
    :tableBarButtonsProps="tableBarButtonsProps"
    @search-complete="onSearchComplete"
  />
</template>
