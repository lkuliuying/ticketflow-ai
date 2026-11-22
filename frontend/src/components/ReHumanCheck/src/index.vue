<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { CaptchaScene } from "@/api/identity/captcha";
import SlidePuzzle from "./SlidePuzzle.vue";
import { useHumanCheck } from "./useHumanCheck";

defineOptions({ name: "ReHumanCheck" });

const props = defineProps<{
  scene: CaptchaScene;
  action: string;
  /** 服务端启用的题型（能力探测返回的 `captcha_types`） */
  types?: readonly string[];
}>();

const { t } = useI18n();
const code = ref("");
const { visible, loading, challenge, obtain, submit, refresh, cancel } =
  useHumanCheck({
    scene: () => props.scene,
    action: () => props.action,
    types: () => props.types,
    unsupportedMessage: () => t("captcha.unsupported"),
    failedMessage: () => t("captcha.failed")
  });

watch(
  () => challenge.value?.challenge_id,
  () => (code.value = "")
);

function submitCode() {
  const value = code.value.trim();
  if (!value || loading.value) return;
  void submit(value, { input: "keyboard" });
}

defineExpose({ obtain });
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="t('captcha.title')"
    width="380px"
    append-to-body
    align-center
    :close-on-click-modal="false"
    @close="cancel"
  >
    <div v-loading="loading" class="flex flex-col items-center gap-3">
      <template v-if="challenge?.type === 'slide'">
        <SlidePuzzle
          :challenge="challenge"
          :disabled="loading"
          @submit="(answer, extra) => submit(answer, extra)"
        />
      </template>
      <template v-else-if="challenge?.type === 'image'">
        <img
          :src="challenge.background"
          :width="challenge.width"
          :height="challenge.height"
          :alt="t('captcha.imageAlt')"
          :class="loading ? 'cursor-wait' : 'cursor-pointer'"
          @click="refresh"
        />
        <el-input
          v-model="code"
          :maxlength="challenge.length || 8"
          :placeholder="t('captcha.imagePlaceholder')"
          @keyup.enter="submitCode"
        />
      </template>
      <div class="flex w-full justify-between">
        <el-button link type="primary" :disabled="loading" @click="refresh">
          {{ t("captcha.refresh") }}
        </el-button>
        <el-button
          v-if="challenge?.type === 'image'"
          type="primary"
          :loading="loading"
          :disabled="!code.trim()"
          @click="submitCode"
        >
          {{ t("captcha.confirm") }}
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>
