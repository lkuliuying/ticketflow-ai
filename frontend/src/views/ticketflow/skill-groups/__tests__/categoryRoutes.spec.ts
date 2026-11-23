import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  categoryRoutes: vi.fn(),
  updateRoute: vi.fn(),
  message: vi.fn()
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return {
    ...actual,
    useI18n: () => ({ t: (key: string) => key, te: () => false })
  };
});
vi.mock("@/utils/message", () => ({ message: mocks.message }));
vi.mock("@/api/ticketflow/accounts", () => ({
  skillGroupApi: {
    categoryRoutes: mocks.categoryRoutes,
    updateRoute: mocks.updateRoute
  }
}));

import CategoryRoutes from "../components/CategoryRoutes.vue";

const groups = [
  {
    pk: "g1",
    name: "工单支持组",
    description: "",
    is_active: true,
    is_default: true
  },
  {
    pk: "g2",
    name: "网络支持组",
    description: "",
    is_active: true,
    is_default: false
  }
];

async function mountRoutes() {
  mocks.categoryRoutes.mockResolvedValue({
    code: 1000,
    data: [
      {
        category: "NETWORK",
        label: "网络",
        skill_group: null,
        skill_group_name: null
      }
    ]
  });
  const wrapper = mount(CategoryRoutes, {
    props: { groups, canEdit: true },
    global: { stubs: { "el-card": { template: "<div><slot /></div>" } } }
  });
  await flushPromises();
  return wrapper;
}

describe("CategoryRoutes", () => {
  beforeEach(() => vi.clearAllMocks());

  it("改动即保存，用接口返回值更新该行", async () => {
    mocks.updateRoute.mockResolvedValue({
      code: 1000,
      data: {
        category: "NETWORK",
        label: "网络",
        skill_group: "g2",
        skill_group_name: "网络支持组"
      }
    });
    const wrapper = await mountRoutes();
    const route = {
      ...(await mocks.categoryRoutes.mock.results[0].value).data[0]
    };
    await wrapper.vm.change(route, "g2");
    expect(mocks.updateRoute).toHaveBeenCalledWith("NETWORK", "g2");
    expect(route.skill_group_name).toBe("网络支持组");
    expect(mocks.message).toHaveBeenCalled();
  });

  it("保存失败时回退到原值", async () => {
    mocks.updateRoute.mockResolvedValue({ code: 409, detail: "技能组已停用" });
    const wrapper = await mountRoutes();
    const route = {
      category: "NETWORK",
      label: "网络",
      skill_group: "g1",
      skill_group_name: "工单支持组"
    };
    await wrapper.vm.change(route, "g2");
    expect(route.skill_group).toBe("g1");
  });

  it("清空表示走默认组，提交 null", async () => {
    mocks.updateRoute.mockResolvedValue({
      code: 1000,
      data: {
        category: "NETWORK",
        label: "网络",
        skill_group: null,
        skill_group_name: null
      }
    });
    const wrapper = await mountRoutes();
    const route = {
      category: "NETWORK",
      label: "网络",
      skill_group: "g2",
      skill_group_name: "网络支持组"
    };
    await wrapper.vm.change(route, null);
    expect(mocks.updateRoute).toHaveBeenCalledWith("NETWORK", null);
    expect(route.skill_group).toBeNull();
  });
});
