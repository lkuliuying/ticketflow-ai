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
    html = `<b>${esc(a.name)}</b> · ${STATE_LABEL[a.state] ?? a.state}<br>${esc(a.task ?? "无任务")}`;
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
let rotating = false;
document.getElementById("rotate-toggle").addEventListener("click", e => {
  rotating = !rotating;
  scene.setAutoRotate(rotating);
  e.currentTarget.classList.toggle("off", !rotating);
});
window.addEventListener("keydown", e => {
  if (e.key === "Escape") select(null);
});

poll();
