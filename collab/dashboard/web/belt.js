// 传送带：仓库之间的三角环线、流动的数据包、任务卡片与中央的 main 归档库。
import * as THREE from "three";
import { AGENT_COLORS, STAGE_COLORS, esc } from "./theme.js";
import { HALF, WAREHOUSES, box, label, mat } from "./warehouse.js";

const BELT_TOP = 0.95;
const BELT_WIDTH = 1.1;
const LANE_GAP = 0.72;
const CARRY_Y = BELT_TOP + 0.45;
export const VAULT = new THREE.Vector3(0, 0, -0.6);
const VAULT_HALF = { x: 1.3, z: 1.1 };
const PALLET = new THREE.Vector3(0, 0, 1.75);
const DRAWERS = 8;

// 双向的边各走一条车道；车道在前进方向右侧，所以往返两条自动错开
export const LANES = [
  { id: "brief", from: "claude", to: "codex", label: "任务书", gap: 0 },
  { id: "report", from: "codex", to: "gemini", label: "完成报告", gap: LANE_GAP },
  { id: "rework", from: "gemini", to: "codex", label: "退回修改", gap: LANE_GAP },
  { id: "verdict", from: "gemini", to: "claude", label: "评审结论", gap: LANE_GAP },
  { id: "submit", from: "claude", to: "gemini", label: "提交评审", gap: LANE_GAP },
  { id: "merge", from: "claude", to: "vault", label: "合并", gap: 0 }
];

const nodeCenter = id => (id === "vault" ? VAULT : WAREHOUSES[id]);
const nodeHalf = id => (id === "vault" ? VAULT_HALF : HALF);

/** 从节点内一点沿方向 d 走到边界的距离 */
function exitDistance(point, center, half, d) {
  const tx = d.x ? ((d.x > 0 ? half.x : -half.x) - (point.x - center.x)) / d.x : Infinity;
  const tz = d.z ? ((d.z > 0 ? half.z : -half.z) - (point.z - center.z)) / d.z : Infinity;
  return Math.min(tx, tz);
}

function chevronTexture(base, mark) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, 128, 64);
  ctx.strokeStyle = mark;
  ctx.lineWidth = 9;
  for (const x of [24, 88]) {
    ctx.beginPath();
    ctx.moveTo(x, 12);
    ctx.lineTo(x + 18, 32);
    ctx.lineTo(x, 52);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// ------------------------------------------------------------------ 传送带

export function buildLanes(scene) {
  return LANES.map(spec => {
    const a = nodeCenter(spec.from);
    const b = nodeCenter(spec.to);
    const d = b.clone().sub(a).setY(0).normalize();
    const n = new THREE.Vector3(d.z, 0, -d.x);
    const sa = a.clone().addScaledVector(n, spec.gap);
    const sb = b.clone().addScaledVector(n, spec.gap);
    const start = sa.clone().addScaledVector(d, exitDistance(sa, a, nodeHalf(spec.from), d));
    const end = sb.clone().addScaledVector(d, -exitDistance(sb, b, nodeHalf(spec.to), d.clone().negate()));
    // 两端各伸进仓库一段，卡片在仓库里上带、在下一个仓库里下带
    const inA = start.clone().addScaledVector(d, -0.9).setY(CARRY_Y);
    const inB = end.clone().addScaledVector(d, 0.9).setY(CARRY_Y);
    const length = start.distanceTo(end) + 1.2;
    const mid = start.clone().add(end).multiplyScalar(0.5);

    const group = new THREE.Group();
    group.position.copy(mid);
    group.rotation.y = -Math.atan2(d.z, d.x);
    const frame = mat("#9aa1ad");
    group.add(box(length, 0.5, BELT_WIDTH, frame, 0, BELT_TOP - 0.3, 0));
    for (const side of [-1, 1]) group.add(box(length, 0.16, 0.1, mat("#c4c9d2"), 0, BELT_TOP, side * (BELT_WIDTH / 2 - 0.02)));
    for (let x = -length / 2 + 0.6; x < length / 2; x += 1.8) group.add(box(0.12, BELT_TOP - 0.45, 0.6, frame, x, (BELT_TOP - 0.45) / 2, 0));
    const rework = spec.id === "rework";
    const tex = chevronTexture(rework ? "#7a5560" : "#5b616e", rework ? "#f2a3a3" : "#9aa3b2");
    tex.repeat.set(length / 1.1, 1);
    const surface = new THREE.Mesh(new THREE.PlaneGeometry(length, BELT_WIDTH - 0.2), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.7 }));
    surface.rotation.x = -Math.PI / 2;
    surface.position.y = BELT_TOP + 0.01;
    surface.receiveShadow = true;
    group.add(surface);
    // 两端的装卸门框
    for (const x of [-length / 2 + 0.6, length / 2 - 0.6]) {
      for (const side of [-1, 1]) group.add(box(0.12, 2.0, 0.12, mat("#6b7280"), x, 1.0, side * (BELT_WIDTH / 2 + 0.12)));
      group.add(box(0.14, 0.18, BELT_WIDTH + 0.4, mat("#f0b429"), x, 2.0, 0));
    }
    scene.add(group);

    const tag = label(`<i></i>${esc(spec.label)}`, "label lane-tag");
    tag.body.style.setProperty("--c", spec.to === "vault" ? STAGE_COLORS["已合并"] : AGENT_COLORS[spec.from]);
    tag.position.copy(mid).setY(BELT_TOP + 0.55);
    scene.add(tag);

    const packets = new THREE.InstancedMesh(new THREE.BoxGeometry(0.34, 0.26, 0.34), mat(AGENT_COLORS[spec.from] ?? "#9ca3af"), 4);
    packets.castShadow = true;
    // 实例分布在整条车道上，几何体本身在原点，关闭视锥裁剪以免镜头移开原点时数据包消失
    packets.frustumCulled = false;
    packets.count = 0;
    scene.add(packets);
    return { ...spec, d, inA, inB, tex, tag, packets, energy: 0, transit: 0 };
  });
}

/** 在车道图上找从一个节点到另一个节点的车道序列（广度优先） */
export function route(from, to) {
  if (from === to) return [];
  const queue = [[from, []]];
  const seen = new Set([from]);
  while (queue.length) {
    const [node, path] = queue.shift();
    for (const lane of LANES) {
      if (lane.from !== node || seen.has(lane.to)) continue;
      const next = [...path, lane.id];
      if (lane.to === to) return next;
      seen.add(lane.to);
      queue.push([lane.to, next]);
    }
  }
  return null;
}

/** 卡片换仓库时的路径点：先升到带面，沿各段车道运输，最后落到目标位置 */
export function travelPath(lanes, from, to, slot) {
  const ids = route(from, to);
  if (!ids) return { points: [slot.clone()], lanes: [] };
  const points = [];
  for (const id of ids) {
    const lane = lanes.find(l => l.id === id);
    points.push(lane.inA.clone(), lane.inB.clone());
  }
  points.push(slot.clone());
  return { points, lanes: ids };
}

/** 各车道当前的“流量”：决定数据包数量和带速 */
export function laneEnergy(lane, data) {
  const has = new Set(data.tasks.flatMap(t => [t.stage, `${t.agent}:${t.stage}`]));
  const running = id => data.agents[id]?.state === "running";
  switch (lane.id) {
    case "brief": return running("claude") ? 2 : has.has("待开始") ? 1 : 0;
    case "report": return running("codex") ? 3 : has.has("codex:待评审") ? 1 : 0;
    case "rework": return has.has("codex:需修改") ? 2 : 0;
    case "verdict": return running("gemini") ? 3 : has.has("已通过") ? 1 : 0;
    case "submit": return running("claude") && has.has("claude:执行中") ? 2 : has.has("claude:待评审") ? 1 : 0;
    case "merge": return has.has("已通过") ? 1 : 0;
    default: return 0;
  }
}

const UP = new THREE.Vector3(0, 1, 0);

export function tickLanes(lanes, t, dt) {
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const s = new THREE.Vector3(1, 1, 1);
  const p = new THREE.Vector3();
  for (const lane of lanes) {
    const active = lane.energy > 0 || lane.transit > 0;
    const speed = lane.transit > 0 ? 0.9 : lane.energy > 1 ? 0.55 : active ? 0.25 : 0.04;
    lane.tex.offset.x -= dt * speed;
    lane.tag.body.classList.toggle("hot", active);
    // 数据包沿车道循环流动
    lane.packets.count = lane.energy;
    q.setFromAxisAngle(UP, -Math.atan2(lane.d.z, lane.d.x));
    for (let i = 0; i < lane.energy; i++) {
      const u = (t * 0.12 * (1 + lane.energy * 0.3) + i / lane.energy) % 1;
      p.lerpVectors(lane.inA, lane.inB, u).setY(BELT_TOP + 0.14);
      lane.packets.setMatrixAt(i, m.compose(p, q, s));
    }
    lane.packets.instanceMatrix.needsUpdate = true;
  }
}

// ------------------------------------------------------------------ 任务卡片

// 卡面用阶段色做底、白字，缩小后也能一眼看出阶段
export function cardTexture(task) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 300;
  const ctx = canvas.getContext("2d");
  const color = STAGE_COLORS[task.stage] ?? "#94a3b8";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 512, 300);
  ctx.fillStyle = "rgba(255, 255, 255, 0.16)";
  ctx.fillRect(0, 210, 512, 90);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
  ctx.lineWidth = 8;
  ctx.strokeRect(4, 4, 504, 292);
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(458, 74, 28, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = AGENT_COLORS[task.agent] ?? "#999";
  ctx.beginPath();
  ctx.arc(458, 74, 19, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 96px 'JetBrains Mono', monospace";
  ctx.fillText(task.id, 28, 116);
  ctx.font = "500 40px 'Noto Sans SC', sans-serif";
  ctx.fillText(task.title.length > 11 ? `${task.title.slice(0, 11)}…` : task.title, 30, 186);
  ctx.font = "700 36px 'Noto Sans SC', sans-serif";
  ctx.fillText(task.stage, 30, 268);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

export function createCard(scene, task, slot, pickables) {
  const group = new THREE.Group();
  const side = mat("#e5e7eb");
  const face = new THREE.MeshBasicMaterial({ map: cardTexture(task) });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.76, 0.05), [side, side, side, side, face, side]);
  mesh.castShadow = true;
  group.add(mesh);
  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0 })
  );
  edge.scale.setScalar(1.05);
  group.add(edge);
  mesh.userData = { kind: "task", id: task.id };
  pickables.push(mesh);
  group.position.copy(slot);
  scene.add(group);
  return { group, mesh, edge, stage: task.stage, task, target: slot.clone(), path: [], pathLanes: [], bob: Math.random() * 6 };
}

export function refreshCard(card, task) {
  const face = card.mesh.material[4];
  face.map?.dispose();
  face.map = cardTexture(task);
  face.needsUpdate = true;
}

export function disposeCard(scene, card, pickables) {
  scene.remove(card.group);
  card.mesh.material[4].map?.dispose();
  card.group.traverse(o => {
    o.geometry?.dispose();
    for (const m of [o.material].flat()) m?.dispose();
  });
  const i = pickables.indexOf(card.mesh);
  if (i >= 0) pickables.splice(i, 1);
}

/** 已合并的任务码放在归档库前的托盘上 */
export function vaultSlot(index) {
  const col = index % 3;
  const row = Math.floor(index / 3);
  return PALLET.clone().add(new THREE.Vector3((col - 1) * 1.32, 0.66 + row * 0.8, 0));
}

// ------------------------------------------------------------------ main 归档库

export function buildVault(scene, pickables) {
  const group = new THREE.Group();
  group.position.copy(VAULT);
  const body = box(2.4, 3.4, 2, mat("#dfe3e8"), 0, 1.7, 0);
  group.add(body);
  group.add(box(2.6, 0.12, 2.2, mat("#6cbf4a"), 0, 3.46, 0));
  const drawers = [];
  for (let i = 0; i < DRAWERS; i++) {
    const drawer = box(2.0, 0.32, 0.3, mat("#f3f4f6"), 0, 3.12 - i * 0.39, 1.05);
    const handle = box(0.5, 0.06, 0.08, mat("#9ca3af"), 0, 0, 0.18);
    drawer.add(handle);
    drawer.userData = { kind: "trunk" };
    pickables.push(drawer);
    group.add(drawer);
    drawers.push({ mesh: drawer, handle, pop: 0, base: 1.05 });
  }
  body.userData = { kind: "trunk" };
  pickables.push(body);
  scene.add(group);
  scene.add(box(4.2, 0.16, 1.2, mat("#c8a27a"), PALLET.x, 0.18, PALLET.z));
  const tag = label("", "label trunk-label");
  tag.position.set(VAULT.x, 4.25, VAULT.z);
  scene.add(tag);
  return { group, drawers, tag, known: null, confetti: [] };
}

export function updateVault(scene, vault, git) {
  const main = git.branches.find(b => b.name === "main");
  const ahead = git.branches.filter(b => b.name !== "main" && b.ahead > 0);
  vault.tag.body.innerHTML = `
    <div class="trunk-title">main <code>${esc(main?.sha ?? "")}</code></div>
    <div class="trunk-sub">${esc(main?.subject ?? "")}</div>
    <div class="trunk-sub">${ahead.length} 个分支领先 · 检出 <code>${esc(git.current)}</code></div>`;
  const commits = git.commits.slice(0, DRAWERS);
  commits.forEach((c, i) => {
    const d = vault.drawers[i];
    const color = new THREE.Color(AGENT_COLORS[c.author] ?? "#c9d3e6");
    d.mesh.material.color.copy(color).lerp(new THREE.Color("#ffffff"), 0.55);
    d.handle.material.color.copy(color);
    if (vault.known && !vault.known.has(c.sha)) {
      d.pop = 1;
      confetti(scene, vault, AGENT_COLORS[c.author] ?? "#9ca3af");
    }
  });
  vault.known = new Set(commits.map(c => c.sha));
}

const CONFETTI_GEOMETRY = new THREE.PlaneGeometry(0.16, 0.1);

function confetti(scene, vault, color) {
  const palette = [color, "#f0a92e", "#2fb383", "#3b7ddd", "#e07a3f"];
  const pieces = Array.from({ length: 36 }, (_, i) => {
    const piece = new THREE.Mesh(
      CONFETTI_GEOMETRY,
      new THREE.MeshBasicMaterial({ color: palette[i % palette.length], side: THREE.DoubleSide, transparent: true })
    );
    piece.position.set(VAULT.x, 3.8, VAULT.z);
    piece.userData.vel = new THREE.Vector3((Math.random() - 0.5) * 4, 3 + Math.random() * 3, (Math.random() - 0.5) * 4);
    piece.userData.spin = new THREE.Vector3(Math.random() * 8, Math.random() * 8, Math.random() * 8);
    scene.add(piece);
    return piece;
  });
  vault.confetti.push({ pieces, life: 0 });
}

export function tickVault(scene, vault, dt, selected) {
  for (const d of vault.drawers) {
    d.pop = Math.max(0, d.pop - dt * 0.5);
    d.mesh.position.z = d.base + Math.sin(d.pop * Math.PI) * 0.6;
  }
  vault.tag.body.classList.toggle("selected", selected);
  vault.confetti = vault.confetti.filter(burst => {
    burst.life += dt;
    for (const p of burst.pieces) {
      p.userData.vel.y -= dt * 6;
      p.position.addScaledVector(p.userData.vel, dt);
      if (p.position.y < 0.05) {
        p.position.y = 0.05;
        p.userData.vel.set(0, 0, 0);
      }
      p.rotation.x += p.userData.spin.x * dt;
      p.rotation.y += p.userData.spin.y * dt;
      p.material.opacity = Math.max(0, 1 - Math.max(0, burst.life - 1.8) / 1.2);
    }
    if (burst.life > 3) {
      for (const p of burst.pieces) {
        scene.remove(p);
        p.material.dispose();
      }
      return false;
    }
    return true;
  });
}
