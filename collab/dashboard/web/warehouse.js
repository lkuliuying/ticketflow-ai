// 总览里的代理仓库：扁平低多边形的封闭建筑，只显示状态与库存，点击进入内部。
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { AGENT_COLORS, STAGE_COLORS, STATE_LABEL, esc } from "./theme.js";

// 三座仓库摆成三角形：Claude 在后方，Codex 在右前，Gemini 在左前
export const WAREHOUSES = {
  claude: new THREE.Vector3(0, 0, -8.5),
  codex: new THREE.Vector3(9.5, 0, 4.5),
  gemini: new THREE.Vector3(-9.5, 0, 4.5)
};
export const HALF = { x: 3.4, z: 2.6 };
export const ROLE_TITLE = { claude: "总指导仓", codex: "后端工坊", gemini: "评审质检仓" };
const BODY_H = 2.2;
const STATE_COLOR = { running: "#2fb383", error: "#e5484d", waiting: "#f0a92e", idle: "#c3c8d0" };

export function mat(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.9, metalness: 0, flatShading: true, ...extra });
}

export function box(w, h, d, material, x = 0, y = 0, z = 0) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

// 标签分两层：外层交给 CSS2DRenderer 定位，内层 body 承载内容并按可见区域缩放
export function label(html, className) {
  const anchor = document.createElement("div");
  const body = document.createElement("div");
  body.className = className;
  body.innerHTML = html;
  anchor.appendChild(body);
  const obj = new CSS2DObject(anchor);
  // CSS2DObject 会写入行内 pointer-events: auto，标签会挡住下面的 3D 物体，点击要穿透到画布
  anchor.style.pointerEvents = "none";
  obj.body = body;
  return obj;
}

export function tint(color, amount) {
  return new THREE.Color(color).lerp(new THREE.Color("#ffffff"), amount);
}

/** 任务当前在哪：负责它的代理的仓库，或已合并进 main */
export function locationOf(task, owner) {
  return task.stage === "已合并" ? "vault" : owner;
}

export function buildGround(scene) {
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(90, 70), new THREE.MeshStandardMaterial({ color: "#eef0f3", roughness: 1 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);
}

// ------------------------------------------------------------------ 仓库建筑

export function buildWarehouse(scene, id, pickables) {
  const color = AGENT_COLORS[id];
  const group = new THREE.Group();
  group.position.copy(WAREHOUSES[id]);
  const W = HALF.x * 2;
  const D = HALF.z * 2;

  const plinth = box(W + 0.8, 0.12, D + 0.8, mat(tint(color, 0.86)), 0, 0.06, 0);
  plinth.castShadow = false;
  group.add(plinth);
  const bodyMat = mat(tint(color, 0.72));
  const body = box(W, BODY_H, D, bodyMat, 0, BODY_H / 2 + 0.12, 0);
  group.add(body);
  group.add(box(W + 0.04, 0.22, D + 0.04, mat(color), 0, BODY_H + 0.02, 0));

  // 双坡屋顶
  const pitch = 0.42;
  const slope = HALF.z / Math.cos(pitch) + 0.25;
  const roofMat = mat(color);
  const roofs = [-1, 1].map(side => {
    const roof = box(W + 0.4, 0.16, slope, roofMat, 0, BODY_H + 0.12 + (Math.tan(pitch) * HALF.z) / 2, (side * HALF.z) / 2);
    roof.rotation.x = side * pitch;
    group.add(roof);
    return roof;
  });

  // 正面卷帘门与侧窗
  const door = box(2.4, 1.7, 0.08, mat(tint(color, 0.35)), 0, 0.97, HALF.z + 0.04);
  group.add(door);
  for (let i = 0; i < 5; i++) group.add(box(2.4, 0.03, 0.1, mat(tint(color, 0.2)), 0, 0.3 + i * 0.32, HALF.z + 0.06));
  for (const x of [-2.4, 2.4]) group.add(box(1.0, 0.6, 0.06, mat("#dfeaf6"), x, 1.5, HALF.z + 0.03));

  // 屋脊上的状态灯
  const beacon = new THREE.Mesh(
    new THREE.SphereGeometry(0.32, 12, 8),
    new THREE.MeshStandardMaterial({ color: STATE_COLOR.idle, emissive: STATE_COLOR.idle, emissiveIntensity: 0.2 })
  );
  beacon.position.set(0, BODY_H + 0.12 + Math.tan(pitch) * HALF.z + 0.3, 0);
  group.add(beacon);

  const tag = label("", "label agent-label");
  tag.body.style.setProperty("--c", color);
  tag.position.set(0, beacon.position.y + 1.0, 0);
  group.add(tag);

  for (const mesh of [body, door, ...roofs, plinth]) {
    mesh.userData = { kind: "agent", id };
    pickables.push(mesh);
  }
  scene.add(group);
  return { id, group, bodyMat, beacon, tag, state: "idle" };
}

export function updateWarehouse(view, agent, counts) {
  view.state = agent.state;
  const stock = Object.entries(counts)
    .map(([stage, n]) => `<span class="stock" style="--c:${STAGE_COLORS[stage]}">${esc(stage)} ${n}</span>`)
    .join("");
  view.tag.body.innerHTML = `
    <div class="agent-name">${esc(agent.name)}<span class="role">${esc(ROLE_TITLE[view.id])}</span><span class="chip ${agent.state}">${STATE_LABEL[agent.state] ?? esc(agent.state)}</span></div>
    <div class="agent-task">${agent.task ? `当前任务 <b>${esc(agent.task)}</b>` : "暂无任务"}</div>
    <div class="stocks">${stock || '<span class="muted">仓库空</span>'}</div>
    <div class="enter-hint">点击进入仓库 ›</div>`;
  const c = STATE_COLOR[agent.state] ?? STATE_COLOR.idle;
  view.beacon.material.color.set(c);
  view.beacon.material.emissive.set(c);
}

export function tickWarehouse(view, t, selected) {
  const running = view.state === "running";
  const error = view.state === "error";
  view.beacon.material.emissiveIntensity = running ? 0.6 + 0.5 * Math.sin(t * 4) : error ? (Math.sin(t * 8) > 0 ? 1.2 : 0.1) : 0.15;
  view.beacon.scale.setScalar(running ? 1 + 0.12 * Math.sin(t * 4) : 1);
  const isSel = selected?.kind === "agent" && selected.id === view.id;
  view.bodyMat.emissive.set(isSel ? AGENT_COLORS[view.id] : "#000000");
  view.bodyMat.emissiveIntensity = isSel ? 0.12 : 0;
  view.tag.body.classList.toggle("selected", isSel);
}
