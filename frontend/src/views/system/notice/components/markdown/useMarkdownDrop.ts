import { ref, type Ref } from "vue";

/**
 * Markdown 编辑器的拖拽与粘贴上传：把拖入或粘贴的文件交给 `uploadFiles`。
 * 拖拽高亮用进入/离开计数，避免经过子元素时闪烁；无上传权限时不响应。
 */
export function useMarkdownDrop({
  canUpload,
  uploadFiles
}: {
  canUpload: Ref<boolean>;
  uploadFiles: (list: File[]) => Promise<void>;
}) {
  const dragActive = ref(false);
  const dragDepth = ref(0);

  function onDragEnter(event: DragEvent) {
    if (!canUpload.value || !event.dataTransfer?.types.includes("Files")) {
      return;
    }
    dragDepth.value += 1;
    dragActive.value = true;
  }

  function onDragLeave() {
    dragDepth.value = Math.max(0, dragDepth.value - 1);
    if (!dragDepth.value) dragActive.value = false;
  }

  async function onDrop(event: DragEvent) {
    dragDepth.value = 0;
    dragActive.value = false;
    if (!canUpload.value) return;
    const dropped = Array.from(event.dataTransfer?.files ?? []);
    if (dropped.length) await uploadFiles(dropped);
  }

  async function onPaste(event: ClipboardEvent) {
    if (!canUpload.value) return;
    const pasted = Array.from(event.clipboardData?.items ?? [])
      .filter(item => item.kind === "file")
      .map(item => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (!pasted.length) return;
    event.preventDefault();
    await uploadFiles(pasted);
  }

  return { dragActive, onDragEnter, onDragLeave, onDrop, onPaste };
}
