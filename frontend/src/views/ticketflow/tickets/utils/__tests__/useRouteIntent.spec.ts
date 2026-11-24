import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import {
  parseRouteIntent,
  useRouteIntent,
  withoutIntent
} from "../useRouteIntent";

describe("parseRouteIntent", () => {
  it("没有意图参数时返回 null", () => {
    expect(parseRouteIntent({})).toBeNull();
    expect(parseRouteIntent({ page: "2", create: "0" })).toBeNull();
  });

  it("create=1 打开新建表单", () => {
    expect(parseRouteIntent({ create: "1" })).toEqual({
      filter: null,
      create: true
    });
  });

  it("按 status、sla、priority 的顺序取第一个作为看板筛选", () => {
    expect(parseRouteIntent({ sla: "OVERDUE", status: "OPEN" })).toEqual({
      filter: { key: "status", value: "OPEN" },
      create: false
    });
    expect(parseRouteIntent({ priority: "P0" })?.filter).toEqual({
      key: "priority",
      value: "P0"
    });
  });

  it("忽略空值与数组形式的参数", () => {
    expect(parseRouteIntent({ status: "", sla: ["OVERDUE"] })).toBeNull();
  });

  it("清理时只去掉意图参数", () => {
    expect(withoutIntent({ status: "OPEN", create: "1", page: "2" })).toEqual({
      page: "2"
    });
  });
});

async function setup(initial: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/tickets", component: { render: () => null } },
      { path: "/other", component: { render: () => null } }
    ]
  });
  await router.push(initial);
  await router.isReady();
  const state = { ready: false };
  const applyFilter = vi.fn();
  const openCreate = vi.fn();
  let consume: () => void = () => undefined;
  // 模拟被缓存的工单页：组件挂载在工单路由上，之后路由切走组件仍然存活
  const Page = defineComponent({
    setup() {
      ({ consume } = useRouteIntent({
        isReady: () => state.ready,
        applyFilter,
        openCreate
      }));
      return () => h("div");
    }
  });
  mount(Page, { global: { plugins: [router] } });
  const markReady = () => {
    state.ready = true;
    consume();
  };
  return { router, applyFilter, openCreate, markReady };
}

describe("useRouteIntent", () => {
  it("列表就绪前不消费，就绪后执行并只清掉意图参数", async () => {
    const ctx = await setup("/tickets?status=OPEN&page=2");
    expect(ctx.applyFilter).not.toHaveBeenCalled();

    ctx.markReady();
    await flushPromises();

    expect(ctx.applyFilter).toHaveBeenCalledWith({
      key: "status",
      value: "OPEN"
    });
    expect(ctx.router.currentRoute.value.query).toEqual({ page: "2" });
  });

  it("缓存页再次带参进入时打开新建表单", async () => {
    const ctx = await setup("/tickets");
    ctx.markReady();
    await ctx.router.push("/other");
    await ctx.router.push("/tickets?create=1");
    await flushPromises();

    expect(ctx.openCreate).toHaveBeenCalledTimes(1);
    expect(ctx.router.currentRoute.value.query).toEqual({});
  });

  it("其他页面的同名参数不会被缓存中的工单页处理", async () => {
    const ctx = await setup("/tickets");
    ctx.markReady();
    await ctx.router.push("/other?status=OPEN&create=1");
    await flushPromises();

    expect(ctx.applyFilter).not.toHaveBeenCalled();
    expect(ctx.openCreate).not.toHaveBeenCalled();
    expect(ctx.router.currentRoute.value.fullPath).toBe(
      "/other?status=OPEN&create=1"
    );
  });
});
