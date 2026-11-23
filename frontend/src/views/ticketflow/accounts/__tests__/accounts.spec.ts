import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";

const mocks = vi.hoisted(() => ({
  addDialog: vi.fn(),
  confirm: vi.fn(),
  message: vi.fn(),
  create: vi.fn(),
  partialUpdate: vi.fn(),
  resetPassword: vi.fn(),
  setActive: vi.fn(),
  encrypt: vi.fn(async (key: string, msg: string) => `enc(${key}:${msg})`)
}));

vi.mock("vue-i18n", async importOriginal => {
  const actual = await importOriginal<typeof import("vue-i18n")>();
  return { ...actual, useI18n: () => ({ t: (key: string) => key }) };
});
vi.mock("@/plugins/i18n", () => ({
  i18n: { global: { t: (key: string) => key } },
  $t: (key: string) => key,
  transformI18n: (key: string) => key
}));
vi.mock("@/components/ReDialog", () => ({ addDialog: mocks.addDialog }));
vi.mock("@/utils/message", () => ({ message: mocks.message }));
vi.mock("@/utils/aes", () => ({ AesEncrypted: mocks.encrypt }));
vi.mock("element-plus", async importOriginal => {
  const actual = await importOriginal<typeof import("element-plus")>();
  return { ...actual, ElMessageBox: { confirm: mocks.confirm } };
});
vi.mock("@/api/ticketflow/accounts", async importOriginal => {
  const actual =
    await importOriginal<typeof import("@/api/ticketflow/accounts")>();
  return {
    ...actual,
    accountApi: {
      create: mocks.create,
      partialUpdate: mocks.partialUpdate,
      resetPassword: mocks.resetPassword,
      setActive: mocks.setActive
    }
  };
});

import AccountForm from "../components/AccountForm.vue";
import {
  openAccountForm,
  openResetPassword,
  toggleAccountActive
} from "../utils/accountDialogs";
import type { BusinessAccount } from "@/api/ticketflow/accounts";

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
    name: "已停用组",
    description: "",
    is_active: false,
    is_default: false
  }
];
const agent: BusinessAccount = {
  pk: 3,
  username: "tf_agent_other",
  name: "网络支持技术员",
  phone: "",
  email: "",
  role: "agent",
  skill_group: "g2",
  skill_group_name: "已停用组",
  is_active: true
};

type DialogOptions = {
  title: string;
  contentRenderer: () => { ref: { r: { value: unknown } } };
  beforeSure: (
    done: () => void,
    ctx: { closeLoading: () => void }
  ) => Promise<void>;
};

function lastDialog(formStub: unknown): DialogOptions {
  const options: DialogOptions = mocks.addDialog.mock.calls.at(-1)![0];
  options.contentRenderer().ref.r.value = formStub;
  return options;
}

describe("AccountForm", () => {
  const mountForm = (initial?: BusinessAccount) =>
    mount(AccountForm, {
      props: { initial, groups, passwordRules: [] },
      global: { plugins: [ElementPlus] }
    });

  it("新建：技术员未选技能组时校验失败", async () => {
    const wrapper = mountForm();
    Object.assign(wrapper.vm.form, {
      username: "new_agent",
      name: "新技术员",
      role: "agent",
      password: "Secret-123456"
    });
    await flushPromises();
    expect(await wrapper.vm.getPayload()).toBeNull();
  });

  it("新建：返回去空白的载荷，非技术员技能组为空", async () => {
    const wrapper = mountForm();
    Object.assign(wrapper.vm.form, {
      username: "new_user",
      name: " 新员工 ",
      role: "requester",
      skill_group: "g1",
      password: "Secret-123456"
    });
    await flushPromises();
    expect(await wrapper.vm.getPayload()).toEqual({
      username: "new_user",
      password: "Secret-123456",
      name: "新员工",
      phone: "",
      email: "",
      role: "requester",
      skill_group: null
    });
  });

  it("编辑：不提交用户名与密码，切换成非技术员时清空技能组", async () => {
    const wrapper = mountForm(agent);
    wrapper.vm.form.role = "admin";
    await flushPromises();
    expect(wrapper.vm.form.skill_group).toBeNull();
    const payload = await wrapper.vm.getPayload();
    expect(payload).not.toHaveProperty("username");
    expect(payload).not.toHaveProperty("password");
    expect(payload?.role).toBe("admin");
  });

  it("技能组选项：只列启用组，编辑时保留当前所在的已停用组", () => {
    const create = mountForm();
    expect(
      create.vm.groupOptions.map((group: { pk: string }) => group.pk)
    ).toEqual(["g1"]);
    const edit = mountForm(agent);
    expect(
      edit.vm.groupOptions.map((group: { pk: string }) => group.pk)
    ).toEqual(["g1", "g2"]);
  });

  it("新建：非法用户名被拦截", async () => {
    const wrapper = mountForm();
    Object.assign(wrapper.vm.form, {
      username: "坏 名字",
      name: "员工",
      role: "requester",
      password: "Secret-123456"
    });
    await flushPromises();
    expect(await wrapper.vm.getPayload()).toBeNull();
  });
});

describe("账号弹窗", () => {
  beforeEach(() => vi.clearAllMocks());

  it("新建时以目标用户名为密钥加密初始密码后提交", async () => {
    mocks.create.mockResolvedValue({ code: 1000, data: {} });
    const onSaved = vi.fn();
    openAccountForm({ groups, passwordRules: [], onSaved });
    const payload = {
      username: "new_user",
      password: "Secret-123456",
      name: "新员工",
      phone: "",
      email: "",
      role: "requester",
      skill_group: null
    };
    const done = vi.fn();
    await lastDialog({ getPayload: async () => ({ ...payload }) }).beforeSure(
      done,
      { closeLoading: vi.fn() }
    );
    expect(mocks.encrypt).toHaveBeenCalledWith("new_user", "Secret-123456");
    expect(mocks.create).toHaveBeenCalledWith({
      ...payload,
      password: "enc(new_user:Secret-123456)"
    });
    expect(done).toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalled();
  });

  it("编辑走 PATCH，失败时保持弹窗", async () => {
    mocks.partialUpdate.mockResolvedValue({ code: 403, detail: "越权" });
    openAccountForm({ initial: agent, groups, passwordRules: [] });
    const done = vi.fn();
    await lastDialog({
      getPayload: async () => ({ name: "x", role: "agent" })
    }).beforeSure(done, { closeLoading: vi.fn() });
    expect(mocks.partialUpdate).toHaveBeenCalledWith(3, {
      name: "x",
      role: "agent"
    });
    expect(mocks.encrypt).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
  });

  it("重置密码加密后提交", async () => {
    mocks.resetPassword.mockResolvedValue({ code: 1000, data: null });
    openResetPassword(agent, []);
    const done = vi.fn();
    await lastDialog({ getPassword: async () => "New-Secret-1" }).beforeSure(
      done,
      { closeLoading: vi.fn() }
    );
    expect(mocks.resetPassword).toHaveBeenCalledWith(3, {
      password: "enc(tf_agent_other:New-Secret-1)"
    });
    expect(done).toHaveBeenCalled();
  });

  it("停用技术员使用专门的确认文案，取消时不提交", async () => {
    mocks.confirm.mockRejectedValue("cancel");
    expect(await toggleAccountActive(agent)).toBe(false);
    expect(mocks.confirm.mock.calls[0][0]).toBe(
      "ticketflow.account.disableAgentConfirm"
    );
    expect(mocks.setActive).not.toHaveBeenCalled();
  });

  it("确认后切换启用状态并回调", async () => {
    mocks.confirm.mockResolvedValue(true);
    mocks.setActive.mockResolvedValue({ code: 1000, data: {} });
    const onChanged = vi.fn();
    expect(
      await toggleAccountActive({ ...agent, is_active: false }, onChanged)
    ).toBe(true);
    expect(mocks.setActive).toHaveBeenCalledWith(3, true);
    expect(onChanged).toHaveBeenCalled();
  });
});
