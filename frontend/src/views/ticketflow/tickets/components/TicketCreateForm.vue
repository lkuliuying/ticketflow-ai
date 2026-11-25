<script lang="ts" setup>
import { onBeforeUnmount, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { FormInstance, FormRules } from "element-plus";
import { isSuccess } from "@/api/types";
import { message } from "@/utils/message";
import {
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  ticketApi,
  type TicketCreatePayload
} from "@/api/ticketflow/tickets";

defineOptions({ name: "TicketFlowTicketCreateForm" });

const TITLE_MAX = 200;
const DESCRIPTION_MAX = 20000;
const MAX_IMAGES = 5;

type UploadedImage = {
  file_pk: string;
  filename: string;
  previewUrl: string;
};

const { t } = useI18n();
const formRef = ref<FormInstance>();
const fileInputRef = ref<HTMLInputElement>();
const uploading = ref(false);
const images = ref<UploadedImage[]>([]);

const form = reactive({
  title: "",
  description: "",
  category: "OTHER",
  priority: "P2" as TicketCreatePayload["priority"]
});

const rules: FormRules = {
  title: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.handoff.titleRequired")
    },
    {
      max: TITLE_MAX,
      message: t("ticketflow.handoff.tooLong", { max: TITLE_MAX })
    }
  ],
  description: [
    {
      required: true,
      whitespace: true,
      message: t("ticketflow.handoff.descriptionRequired")
    },
    {
      max: DESCRIPTION_MAX,
      message: t("ticketflow.handoff.tooLong", { max: DESCRIPTION_MAX })
    }
  ],
  category: [{ required: true }],
  priority: [{ required: true }]
};

async function handleFiles(fileList: FileList | File[]) {
  const files = Array.from(fileList).filter(f => f.type.startsWith("image/"));
  if (!files.length) return;
  if (images.value.length + files.length > MAX_IMAGES) {
    message(t("ticketflow.detail.imageLimitReached"), { type: "warning" });
    return;
  }
  uploading.value = true;
  for (const file of files) {
    const res = await ticketApi.uploadAttachment(file).catch(() => null);
    if (res && isSuccess(res)) {
      images.value.push({
        file_pk: res.data.file_pk,
        filename: res.data.filename,
        previewUrl: URL.createObjectURL(file)
      });
    } else {
      message(String(res?.detail || t("ticketflow.detail.uploadFailed")), {
        type: "error"
      });
    }
  }
  uploading.value = false;
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files?.length) void handleFiles(input.files);
  input.value = "";
}

function onPaste(event: ClipboardEvent) {
  const pasted = Array.from(event.clipboardData?.files ?? []).filter(f =>
    f.type.startsWith("image/")
  );
  if (pasted.length) {
    event.preventDefault();
    void handleFiles(pasted);
  }
}

function removeImage(index: number) {
  const [removed] = images.value.splice(index, 1);
  if (removed) URL.revokeObjectURL(removed.previewUrl);
}

onBeforeUnmount(() => {
  for (const item of images.value) URL.revokeObjectURL(item.previewUrl);
});

async function getPayload(): Promise<TicketCreatePayload | null> {
  if (uploading.value) return null;
  const valid = await formRef.value?.validate().catch(() => false);
  const title = form.title.trim();
  const description = form.description.trim();
  if (!valid || !title || !description) return null;
  const attachment_ids = images.value.map(item => item.file_pk);
  return {
    title,
    description,
    category: form.category,
    priority: form.priority,
    ...(attachment_ids.length ? { attachment_ids } : {})
  };
}

defineExpose({ getPayload });
</script>

<template>
  <el-form
    ref="formRef"
    :model="form"
    :rules="rules"
    label-position="top"
    @paste="onPaste"
  >
    <el-form-item :label="t('ticketflow.title')" prop="title">
      <el-input
        v-model="form.title"
        :maxlength="TITLE_MAX"
        show-word-limit
        data-testid="create-ticket-title"
      />
    </el-form-item>
    <el-form-item :label="t('ticketflow.description')" prop="description">
      <el-input
        v-model="form.description"
        type="textarea"
        :rows="6"
        :maxlength="DESCRIPTION_MAX"
        show-word-limit
        data-testid="create-ticket-description"
      />
    </el-form-item>
    <div class="grid gap-4 md:grid-cols-2">
      <el-form-item :label="t('ticketflow.category')" prop="category">
        <el-select
          v-model="form.category"
          class="w-full"
          data-testid="create-ticket-category"
        >
          <el-option
            v-for="value in TICKET_CATEGORIES"
            :key="value"
            :label="t(`ticketflow.categoryValue.${value}`)"
            :value="value"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('ticketflow.priority')" prop="priority">
        <el-select
          v-model="form.priority"
          class="w-full"
          data-testid="create-ticket-priority"
        >
          <el-option
            v-for="value in TICKET_PRIORITIES"
            :key="value"
            :label="value"
            :value="value"
          />
        </el-select>
      </el-form-item>
    </div>
    <el-form-item :label="t('ticketflow.detail.uploadImages')">
      <div class="flex flex-col gap-2 w-full">
        <div class="flex items-center gap-2 flex-wrap">
          <input
            ref="fileInputRef"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            class="hidden"
            data-testid="create-ticket-file-input"
            @change="onFileChange"
          />
          <el-button
            size="small"
            plain
            :loading="uploading"
            :disabled="images.length >= MAX_IMAGES"
            data-testid="create-ticket-upload-btn"
            @click="fileInputRef?.click()"
          >
            {{ t("ticketflow.detail.uploadImages") }}
          </el-button>
          <span class="text-xs text-(--el-text-color-secondary)">
            {{ t("ticketflow.detail.uploadImagesHint") }}
          </span>
        </div>
        <div
          v-if="images.length"
          class="flex flex-wrap gap-2"
          data-testid="create-ticket-images"
        >
          <div
            v-for="(item, index) in images"
            :key="item.file_pk"
            class="relative size-20 rounded border border-(--el-border-color) overflow-hidden"
          >
            <img
              :src="item.previewUrl"
              :alt="item.filename"
              class="size-full object-cover"
            />
            <el-button
              circle
              size="small"
              type="danger"
              class="absolute top-1 right-1"
              :aria-label="item.filename"
              @click="removeImage(index)"
            >
              ×
            </el-button>
          </div>
        </div>
      </div>
    </el-form-item>
  </el-form>
</template>
