import { get } from "lodash-es";
import type { PlusColumnRegistry } from "./types";

/**
 * 文本类字段（decimal / password / url / rich_text）的表单与详情渲染器。
 * 服务端词表 DECLARED_INPUT_TYPES 声明了这些类型，渲染面在此集中实现，
 * 由 renderers-form.tsx / renderers-detail.tsx 并入各自的内置表。
 */

/** 只把 http(s) 地址渲染成链接，其他协议（javascript: 等）按纯文本展示 */
const SAFE_URL = /^https?:\/\//i;
const PASSWORD_MASK = "••••••";
const EMPTY = "—";

function urlNode(value: unknown) {
  if (typeof value !== "string" || !value) return <span>{EMPTY}</span>;
  if (!SAFE_URL.test(value)) return <span>{value}</span>;
  return (
    <a
      class="text-(--el-color-primary) break-all"
      href={value}
      target="_blank"
      rel="noopener noreferrer"
    >
      {value}
    </a>
  );
}

export const textFormRenderers: PlusColumnRegistry = {
  // DecimalField 序列化为字符串：按文本编辑并原样提交，避免转成浮点数丢精度，校验交给服务端
  decimal: item => {
    item["valueType"] = "input";
    item["fieldProps"]!["inputmode"] = "decimal";
  },
  password: item => {
    item["valueType"] = "input";
    item["fieldProps"]!["type"] = "password";
    item["fieldProps"]!["showPassword"] = true;
    item["fieldProps"]!["autocomplete"] = "new-password";
  },
  url: item => {
    item["valueType"] = "input";
    item["fieldProps"]!["placeholder"] ??= "https://";
  },
  // 富文本按多行文本编辑，提交原文；展示侧不解析 HTML（见 textDetailRenderers）
  rich_text: item => {
    item["valueType"] = "textarea";
    item["fieldProps"]!["autosize"] = { minRows: 4, maxRows: 12 };
  }
};

export const textDetailRenderers: PlusColumnRegistry = {
  // 详情与列表都不回显密码原文
  password: (item, { column }) => {
    item["render"] = (value: unknown) => (
      <span>{value ? PASSWORD_MASK : EMPTY}</span>
    );
    item["cellRenderer"] = ({ row }) => (
      <span>{get(row, column.key) ? PASSWORD_MASK : EMPTY}</span>
    );
  },
  url: (item, { column }) => {
    item["render"] = (value: unknown) => urlNode(value);
    item["cellRenderer"] = ({ row }) => urlNode(get(row, column.key));
  },
  // 富文本按纯文本展示（保留换行），不插入 HTML，避免 XSS
  rich_text: (item, { column }) => {
    item["render"] = (value: unknown) => (
      <span class="whitespace-pre-wrap wrap-break-word">
        {value ? String(value) : EMPTY}
      </span>
    );
    item["cellRenderer"] = ({ row }) => {
      const value = get(row, column.key);
      return (
        <span class="block truncate">{value ? String(value) : EMPTY}</span>
      );
    };
  }
};
