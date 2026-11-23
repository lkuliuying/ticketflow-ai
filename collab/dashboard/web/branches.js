// 分支堆场：main 之外的每个分支一个集装箱。领先 main 的分支是彩色高箱，已合入的分支是一排小灰箱。
import * as THREE from "three";
import { AGENT_COLORS, esc } from "./theme.js";
import { box, label, mat, tint } from "./warehouse.js";

export const YARD = new THREE.Vector3(0, 0, 10.2);
const ACTIVE_SPACING = 3.1;
const STALE_SPACING = 1.15;
const MAX_STALE = 24;

/** 分支前缀对应的执行者颜色：fe/ 是 Claude，be/ 是 Codex，其余用中性色 */
export function branchColor(name) {
  if (name.startsWith("fe/")) return AGENT_COLORS.claude;
  if (name.startsWith("be/")) return AGENT_COLORS.codex;
  if (name.startsWith("integration/")) return "#7c8aa5";
  return "#9aa3b2";
}

export function buildYard(scene) {
  const group = new THREE.Group();
  group.position.copy(YARD);
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(26, 5.4), new THREE.MeshStandardMaterial({ color: "#e4e8ee", roughness: 1 }));
  pad.rotation.x = -Math.PI / 2;
  pad.position.set(0, 0.02, 0.6);
  pad.receiveShadow = true;
  group.add(pad);
  // 堆场边线
  for (const z of [-2.1, 3.3]) group.add(box(26, 0.04, 0.08, mat("#f0b429"), 0, 0.04, z));
  const tag = label("", "label yard-label");
  tag.position.set(-9.5, 0.1, -1.7);
  group.add(tag);
  scene.add(group);
  return { group, tag, items: [], sig: "" };
}

export function updateYard(yard, git, pickables) {
  const branches = git.branches.filter(b => b.name !== "main");
  const active = branches.filter(b => b.ahead > 0).sort((a, b) => b.ahead - a.ahead);
  const stale = branches.filter(b => b.ahead === 0).sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
  yard.tag.body.innerHTML = `<b>分支堆场</b><span>${active.length} 个领先 main · ${stale.length} 个已合入</span>`;
  const sig = JSON.stringify([git.current, active.map(b => [b.name, b.ahead, b.behind, b.sha]), stale.map(b => b.name)]);
  if (sig === yard.sig) return;
  yard.sig = sig;
  for (const item of yard.items) {
    yard.group.remove(item.group);
    // Object3D.remove 只对被移除的分组派发 removed，子级标签的 DOM 要自己删掉
    item.group.traverse(o => {
      if (o.isCSS2DObject) o.element.remove();
      o.geometry?.dispose();
      o.material?.dispose();
      const i = pickables.indexOf(o);
      if (i >= 0) pickables.splice(i, 1);
    });
  }
  yard.items = [];

  // 领先 main 的分支：高度随领先提交数增长，当前检出的分支描边高亮
  active.forEach((b, i) => {
    const group = new THREE.Group();
    group.position.set((i - (active.length - 1) / 2) * ACTIVE_SPACING, 0, 0);
    const color = branchColor(b.name);
    const height = 0.9 + Math.min(b.ahead, 25) * 0.07;
    const body = box(2.6, height, 1.3, mat(color), 0, height / 2, 0);
    group.add(body);
    for (let r = -1; r <= 1; r += 0.5) group.add(box(0.05, height - 0.1, 1.32, mat(tint(color, -0.15)), r * 1.1, height / 2, 0));
    group.add(box(2.64, 0.08, 1.34, mat(tint(color, 0.4)), 0, height, 0));
    const current = b.name === git.current;
    if (current) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(1.75, 1.95, 40), new THREE.MeshBasicMaterial({ color: "#1f2937", side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.04;
      ring.scale.set(1, 0.6, 1);
      group.add(ring);
    }
    const tag = label(`
      <div class="branch-name">${esc(b.name)}${current ? '<span class="chip running">当前检出</span>' : ""}</div>
      <div class="branch-sub">领先 ${b.ahead}${b.behind ? ` · 落后 ${b.behind}` : ""} · <code>${esc(b.sha)}</code></div>`, "label branch-label");
    tag.body.style.setProperty("--c", color);
    tag.position.set(0, height + 0.5, 0);
    group.add(tag);
    body.userData = { kind: "branch", id: b.name };
    pickables.push(body);
    yard.group.add(group);
    yard.items.push({ group, name: b.name, body });
  });

  // 已合入 main 的分支：前排一行小灰箱，只在悬停提示里显示名字
  stale.slice(0, MAX_STALE).forEach((b, i) => {
    const group = new THREE.Group();
    const n = Math.min(stale.length, MAX_STALE);
    group.position.set((i - (n - 1) / 2) * STALE_SPACING, 0, 2.4);
    const body = box(0.95, 0.5, 0.65, mat(tint(branchColor(b.name), 0.7)), 0, 0.25, 0);
    group.add(body);
    body.userData = { kind: "branch", id: b.name };
    pickables.push(body);
    yard.group.add(group);
    yard.items.push({ group, name: b.name, body });
  });
}

export function tickYard(yard, selected) {
  for (const item of yard.items) {
    const isSel = selected?.kind === "branch" && selected.id === item.name;
    item.body.material.emissive.set(isSel ? "#1f2937" : "#000000");
    item.body.material.emissiveIntensity = isSel ? 0.25 : 0;
    item.group.scale.y = isSel ? 1.06 : 1;
  }
}
