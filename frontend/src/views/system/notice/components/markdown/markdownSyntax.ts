import type { UploadKind } from "./types";

/** 上传结果转 Markdown：图片用 `![]()`，附件用 `[]()`；去掉文件名里的方括号，地址用尖括号包住以容纳空格 */
export function uploadedSyntax(label: string, url: string, kind: UploadKind) {
  const text = label.replace(/[[\]]/g, "");
  return kind === "image" ? `![${text}](<${url}>)` : `[${text}](<${url}>)`;
}
