<script lang="ts" setup>
import { useTickets } from "./utils/hook";

defineOptions({
  name: "TicketFlowTickets" // 必须定义，用于菜单自动匹配组件
});

const { api, auth, listColumnsFormat } = useTickets();
</script>

<template>
  <RePlusPage
    :api="api"
    :auth="auth"
    locale-name="ticketflow"
    :selection="false"
    :listColumnsFormat="listColumnsFormat"
  />
</template>
