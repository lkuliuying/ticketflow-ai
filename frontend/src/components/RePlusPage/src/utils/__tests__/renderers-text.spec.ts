import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { defineComponent, type VNode } from "vue";
import { textDetailRenderers, textFormRenderers } from "../renderers-text";
import { uploadedSyntax } from "@/views/system/notice/components/markdown/markdownSyntax";
import type { PageColumn, PlusColumnContext, PlusColumnMeta } from "../types";

/** 文本类渲染器的行为守护：链接协议白名单、密码不回显、富文本不插 HTML、decimal 保留字符串 */

/** 渲染器就地写入的字段：详情 render、列表 cellRenderer、表单 valueType / fieldProps */
interface ConfiguredColumn {
  render: (value: unknown) => VNode;
  cellRenderer: (scope: { row: Record<string, unknown> }) => VNode;
  valueType?: string;
  fieldProps: Record<string, unknown>;
}

function makeColumn(inputType: string): PageColumn & PlusColumnMeta {
  return {
    key: "field_a",
    label: "A",
    prop: "field_a",
    input_type: inputType,
    fieldProps: {},
    _column: { key: "field_a", label: "A", input_type: inputType }
  } as PageColumn & PlusColumnMeta;
}

function context(column: PageColumn & PlusColumnMeta): PlusColumnContext {
  return {
    column,
    t: (k: string) => k,
    te: () => false,
    localeName: "zh",
    apiSearchComponents: {}
  };
}

function configure(
  registry: typeof textDetailRenderers,
  inputType: string
): ConfiguredColumn {
  const column = makeColumn(inputType);
  registry[inputType](column, context(column));
  const record: Record<string, unknown> = column;
  return {
    render: record.render as ConfiguredColumn["render"],
    cellRenderer: record.cellRenderer as ConfiguredColumn["cellRenderer"],
    valueType: record.valueType as string | undefined,
    fieldProps: record.fieldProps as Record<string, unknown>
  };
}

function html(node: VNode) {
  return mount(defineComponent({ render: () => node })).html();
}

describe("文本类详情渲染器", () => {
  it("url：http(s) 渲染为新窗口链接并带 noopener", () => {
    const column = configure(textDetailRenderers, "url");
    const out = mount(
      defineComponent({ render: () => column.render("https://example.com/a") })
    );
    const link = out.find("a");
    expect(link.attributes("href")).toBe("https://example.com/a");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
  });

  it("url：非 http(s) 协议只显示文本，不生成链接", () => {
    const column = configure(textDetailRenderers, "url");
    for (const node of [
      column.render("javascript:alert(1)"),
      column.cellRenderer({ row: { field_a: "data:text/html,x" } })
    ]) {
      const out = html(node);
      expect(out).not.toContain("<a");
      expect(out).not.toContain("href");
    }
  });

  it("password：详情与列表都打码，不回显原文", () => {
    const column = configure(textDetailRenderers, "password");
    const detail = html(column.render("s3cret"));
    const cell = html(column.cellRenderer({ row: { field_a: "s3cret" } }));
    for (const out of [detail, cell]) {
      expect(out).not.toContain("s3cret");
      expect(out).toContain("••••••");
    }
    expect(html(column.render(""))).toContain("—");
  });

  it("rich_text：按纯文本输出，标签被转义而不是插入 DOM", () => {
    const column = configure(textDetailRenderers, "rich_text");
    const payload = '<img src=x onerror="alert(1)">第一行\n第二行';
    const detail = mount(
      defineComponent({ render: () => column.render(payload) })
    );
    expect(detail.find("img").exists()).toBe(false);
    expect(detail.text()).toContain("<img");
    const cell = mount(
      defineComponent({
        render: () => column.cellRenderer({ row: { field_a: payload } })
      })
    );
    expect(cell.find("img").exists()).toBe(false);
  });
});

describe("文本类表单渲染器", () => {
  it("decimal：按文本输入保留服务端字符串，不转浮点", () => {
    const column = configure(textFormRenderers, "decimal");
    expect(column.valueType).toBe("input");
    expect(column.fieldProps.inputmode).toBe("decimal");
  });

  it("password：密码框且可切换显示，不触发浏览器自动填充已存密码", () => {
    const column = configure(textFormRenderers, "password");
    expect(column.fieldProps).toMatchObject({
      type: "password",
      showPassword: true,
      autocomplete: "new-password"
    });
  });

  it("rich_text：多行文本编辑", () => {
    expect(configure(textFormRenderers, "rich_text").valueType).toBe(
      "textarea"
    );
  });
});

describe("Markdown 上传结果语法", () => {
  it("图片与附件语法、去掉方括号、地址用尖括号包住", () => {
    expect(uploadedSyntax("a[1].png", "/m/a 1.png", "image")).toBe(
      "![a1.png](</m/a 1.png>)"
    );
    expect(uploadedSyntax("doc.pdf", "/m/doc.pdf", "attachment")).toBe(
      "[doc.pdf](</m/doc.pdf>)"
    );
  });
});
