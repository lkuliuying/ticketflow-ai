import { AgentScene } from "./scene.js";
import {
  renderAgents,
  renderDetail,
  renderEvents,
  renderGit,
  renderPipeline,
  renderTop
} from "./hud.js";
import { STAGE_HINT, STATE_LABEL, esc } from "./theme.js";

const POLL_MS = 3000;
let data = null;
let selected = null;
let lastOk = false;

const tooltip = document.getElementById("tooltip");
const errorBanner = document.getElementById("error");

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
}

function select(target) {
  selected = target;
  scene.select(target);
  if (target) showTab(target.kind === "trunk" ? "git" : "detail");
  render();
}

function hover(target, event) {
  if (!target || !data) {
    tooltip.style.opacity = 0;
    return;
  }
  let html = "";
  if (target.kind === "agent") {
    const a = data.agents[target.id];
    html = `<b>${esc(a.name)}</b> · ${STATE_LABEL[a.state] ?? a.state}<br>${esc(a.task ?? "无任务")}` +
      (a.activity ? `<br><span class="muted">${esc(a.activity.slice(0, 140))}</span>` : "");
  } else if (target.kind === "task") {
    const t = data.tasks.find(x => x.id === target.id);
    html = t ? `<b>${t.id}</b> ${esc(t.title)}<br>${t.stage} · ${esc(t.executor)}` : "";
  } else if (target.kind === "stage") {
    html = `<b>${target.id}</b><br>${esc(STAGE_HINT[target.id])}`;
  } else if (target.kind === "trunk") {
    html = "<b>main</b><br>点击查看分支与提交";
  }
  tooltip.innerHTML = html;
  tooltip.style.opacity = html ? 1 : 0;
  tooltip.style.transform = `translate(${event.clientX + 14}px, ${event.clientY + 14}px)`;
}

const scene = new AgentScene(document.getElementById("stage"), { onSelect: select, onHover: hover });

const SCROLLERS = ["agents", "tab-pipeline", "tab-detail", "tab-git", "events"];

function render() {
  if (!data) return;
  // 重绘会重建 DOM：先记下各面板的滚动位置与展开的折叠块，重绘后恢复
  const scroll = Object.fromEntries(SCROLLERS.map(id => {
    const el = document.getElementById(id);
    return [id, [el.scrollTop, el.scrollLeft]];
  }));
  const open = [...document.querySelectorAll("details[open] > summary")].map(s => s.textContent);
  renderTop(data, lastOk);
  renderAgents(data, selected, select);
  renderPipeline(data, selected, select);
  renderDetail(data, selected);
  renderGit(data);
  renderEvents(data);
  lastRender = Date.now();
  for (const [id, [top, left]] of Object.entries(scroll)) {
    const el = document.getElementById(id);
    el.scrollTop = top;
    el.scrollLeft = left;
  }
  document.querySelectorAll("details > summary").forEach(s => {
    if (open.includes(s.textContent)) s.parentElement.open = true;
  });
}

let signature = "";
let lastRender = 0;

async function poll() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    const body = await res.json();
    if (body.error) throw new Error(body.error);
    data = body;
    lastOk = true;
    errorBanner.style.display = "none";
    const next = JSON.stringify({ ...body, now: null });
    if (next === signature && Date.now() - lastRender < 20000) {
      renderTop(data, lastOk);
      setTimeout(poll, POLL_MS);
      return;
    }
    signature = next;
    scene.update(data);
  } catch (err) {
    lastOk = false;
    errorBanner.textContent = `状态采集失败：${err.message}`;
    errorBanner.style.display = "block";
  }
  render();
  setTimeout(poll, POLL_MS);
}

document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
// 面板折叠：状态只是本机偏好，存储不可用时退回默认展开
const COLLAPSE_KEY = "dashboard.collapsed";
function loadCollapsed() {
  try {
    const saved = localStorage.getItem(COLLAPSE_KEY);
    const list = saved ? JSON.parse(saved) : null;
    if (Array.isArray(list)) return list;
  } catch {
    /* 读不到偏好时用默认值 */
  }
  // 窄屏默认收起左侧代理面板，把空间留给仓库
  return window.innerWidth < 1300 ? ["left"] : [];
}
function applyCollapsed(list) {
  for (const side of ["left", "right", "bottom"]) document.body.classList.toggle(`collapsed-${side}`, list.includes(side));
  // 过渡结束后再重算画面偏移，让场景居中到可见区域
  setTimeout(() => scene.resize(), 320);
}
document.querySelectorAll("[data-panel]").forEach(el =>
  el.addEventListener("transitionend", e => {
    if (e.target === el) scene.resize();
  })
);
let collapsed = loadCollapsed();
applyCollapsed(collapsed);
scene.resize();
// 首屏直接呈现保存的折叠状态，不播放过渡
requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.remove("preload")));
document.querySelectorAll("[data-collapse]").forEach(b =>
  b.addEventListener("click", () => {
    const side = b.dataset.collapse;
    collapsed = collapsed.includes(side) ? collapsed.filter(s => s !== side) : [...collapsed, side];
    applyCollapsed(collapsed);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed));
    } catch {
      /* 无痕模式等场景下不保存 */
    }
  })
);
let rotating = false;
document.getElementById("reset-view").addEventListener("click", () => {
  // 复位同时停止巡航，按钮状态与 rotating 保持一致
  rotating = false;
  document.getElementById("rotate-toggle").classList.add("off");
  scene.resetView();
});
document.getElementById("rotate-toggle").addEventListener("click", e => {
  rotating = !rotating;
  scene.setAutoRotate(rotating);
  e.currentTarget.classList.toggle("off", !rotating);
});
window.addEventListener("keydown", e => {
  if (e.key === "Escape") select(null);
});

poll();
