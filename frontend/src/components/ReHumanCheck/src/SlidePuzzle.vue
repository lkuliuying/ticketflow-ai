<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { CaptchaChallenge } from "@/api/identity/captcha";
import type { VerifyExtra } from "@/utils/captcha/flow";
import { createTrackRecorder } from "@/utils/captcha/protocol";

defineOptions({ name: "SlidePuzzle" });

const props = defineProps<{
  challenge: CaptchaChallenge;
  disabled?: boolean;
}>();
const emit = defineEmits<{
  submit: [answer: { x: number }, extra: VerifyExtra];
}>();

const { t } = useI18n();
const offset = ref(0);
const dragging = ref(false);
const bar = ref<HTMLElement>();
let startX = 0;
const recorder = createTrackRecorder();

const width = computed(() => props.challenge.width ?? 320);
const height = computed(() => props.challenge.height ?? 180);
const maxOffset = computed(() =>
  Math.max(width.value - (props.challenge.piece_size ?? 56), 0)
);

const pieceSize = computed(() => props.challenge.piece_size ?? 56);

watch(
  () => props.challenge.challenge_id,
  () => {
    offset.value = 0;
    dragging.value = false;
  }
);

function localY(event: PointerEvent) {
  const rect = bar.value?.getBoundingClientRect();
  return rect ? event.clientY - rect.top : 0;
}

function onDown(event: PointerEvent) {
  if (props.disabled) return;
  dragging.value = true;
  startX = event.clientX - offset.value;
  recorder.begin(offset.value, localY(event));
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
}

function onMove(event: PointerEvent) {
  if (!dragging.value) return;
  const next = Math.min(Math.max(event.clientX - startX, 0), maxOffset.value);
  offset.value = next;
  recorder.move(next, localY(event));
}

function onUp(event: PointerEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  recorder.move(offset.value, localY(event));
  emit("submit", { x: Math.round(offset.value) }, { track: recorder.points() });
}

/** 系统手势、切屏等中断拖动：放弃这次拖动，不提交半途位置 */
function onCancel() {
  dragging.value = false;
  offset.value = 0;
}

/** 键盘操作：方向键逐像素（Shift 十像素）移动，回车提交 */
function onKey(event: KeyboardEvent) {
  if (props.disabled) return;
  const step = event.shiftKey ? 10 : 1;
  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? step : -step;
    offset.value = Math.min(Math.max(offset.value + delta, 0), maxOffset.value);
  } else if (event.key === "Enter") {
    event.preventDefault();
    emit("submit", { x: Math.round(offset.value) }, { input: "keyboard" });
  }
}
</script>

<template>
  <div class="slide-puzzle" :style="{ width: `${width}px` }">
    <div class="slide-puzzle__stage" :style="{ height: `${height}px` }">
      <img
        class="slide-puzzle__img"
        :src="challenge.background"
        :width="width"
        :height="height"
        alt=""
        draggable="false"
      />
      <img
        class="slide-puzzle__img"
        :src="challenge.piece"
        :width="width"
        :height="height"
        :style="{ transform: `translateX(${offset}px)` }"
        alt=""
        draggable="false"
      />
    </div>
    <div ref="bar" class="slide-puzzle__bar">
      <span class="slide-puzzle__hint">{{ t("captcha.slideHint") }}</span>
      <div
        class="slide-puzzle__knob"
        role="slider"
        tabindex="0"
        :aria-label="t('captcha.slideHint')"
        :aria-valuemin="0"
        :aria-valuemax="maxOffset"
        :aria-valuenow="Math.round(offset)"
        :class="{ 'is-dragging': dragging }"
        :style="{
          width: `${pieceSize}px`,
          transform: `translateX(${offset}px)`
        }"
        @pointerdown="onDown"
        @pointermove="onMove"
        @pointerup="onUp"
        @pointercancel="onCancel"
        @keydown="onKey"
      >
        <span aria-hidden="true">→</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide-puzzle {
  margin: 0 auto;
  user-select: none;
}

.slide-puzzle__stage {
  position: relative;
  overflow: hidden;
  border-radius: var(--el-border-radius-base);
}

.slide-puzzle__img {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.slide-puzzle__bar {
  position: relative;
  height: 40px;
  margin-top: 12px;
  line-height: 40px;
  color: var(--el-text-color-secondary);
  text-align: center;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
}

.slide-puzzle__knob {
  position: absolute;
  top: -1px;
  left: -1px;
  height: 40px;
  color: var(--el-color-white);
  touch-action: none;
  cursor: grab;
  background: var(--el-color-primary);
  border-radius: var(--el-border-radius-base);
}

.slide-puzzle__knob.is-dragging {
  cursor: grabbing;
}

.slide-puzzle__knob:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: 2px;
}
</style>
