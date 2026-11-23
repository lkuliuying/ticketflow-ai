// 传送带：阶段分段、“需修改”回流带、任务卡片与 main 归档柜。
import * as THREE from "three";
import { AGENT_COLORS, STAGE_COLORS, esc } from "./theme.js";
import { box, label, mat } from "./office.js";

export const BELT_Z = 3;
const BELT_DEPTH = 2.6;
const BELT_TOP = 0.9;
const SEG = 3.4;
export const MAIN_STAGES = ["待开始", "阻塞", "执行中", "待评审", "评审中", "已通过", "已合并"];
const LANE = { z: 0.2, from: 3.4, to: -3.4, top: 0.45 };
const CABINET = new THREE.Vector3(14.8, 0, BELT_Z);
const DRAWERS = 8;

const stageX = stage => (MAIN_STAGES.indexOf(stage) - (MAIN_STAGES.length - 1) / 2) * SEG;

function stripeTexture(color = "#5b616e", stripe = "#6b7280") {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 128, 64);
  ctx.fillStyle = stripe;
  for (let x = 0; x < 128; x += 32) ctx.fillRect(x, 0, 10, 64);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function cardTexture(task) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 300;
  const ctx = canvas.getContext("2d");
  const color = STAGE_COLORS[task.stage];
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, 512, 300);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 512, 22);
  ctx.strokeStyle = "#e5e7eb";
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 506, 294);
  ctx.fillStyle = AGENT_COLORS[task.agent] ?? "#999";
  ctx.beginPath();
  ctx.arc(462, 78, 20, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#1f2937";
  ctx.font = "700 76px 'JetBrains Mono', monospace";
  ctx.fillText(task.id, 32, 108);
  ctx.font = "500 38px 'Noto Sans SC', sans-serif";
  ctx.fillStyle = "#374151";
  const title = task.title.length > 12 ? `${task.title.slice(0, 12)}…` : task.title;
  ctx.fillText(title, 32, 182);
  ctx.fillStyle = color;
  ctx.font = "700 34px 'Noto Sans SC', sans-serif";
  ctx.fillText(task.stage, 32, 258);
  ctx.fillStyle = "#9ca3af";
  ctx.font = "400 26px 'JetBrains Mono', monospace";
  const branch = task.branch ?? "—";
  ctx.fillText(branch.length > 18 ? `${branch.slice(0, 18)}…` : branch, 190, 258);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

// ------------------------------------------------------------------ 传送带

export function buildBelt(scene, pickables) {
  const frame = mat("#9aa1ad");
  const length = MAIN_STAGES.length * SEG + 1.2;
  scene.add(box(length, 0.7, BELT_DEPTH, frame, 0, 0.45, BELT_Z));
  const tex = stripeTexture();
  tex.repeat.set(length / 1.2, 1);
  const surface = new THREE.Mesh(new THREE.PlaneGeometry(length, BELT_DEPTH - 0.3), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.7 }));
  surface.rotation.x = -Math.PI / 2;
  surface.position.set(0, BELT_TOP - 0.09, BELT_Z);
  surface.receiveShadow = true;
  scene.add(surface);
  for (const dz of [-1, 1]) scene.add(box(length, 0.2, 0.16, mat("#c4c9d2"), 0, BELT_TOP, BELT_Z + dz * (BELT_DEPTH / 2 - 0.05)));
  for (let x = -length / 2 + 1; x < length / 2; x += 2.4) {
    for (const dz of [-1, 1]) scene.add(box(0.16, 0.5, 0.16, frame, x, 0.25, BELT_Z + dz * (BELT_DEPTH / 2 - 0.25)));
  }

  const gates = {};
  for (const stage of MAIN_STAGES) {
    const x = stageX(stage);
    const color = new THREE.Color(STAGE_COLORS[stage]);
    const strip = box(SEG - 0.25, 0.5, 0.08, new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.1, roughness: 0.6 }),
      x, 0.5, BELT_Z + BELT_DEPTH / 2 + 0.05);
    scene.add(strip);
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(SEG - 0.3, 1.1), new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.18 }));
    pad.rotation.x = -Math.PI / 2;
    pad.position.set(x, 0.02, BELT_Z + BELT_DEPTH / 2 + 0.75);
    scene.add(pad);
    const tag = label(`<i></i><b>${stage}</b><span class="count">0</span>`, "label gate-label");
    tag.body.style.setProperty("--c", STAGE_COLORS[stage]);
    tag.position.set(x, 0.15, BELT_Z + BELT_DEPTH / 2 + 0.85);
    scene.add(tag);
    for (const m of [strip, pad]) {
      m.userData = { kind: "stage", id: stage };
      pickables.push(m);
    }
    gates[stage] = { strip, pad, tag, pulse: 0 };
  }

  // “需修改”回流带：在主传送带和工位之间，方向从评审段指回 Codex
  const laneLen = LANE.from - LANE.to + 1.6;
  const laneX = (LANE.from + LANE.to) / 2;
  const red = new THREE.Color(STAGE_COLORS["需修改"]);
  scene.add(box(laneLen, 0.3, 1.3, mat("#b8bec8"), laneX, 0.2, LANE.z));
  const laneTex = stripeTexture("#f3d0d0", "#ef9a9a");
  laneTex.repeat.set(laneLen / 1.2, 1);
  const lane = new THREE.Mesh(new THREE.PlaneGeometry(laneLen, 1.1), new THREE.MeshStandardMaterial({ map: laneTex, roughness: 0.8 }));
  lane.rotation.x = -Math.PI / 2;
  lane.position.set(laneX, LANE.top - 0.08, LANE.z);
  lane.receiveShadow = true;
  scene.add(lane);
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.35, 0.7, 3), new THREE.MeshStandardMaterial({ color: red, emissive: red, emissiveIntensity: 0.2, flatShading: true }));
  arrow.rotation.z = Math.PI / 2;
  arrow.position.set(LANE.to - 1.3, 0.45, LANE.z);
  scene.add(arrow);
  const laneTag = label(`<i></i><b>需修改</b><span class="count">0</span><span class="muted">退回 Codex</span>`, "label gate-label");
  laneTag.body.style.setProperty("--c", STAGE_COLORS["需修改"]);
  laneTag.position.set(laneX, 0.1, LANE.z - 0.95);
  scene.add(laneTag);
  lane.userData = { kind: "stage", id: "需修改" };
  pickables.push(lane);
  gates["需修改"] = { strip: arrow, pad: lane, tag: laneTag, pulse: 0 };

  return { gates, textures: [tex, laneTex] };
}

// 每个阶段两列排开，后排逐级抬高，像阶梯看台一样不互相遮挡
export function slotPosition(stage, index, total) {
  if (stage === "需修改") {
    const step = Math.min(1.7, (LANE.from - LANE.to) / Math.max(1, total - 1));
    return new THREE.Vector3(LANE.from - index * step, LANE.top + 0.6, LANE.z);
  }
  const cols = total > 1 ? 2 : 1;
  const col = index % cols;
  const row = Math.floor(index / cols);
  const x = stageX(stage) + (cols === 2 ? (col - 0.5) * 1.72 : 0);
  return new THREE.Vector3(x, BELT_TOP + 0.6 + row * 0.5, BELT_Z + 0.75 - row * 0.62);
}

export function createCard(scene, task, slot, pickables) {
  const group = new THREE.Group();
  const side = mat("#e5e7eb");
  const face = new THREE.MeshBasicMaterial({ map: cardTexture(task) });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.05, 0.06), [side, side, side, side, face, side]);
  mesh.castShadow = true;
  group.add(mesh);
  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: STAGE_COLORS[task.stage], transparent: true, opacity: 0.6 })
  );
  edge.scale.setScalar(1.04);
  group.add(edge);
  // 底座：卡片立在传送带上
  group.add(box(0.5, 0.06, 0.3, mat("#d1d5db"), 0, -0.56, 0));
  mesh.userData = { kind: "task", id: task.id };
  pickables.push(mesh);
  group.position.copy(slot);
  scene.add(group);
  return { group, mesh, edge, stage: task.stage, task, target: slot.clone(), bob: Math.random() * 6, link: null };
}

export function refreshCard(card, task) {
  const face = card.mesh.material[4];
  face.map?.dispose();
  face.map = cardTexture(task);
  face.needsUpdate = true;
  card.edge.material.color.set(STAGE_COLORS[task.stage]);
}

export function disposeCard(scene, card, pickables) {
  scene.remove(card.group);
  card.mesh.material[4].map?.dispose();
  card.group.traverse(o => {
    o.geometry?.dispose();
    for (const m of [o.material].flat()) m?.dispose();
  });
  if (card.link) {
    scene.remove(card.link);
    card.link.geometry.dispose();
    card.link.material.dispose();
  }
  const i = pickables.indexOf(card.mesh);
  if (i >= 0) pickables.splice(i, 1);
}

// 被处理中的卡片到工位的虚线
export function linkLine(from, to, color) {
  const mid = from.clone().add(to).multiplyScalar(0.5);
  mid.y += 2.2;
  const points = new THREE.QuadraticBezierCurve3(from, mid, to).getPoints(40);
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineDashedMaterial({ color, dashSize: 0.25, gapSize: 0.18, transparent: true, opacity: 0.8 })
  );
  line.computeLineDistances();
  return line;
}

// ------------------------------------------------------------------ main 归档柜

export function buildCabinet(scene, pickables) {
  const group = new THREE.Group();
  group.position.copy(CABINET);
  const body = box(2.4, 4, 2, mat("#dfe3e8"), 0, 2, 0);
  group.add(body);
  group.add(box(2.6, 0.12, 2.2, mat("#c2c8d0"), 0, 4.06, 0));
  // 入口滑槽：传送带末端进入归档柜
  group.add(box(1.0, 0.1, 2.0, mat("#9aa1ad"), -1.6, 0.95, 0));
  const drawers = [];
  for (let i = 0; i < DRAWERS; i++) {
    const drawer = box(2.0, 0.38, 0.3, mat("#f3f4f6"), 0, 3.7 - i * 0.45, 1.05);
    const handle = box(0.5, 0.06, 0.08, mat("#9ca3af"), 0, 0, 0.18);
    drawer.add(handle);
    drawer.userData = { kind: "trunk" };
    pickables.push(drawer);
    group.add(drawer);
    drawers.push({ mesh: drawer, handle, pop: 0, base: 1.05 });
  }
  body.userData = { kind: "trunk" };
  pickables.push(body);
  const tag = label("", "label trunk-label");
  tag.position.set(0, 4.6, 0.6);
  group.add(tag);
  scene.add(group);
  return { group, drawers, tag, known: null, confetti: [] };
}

export function updateCabinet(scene, cab, git) {
  const main = git.branches.find(b => b.name === "main");
  const ahead = git.branches.filter(b => b.name !== "main" && b.ahead > 0);
  cab.tag.body.innerHTML = `
    <div class="trunk-title">main <code>${esc(main?.sha ?? "")}</code></div>
    <div class="trunk-sub">${esc(main?.subject ?? "")}</div>
    <div class="trunk-sub">${ahead.length} 个分支领先 · 检出 <code>${esc(git.current)}</code></div>`;
  const commits = git.commits.slice(0, DRAWERS);
  commits.forEach((c, i) => {
    const d = cab.drawers[i];
    const color = new THREE.Color(AGENT_COLORS[c.author] ?? "#c9d3e6");
    d.mesh.material.color.copy(color).lerp(new THREE.Color("#ffffff"), 0.55);
    d.handle.material.color.copy(color);
    if (cab.known && !cab.known.has(c.sha)) {
      d.pop = 1;
      confetti(scene, cab, AGENT_COLORS[c.author] ?? "#9ca3af");
    }
  });
  cab.known = new Set(commits.map(c => c.sha));
}

const CONFETTI_GEOMETRY = new THREE.PlaneGeometry(0.16, 0.1);

function confetti(scene, cab, color) {
  const palette = [color, "#f0a92e", "#2fb383", "#3b7ddd", "#e07a3f"];
  const pieces = Array.from({ length: 36 }, (_, i) => {
    const piece = new THREE.Mesh(
      CONFETTI_GEOMETRY,
      new THREE.MeshBasicMaterial({ color: palette[i % palette.length], side: THREE.DoubleSide, transparent: true })
    );
    piece.position.set(cab.group.position.x, 4.4, cab.group.position.z);
    piece.userData.vel = new THREE.Vector3((Math.random() - 0.5) * 4, 3 + Math.random() * 3, (Math.random() - 0.5) * 4);
    piece.userData.spin = new THREE.Vector3(Math.random() * 8, Math.random() * 8, Math.random() * 8);
    scene.add(piece);
    return piece;
  });
  cab.confetti.push({ pieces, life: 0 });
}

export function tickCabinet(scene, cab, dt, t, selected) {
  for (const d of cab.drawers) {
    d.pop = Math.max(0, d.pop - dt * 0.5);
    d.mesh.position.z = d.base + Math.sin(d.pop * Math.PI) * 0.6;
  }
  cab.tag.body.classList.toggle("selected", selected);
  cab.confetti = cab.confetti.filter(burst => {
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
