// 仓库区：场地、三座切开屋顶的代理仓库（货架、工作台、装货区）与仓库内的任务区域。
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { AGENT_COLORS, STAGE_COLORS, STATE_LABEL, esc } from "./theme.js";

// 三座仓库摆成三角形：Claude 在后方，Codex 在右前，Gemini 在左前
export const WAREHOUSES = {
  claude: new THREE.Vector3(0, 0, -8.5),
  codex: new THREE.Vector3(9.5, 0, 4.5),
  gemini: new THREE.Vector3(-9.5, 0, 4.5)
};
export const HALF = { x: 3.6, z: 2.8 };
const WALL = 0.8;
const PILLAR = 3.3;
const ROLE_TITLE = { claude: "总指导仓", codex: "后端工坊", gemini: "评审质检仓" };

// 每座仓库里各阶段放在哪：货架 A / B、工作台、装货区（Claude 的待合并）
const ZONES = {
  claude: { 待开始: "shelfA", 阻塞: "shelfB", 需修改: "shelfB", 执行中: "bench", 已通过: "dock" },
  codex: { 需修改: "shelfA", 执行中: "bench" },
  gemini: { 待评审: "shelfA", 评审中: "bench" }
};
const AREA = {
  shelfA: new THREE.Vector3(-1.75, 0, -2.15),
  shelfB: new THREE.Vector3(1.6, 0, -2.15),
  desk: new THREE.Vector3(-0.9, 0, 0.6),
  dock: new THREE.Vector3(2.25, 0, 1.4)
};
const SHELF_LEVELS = [0.75, 1.62, 2.49];
const HAIR = { claude: "#6b4f3a", codex: "#2f2f35", gemini: "#c9a46c" };
const SKIN = "#f2d4bb";

export function mat(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.02, flatShading: true, ...extra });
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

export function canvasTexture(w, h, draw) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  draw(canvas.getContext("2d"), w, h);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** 任务当前在哪：负责它的代理的仓库，或已合并进 main 归档库 */
export function locationOf(task, owner) {
  return task.stage === "已合并" ? "vault" : owner;
}

// ------------------------------------------------------------------ 场地

export function buildYard(scene) {
  const tex = canvasTexture(512, 512, (ctx, w, h) => {
    ctx.fillStyle = "#ece7df";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "rgba(120, 110, 95, 0.12)";
    ctx.lineWidth = 2;
    for (let i = 0; i <= 512; i += 128) {
      ctx.beginPath();
      ctx.moveTo(i, 0);
      ctx.lineTo(i, h);
      ctx.moveTo(0, i);
      ctx.lineTo(w, i);
      ctx.stroke();
    }
  });
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(16, 12);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(64, 48), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(0, 0, -1.5);
  ground.receiveShadow = true;
  scene.add(ground);
  for (const [x, z] of [[-15.5, -9], [15.5, -9], [-5, -11.5], [5.5, -11.5], [-15.5, 9.5], [15.5, 9.5], [0, 9.8]]) scene.add(tree(x, z));
}

function tree(x, z) {
  const group = new THREE.Group();
  group.add(box(0.25, 1.1, 0.25, mat("#9b7653"), 0, 0.55, 0));
  const leaves = mat("#6dbb76");
  for (const [dx, dy, dz, r] of [[0, 1.6, 0, 0.8], [0.35, 2.2, 0.1, 0.55], [-0.3, 2.1, -0.2, 0.6]]) {
    const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 0), leaves);
    leaf.position.set(dx, dy, dz);
    leaf.castShadow = true;
    group.add(leaf);
  }
  group.position.set(x, 0, z);
  return group;
}

// ------------------------------------------------------------------ 仓库

export function buildWarehouse(scene, id, pickables) {
  const color = AGENT_COLORS[id];
  const tint = new THREE.Color(color).lerp(new THREE.Color("#ffffff"), 0.82);
  const group = new THREE.Group();
  group.position.copy(WAREHOUSES[id]);

  const slab = box(HALF.x * 2, 0.1, HALF.z * 2, new THREE.MeshStandardMaterial({ color: tint, roughness: 0.9 }), 0, 0.05, 0);
  slab.castShadow = false;
  group.add(slab);

  // 矮墙 + 角柱 + 屋架：切开屋顶的等距仓库，能看到里面
  const wallMat = mat("#f6f3ee");
  const trimMat = mat(color);
  const W = HALF.x * 2;
  const D = HALF.z * 2;
  for (const z of [-HALF.z, HALF.z]) {
    group.add(box(W, WALL, 0.16, wallMat, 0, WALL / 2, z));
    group.add(box(W, 0.08, 0.2, trimMat, 0, WALL, z));
  }
  for (const x of [-HALF.x, HALF.x]) {
    group.add(box(0.16, WALL, D, wallMat, x, WALL / 2, 0));
    group.add(box(0.2, 0.08, D, trimMat, x, WALL, 0));
  }
  const steel = mat("#c9ced6");
  for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) group.add(box(0.26, PILLAR, 0.26, steel, x * HALF.x, PILLAR / 2, z * HALF.z));
  // 只保留后梁和侧梁，前梁会横在镜头和货架之间
  group.add(box(W, 0.14, 0.14, steel, 0, PILLAR, -HALF.z));
  for (const x of [-HALF.x, HALF.x]) group.add(box(0.14, 0.14, D, steel, x, PILLAR, 0));

  // 后方招牌
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 1.0), new THREE.MeshBasicMaterial({
    map: canvasTexture(840, 200, (ctx, w, h) => {
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "#ffffff";
      ctx.font = "700 86px 'Noto Sans SC', sans-serif";
      ctx.fillText(id === "claude" ? "Claude" : id === "codex" ? "Codex" : "Gemini", 36, 122);
      ctx.font = "500 50px 'Noto Sans SC', sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(ROLE_TITLE[id], w - 36, 122);
    })
  }));
  sign.position.set(0, PILLAR + 0.75, -HALF.z);
  group.add(sign);
  group.add(box(4.4, 1.15, 0.08, mat("#ffffff"), 0, PILLAR + 0.75, -HALF.z - 0.06));

  // 货架
  const racks = { shelfA: rack(group, AREA.shelfA), shelfB: rack(group, AREA.shelfB) };
  if (id === "claude") {
    // 装货区托盘：已通过、等待合并的任务
    group.add(box(1.5, 0.16, 1.3, mat("#c8a27a"), AREA.dock.x, 0.18, AREA.dock.z));
  }

  const desk = buildDesk(group, id, AREA.desk);

  // 区域标签：显示该仓库里各阶段的任务数，点击查看该阶段
  const zones = {};
  for (const [stage, area] of Object.entries(ZONES[id])) {
    const at = zoneAnchor(area);
    const tag = label(`<i></i><b>${stage}</b><span class="count">0</span>`, "label gate-label");
    tag.body.style.setProperty("--c", STAGE_COLORS[stage]);
    tag.position.copy(at.label);
    group.add(tag);
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(at.size[0], at.size[1]),
      new THREE.MeshStandardMaterial({ color: STAGE_COLORS[stage], transparent: true, opacity: 0.22 }));
    pad.rotation.x = -Math.PI / 2;
    pad.position.copy(at.pad);
    group.add(pad);
    pad.userData = { kind: "stage", id: stage };
    pickables.push(pad);
    zones[stage] = { tag, pad, pulse: 0 };
  }
  // 货架隔板点击打开放在这排货架上的阶段；没有分配阶段的货架算作仓库本身
  for (const [area, boards] of Object.entries(racks)) {
    const stage = Object.keys(ZONES[id]).find(s => ZONES[id][s] === area);
    for (const board of boards) {
      board.userData = stage ? { kind: "stage", id: stage } : { kind: "agent", id };
      pickables.push(board);
    }
  }

  const tag = label("", "label agent-label");
  tag.body.style.setProperty("--c", color);
  tag.position.set(0, PILLAR + 1.75, -HALF.z);
  group.add(tag);

  slab.userData = { kind: "agent", id };
  pickables.push(slab);
  for (const mesh of [desk.torso, desk.head, desk.screen]) {
    mesh.userData = { kind: "agent", id };
    pickables.push(mesh);
  }
  scene.add(group);
  return { id, group, slab, zones, tag, ...desk, state: "idle", task: null, sig: "" };
}

function zoneAnchor(area) {
  if (area === "bench") {
    const p = AREA.desk.clone().add(new THREE.Vector3(0.85, 0, 0));
    return { label: p.clone().setY(2.55), pad: p.clone().setY(0.11).add(new THREE.Vector3(0, 0, -0.95)), size: [1.0, 0.5] };
  }
  if (area === "dock") {
    return { label: AREA.dock.clone().setY(0.25).add(new THREE.Vector3(0, 0, 0.95)), pad: AREA.dock.clone().setY(0.11), size: [1.7, 1.5] };
  }
  const p = AREA[area];
  return { label: p.clone().setY(3.45), pad: p.clone().setY(0.11).add(new THREE.Vector3(0, 0, 0.75)), size: [2.8, 0.7] };
}

function rack(group, at) {
  const upright = mat("#3b6fb6");
  const beam = mat("#f08c2e");
  const boardMat = mat("#d9d4cb");
  const boards = [];
  for (const dx of [-1.4, 1.4]) for (const dz of [-0.3, 0.3]) group.add(box(0.08, 3.1, 0.08, upright, at.x + dx, 1.55, at.z + dz));
  for (const y of SHELF_LEVELS) {
    const board = box(2.8, 0.06, 0.66, boardMat, at.x, y, at.z);
    group.add(board);
    group.add(box(2.86, 0.1, 0.06, beam, at.x, y - 0.05, at.z + 0.34));
    boards.push(board);
  }
  return boards;
}

/** 卡片在仓库里的世界坐标：货架两列三层，工作台叠放，装货区两列码放 */
export function slotIn(id, stage, index) {
  const origin = WAREHOUSES[id];
  const area = ZONES[id][stage] ?? "shelfB";
  if (area === "bench") {
    return origin.clone().add(AREA.desk).add(new THREE.Vector3(0.85 + (index % 2) * 0.15, 1.95 + index * 0.12, -0.15 - index * 0.08));
  }
  if (area === "dock") {
    const col = index % 2;
    const row = Math.floor(index / 2);
    return origin.clone().add(AREA.dock).add(new THREE.Vector3((col - 0.5) * 0.75, 0.68 + row * 0.82, 0));
  }
  const at = AREA[area];
  const col = index % 2;
  const level = Math.floor(index / 2) % SHELF_LEVELS.length;
  const layer = Math.floor(index / (2 * SHELF_LEVELS.length));
  return origin.clone().add(new THREE.Vector3(at.x + (col - 0.5) * 1.36, SHELF_LEVELS[level] + 0.42, at.z + 0.38 + layer * 0.22));
}

// ------------------------------------------------------------------ 工作台与人物

function buildDesk(parent, id, at) {
  const color = AGENT_COLORS[id];
  const group = new THREE.Group();
  group.position.copy(at);
  const wood = mat("#c8a27a");
  const legMat = mat("#8b8f98");
  group.add(box(2.6, 0.12, 1.4, wood, 0, 1.45, 0));
  for (const [x, z] of [[-1.2, -0.6], [1.2, -0.6], [-1.2, 0.6], [1.2, 0.6]]) group.add(box(0.1, 1.4, 0.1, legMat, x, 0.7, z));

  // 显示器：屏幕朝向人物（+z），斜前方的镜头能看到屏幕
  group.add(box(0.12, 0.45, 0.12, legMat, -0.35, 1.72, -0.4));
  group.add(box(1.4, 0.82, 0.1, mat("#2b2f38"), -0.35, 2.3, -0.45));
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 0.72), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
  screen.position.set(-0.35, 2.3, -0.39);
  group.add(screen);
  group.add(box(1.0, 0.05, 0.36, mat("#e5e7eb"), 0.1, 1.53, 0.3));

  const lampMat = mat("#f4f4f5");
  group.add(box(0.3, 0.06, 0.3, lampMat, -1.05, 1.54, -0.4));
  group.add(box(0.05, 0.6, 0.05, lampMat, -1.05, 1.85, -0.4));
  const shade = new THREE.Mesh(new THREE.ConeGeometry(0.25, 0.3, 10, 1, true), new THREE.MeshStandardMaterial({
    color, emissive: "#ffd9a0", emissiveIntensity: 0, side: THREE.DoubleSide, flatShading: true
  }));
  shade.position.set(-0.95, 2.15, -0.35);
  shade.rotation.z = -0.5;
  group.add(shade);
  const lamp = new THREE.PointLight("#ffd9a0", 0, 5, 2);
  lamp.position.set(-0.8, 1.9, -0.2);
  group.add(lamp);

  if (id === "gemini") {
    const lens = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.04, 6, 16), mat("#6b7280"));
    lens.rotation.x = -Math.PI / 2;
    lens.position.set(-1.0, 1.55, 0.35);
    group.add(lens, box(0.28, 0.04, 0.06, mat("#7c5a3a"), -0.74, 1.55, 0.5));
  }

  const chairMat = mat("#4b5563");
  group.add(box(0.95, 0.14, 0.9, chairMat, 0.1, 1.0, 1.3));
  group.add(box(0.95, 0.65, 0.12, chairMat, 0.1, 1.38, 1.78));
  group.add(box(0.12, 0.9, 0.12, legMat, 0.1, 0.5, 1.3));
  group.add(box(0.85, 0.06, 0.85, legMat, 0.1, 0.05, 1.3));

  // 人物：面朝显示器（-z），镜头看到背影和屏幕
  const person = new THREE.Group();
  person.position.set(0.1, 0, 1.25);
  const shirt = mat(color);
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 0.5, 4, 10), shirt);
  torso.position.y = 1.72;
  torso.castShadow = true;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.34, 14, 10), mat(SKIN));
  head.position.y = 2.48;
  head.castShadow = true;
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.36, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), mat(HAIR[id]));
  hair.rotation.x = 0.35;
  hair.position.set(0, 0.03, 0.02);
  head.add(hair);
  person.add(torso, head);
  if (id === "codex") {
    const phones = new THREE.Mesh(new THREE.TorusGeometry(0.38, 0.05, 6, 20, Math.PI), mat("#1f2937"));
    phones.position.y = 0.05;
    head.add(phones);
  }
  const arms = [-1, 1].map(side => {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.44, 2.0, 0);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.1, 0.52, 3, 8), shirt);
    arm.position.y = -0.33;
    arm.castShadow = true;
    pivot.add(arm);
    pivot.rotation.x = -1.05;
    person.add(pivot);
    return pivot;
  });
  group.add(person);
  parent.add(group);
  return { screen, shade, lamp, person, head, torso, arms };
}

function drawScreen(view, agent) {
  const state = agent.state;
  const tex = canvasTexture(512, 296, (ctx, w, h) => {
    ctx.fillStyle = state === "running" ? "#16324a" : state === "error" ? "#fde2e2" : "#eef2f7";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = AGENT_COLORS[view.id];
    ctx.fillRect(0, 0, w, 16);
    if (state === "running") {
      const palette = ["#7dd3fc", "#86efac", "#fcd34d", "#c4b5fd", "#f9a8d4"];
      ctx.globalAlpha = 0.75;
      for (let i = 0; i < 9; i++) {
        ctx.fillStyle = palette[i % palette.length];
        ctx.fillRect(28 + (i % 3) * 22, 120 + i * 18, 80 + ((i * 97) % 260), 9);
      }
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = state === "running" ? "#ffffff" : state === "error" ? "#b42318" : "#1f2937";
    ctx.font = "700 64px 'JetBrains Mono', monospace";
    ctx.fillText(agent.task ?? "—", 28, 96);
    ctx.font = "500 30px 'Noto Sans SC', sans-serif";
    ctx.fillStyle = state === "running" ? "#a7f3d0" : state === "error" ? "#b42318" : "#6b7280";
    ctx.textAlign = "right";
    ctx.fillText(STATE_LABEL[state] ?? state, w - 24, 96);
  });
  view.screen.material.map?.dispose();
  view.screen.material.map = tex;
  view.screen.material.needsUpdate = true;
}

export function updateWarehouse(view, agent, counts) {
  view.state = agent.state;
  view.task = agent.task;
  view.tag.body.innerHTML = `
    <div class="agent-name">${esc(agent.name)}<span class="chip ${agent.state}">${STATE_LABEL[agent.state] ?? esc(agent.state)}</span></div>
    <div class="agent-task">${agent.task ? `当前任务 <b>${esc(agent.task)}</b>` : "暂无任务"}</div>`;
  const sig = `${agent.state}|${agent.task}`;
  if (sig !== view.sig) {
    view.sig = sig;
    drawScreen(view, agent);
  }
  for (const [stage, zone] of Object.entries(view.zones)) {
    const n = counts[stage] ?? 0;
    zone.tag.body.querySelector(".count").textContent = n;
    zone.tag.body.classList.toggle("empty", n === 0);
  }
}

export function tickWarehouse(view, t, dt, selected) {
  const running = view.state === "running";
  const error = view.state === "error";
  const phase = view.id.length;
  // 运行中打字，空闲时慢慢呼吸
  view.arms.forEach((pivot, i) => {
    pivot.rotation.x = running ? -1.05 + Math.sin(t * 16 + i * Math.PI) * 0.09 : -1.0 + Math.sin(t * 0.8 + phase) * 0.02;
  });
  view.torso.scale.y = 1 + Math.sin(t * 1.6 + phase) * (running ? 0.01 : 0.025);
  view.head.position.y = 2.48 + (running ? Math.sin(t * 8) * 0.025 : Math.sin(t * 1.6 + phase) * 0.02);
  view.head.rotation.y = running ? Math.sin(t * 0.9) * 0.15 : Math.sin(t * 0.4 + phase) * 0.3;
  view.lamp.intensity = running ? 3.5 : 0;
  view.shade.material.emissiveIntensity = running ? 0.9 : 0;
  view.screen.material.color.setScalar(running ? 0.92 + Math.sin(t * 25) * 0.04 : error ? (Math.sin(t * 8) > 0 ? 1 : 0.55) : 1);
  const isSel = selected?.kind === "agent" && selected.id === view.id;
  view.slab.material.emissive.set(isSel ? AGENT_COLORS[view.id] : "#000000");
  view.slab.material.emissiveIntensity = isSel ? 0.18 : 0;
  view.tag.body.classList.toggle("selected", isSel);
  for (const [stage, zone] of Object.entries(view.zones)) {
    zone.pulse = Math.max(0, zone.pulse - dt * 0.8);
    const zoneSel = selected?.kind === "stage" && selected.id === stage;
    zone.pad.material.opacity = 0.22 + zone.pulse * 0.5 + (zoneSel ? 0.25 : 0);
    zone.tag.body.classList.toggle("selected", zoneSel);
  }
}
