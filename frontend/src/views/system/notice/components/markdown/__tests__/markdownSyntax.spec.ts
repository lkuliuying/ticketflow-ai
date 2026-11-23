import { describe, expect, it } from "vitest";
import { uploadedSyntax } from "../markdownSyntax";

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
