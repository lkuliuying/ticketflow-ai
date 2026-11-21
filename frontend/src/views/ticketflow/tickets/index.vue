<script lang="ts" setup>
import { ref } from "vue";
import { useTickets } from "./utils/hook";

defineOptions({
  name: "TicketFlowTickets" // 必须定义，用于菜单自动匹配组件
});

const tableRef = ref();
const { api, auth, listColumnsFormat, operationButtonsProps } =
  useTickets(tableRef);
</script>

<template>
  <RePlusPage
    ref="tableRef"
    :api="api"
    :auth="auth"
    locale-name="ticketflow"
    :selection="false"
    :listColumnsFormat="listColumnsFormat"
    :operationButtonsProps="operationButtonsProps"
  />
</template>
