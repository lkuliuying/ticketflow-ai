// 办公室：房间、白板与三个代理的工位（桌子、显示器、台灯、低多边形人物）。
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { AGENT_COLORS, STAGE_COLORS, STATE_LABEL, esc } from "./theme.js";

export const ROOM = { minX: -17, maxX: 17, minZ: -7.5, maxZ: 8.5, wall: 4.2 };
// 工位与传送带上的职责位置对齐：Claude 在起点下发，Codex 在“执行中”旁，Gemini 在评审段旁
export const DESKS = {
  claude: new THREE.Vector3(-10.2, 0, -4.2),
  codex: new THREE.Vector3(-3.4, 0, -4.2),
  gemini: new THREE.Vector3(1.7, 0, -4.2)
};
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

function canvasTexture(w, h, draw) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  draw(canvas.getContext("2d"), w, h);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

// ------------------------------------------------------------------ 房间

export function buildRoom(scene) {
  const width = ROOM.maxX - ROOM.minX;
  const depth = ROOM.maxZ - ROOM.minZ;
  const floorTex = canvasTexture(512, 512, (ctx, w, h) => {
    ctx.fillStyle = "#efe4d3";
    ctx.fillRect(0, 0, w, h);
    for (let row = 0; row < 8; row++) {
      const y = row * 64;
      ctx.fillStyle = row % 2 ? "#ebdfcc" : "#f1e7d8";
      ctx.fillRect(0, y, w, 64);
      ctx.strokeStyle = "rgba(150, 120, 90, 0.18)";
      ctx.strokeRect(0, y, w, 64);
      const off = (row * 173) % 256;
      for (let x = off; x < w; x += 256) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + 64);
        ctx.stroke();
      }
    }
  });
  floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping;
  floorTex.repeat.set(width / 6, depth / 6);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set((ROOM.minX + ROOM.maxX) / 2, 0, (ROOM.minZ + ROOM.maxZ) / 2);
  floor.receiveShadow = true;
  scene.add(floor);

  // 切开式等距办公室：只有后墙和左墙，墙脚一条踢脚线
  const wallMat = mat("#f7f4ef");
  const trimMat = mat("#d9cdbb");
  scene.add(box(width, ROOM.wall, 0.3, wallMat, floor.position.x, ROOM.wall / 2, ROOM.minZ - 0.15));
  scene.add(box(0.3, ROOM.wall, depth, wallMat, ROOM.minX - 0.15, ROOM.wall / 2, floor.position.z));
  scene.add(box(width, 0.25, 0.34, trimMat, floor.position.x, 0.125, ROOM.minZ - 0.13));
  scene.add(box(0.34, 0.25, depth, trimMat, ROOM.minX - 0.13, 0.125, floor.position.z));

  // 窗户
  const glass = new THREE.MeshStandardMaterial({ color: "#cfe6fb", emissive: "#bcdcf7", emissiveIntensity: 0.35, roughness: 0.2 });
  const frame = mat("#ffffff");
  for (const x of [-12.5, 8.5, 13.5]) {
    scene.add(box(3.2, 2.2, 0.06, frame, x, 2.35, ROOM.minZ + 0.02));
    scene.add(box(2.9, 1.9, 0.08, glass, x, 2.35, ROOM.minZ + 0.04));
    scene.add(box(0.08, 1.9, 0.1, frame, x, 2.35, ROOM.minZ + 0.06));
  }
  for (const z of [-2, 4]) {
    scene.add(box(0.06, 2.2, 3.2, frame, ROOM.minX + 0.02, 2.35, z));
    scene.add(box(0.08, 1.9, 2.9, glass, ROOM.minX + 0.04, 2.35, z));
  }

  // 绿植
  for (const [x, z] of [[-16, -6.5], [16, -6.5], [-16, 7.5]]) scene.add(plant(x, z));

  // 后墙白板：显示各阶段的任务数
  const board = new THREE.Mesh(new THREE.PlaneGeometry(6, 2.4), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
  board.position.set(-2.8, 2.5, ROOM.minZ + 0.03);
  scene.add(board);
  scene.add(box(6.3, 2.7, 0.05, mat("#c8ced8"), -2.8, 2.5, ROOM.minZ + 0.01));
  return { board };
}

function plant(x, z) {
  const group = new THREE.Group();
  group.add(box(0.8, 0.8, 0.8, mat("#d7b98e"), 0, 0.4, 0));
  const leafMat = mat("#5fae6b");
  for (const [dx, dy, dz, r] of [[0, 1.4, 0, 0.6], [0.3, 1.9, 0.1, 0.42], [-0.25, 1.8, -0.2, 0.45]]) {
    const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 0), leafMat);
    leaf.position.set(dx, dy, dz);
    leaf.castShadow = true;
    group.add(leaf);
  }
  group.position.set(x, 0, z);
  return group;
}

export function drawWhiteboard(board, data) {
  const counts = {};
  for (const t of data.tasks) counts[t.stage] = (counts[t.stage] ?? 0) + 1;
  // 计数没变就不重绘，避免每 3 秒重新上传贴图
  const sig = JSON.stringify([data.tasks.length, data.stages.map(s => counts[s] ?? 0)]);
  if (board.userData.sig === sig) return;
  board.userData.sig = sig;
  const max = Math.max(1, ...Object.values(counts));
  const tex = canvasTexture(1000, 400, (ctx, w, h) => {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#1f2937";
    ctx.font = "700 40px 'Noto Sans SC', sans-serif";
    ctx.fillText("任务看板", 36, 62);
    ctx.fillStyle = "#6b7280";
    ctx.font = "400 26px 'Noto Sans SC', sans-serif";
    ctx.fillText(`共 ${data.tasks.length} 项`, 240, 62);
    const stages = data.stages;
    const col = (w - 72) / stages.length;
    stages.forEach((s, i) => {
      const x = 36 + i * col;
      const n = counts[s] ?? 0;
      const barH = (n / max) * 190;
      ctx.fillStyle = "#f1f3f6";
      ctx.fillRect(x + 12, 110, col - 24, 190);
      ctx.fillStyle = STAGE_COLORS[s];
      ctx.fillRect(x + 12, 300 - barH, col - 24, barH);
      ctx.fillStyle = "#1f2937";
      ctx.font = "700 30px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(String(n), x + col / 2, 300 - barH - 10 < 140 ? 140 : 300 - barH - 10);
      ctx.fillStyle = "#4b5563";
      ctx.font = "500 24px 'Noto Sans SC', sans-serif";
      ctx.fillText(s, x + col / 2, 345);
      ctx.textAlign = "left";
    });
  });
  board.material.map?.dispose();
  board.material.map = tex;
  board.material.needsUpdate = true;
}

// ------------------------------------------------------------------ 工位与人物

export function buildDesk(scene, id, pickables) {
  const color = AGENT_COLORS[id];
  const group = new THREE.Group();
  group.position.copy(DESKS[id]);

  // 地毯标出工位范围
  const rug = new THREE.Mesh(
    new THREE.CircleGeometry(2.6, 40),
    new THREE.MeshStandardMaterial({ color: new THREE.Color(color).lerp(new THREE.Color("#ffffff"), 0.78), roughness: 1 })
  );
  rug.rotation.x = -Math.PI / 2;
  rug.position.set(0, 0.01, 0.5);
  rug.receiveShadow = true;
  group.add(rug);

  const wood = mat("#c8a27a");
  const legMat = mat("#8b8f98");
  group.add(box(3.4, 0.14, 1.6, wood, 0, 1.45, 0));
  for (const [x, z] of [[-1.55, -0.65], [1.55, -0.65], [-1.55, 0.65], [1.55, 0.65]]) group.add(box(0.1, 1.4, 0.1, legMat, x, 0.7, z));

  // 显示器：屏幕朝向人物（+z），从斜前方的镜头能看到屏幕
  group.add(box(0.12, 0.85, 0.12, legMat, -0.35, 1.95, -0.45));
  group.add(box(1.8, 1.1, 0.1, mat("#2b2f38"), -0.35, 2.85, -0.5));
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.66, 0.96), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
  screen.position.set(-0.35, 2.85, -0.44);
  group.add(screen);
  group.add(box(1.2, 0.05, 0.4, mat("#e5e7eb"), 0.3, 1.54, 0.3));

  // 台灯
  const lampMat = mat("#f4f4f5");
  group.add(box(0.36, 0.06, 0.36, lampMat, 1.35, 1.55, -0.35));
  group.add(box(0.05, 0.7, 0.05, lampMat, 1.35, 1.9, -0.35));
  const shade = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.32, 10, 1, true), new THREE.MeshStandardMaterial({
    color: color, emissive: "#ffd9a0", emissiveIntensity: 0, side: THREE.DoubleSide, flatShading: true
  }));
  shade.position.set(1.2, 2.25, -0.3);
  shade.rotation.z = 0.5;
  group.add(shade);
  const lamp = new THREE.PointLight("#ffd9a0", 0, 5, 2);
  lamp.position.set(1.1, 2.0, -0.2);
  group.add(lamp);

  // 桌面小物：Claude 一摞任务书，Gemini 一把放大镜
  if (id === "claude") {
    for (let i = 0; i < 4; i++) group.add(box(0.6, 0.04, 0.8, mat(i % 2 ? "#ffffff" : "#f3efe6"), -1.15, 1.55 + i * 0.045, 0.05 + i * 0.02));
  }
  if (id === "gemini") {
    const lens = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.04, 6, 16), mat("#6b7280"));
    lens.rotation.x = -Math.PI / 2;
    lens.position.set(-1.15, 1.56, 0.1);
    group.add(lens, box(0.3, 0.04, 0.06, mat("#7c5a3a"), -0.85, 1.56, 0.28));
  }

  // 椅子
  const chairMat = mat("#4b5563");
  group.add(box(1.0, 0.14, 0.95, chairMat, 0.45, 1.0, 1.35));
  group.add(box(1.0, 0.7, 0.12, chairMat, 0.45, 1.4, 1.85));
  group.add(box(0.12, 0.9, 0.12, legMat, 0.45, 0.5, 1.35));
  group.add(box(0.9, 0.06, 0.9, legMat, 0.45, 0.05, 1.35));

  // 人物：面朝显示器（-z），镜头看到背影和屏幕
  const person = new THREE.Group();
  person.position.set(0.45, 0, 1.3);
  const shirt = mat(color);
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 0.55, 4, 10), shirt);
  torso.position.y = 1.75;
  torso.castShadow = true;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.36, 14, 10), mat(SKIN));
  head.position.y = 2.55;
  head.castShadow = true;
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.38, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), mat(HAIR[id]));
  hair.rotation.x = 0.35;
  head.add(hair);
  hair.position.set(0, 0.03, 0.02);
  person.add(torso, head);
  if (id === "codex") {
    const phones = new THREE.Mesh(new THREE.TorusGeometry(0.4, 0.05, 6, 20, Math.PI), mat("#1f2937"));
    phones.position.y = 0.05;
    head.add(phones);
  }
  const arms = [-1, 1].map(side => {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.46, 2.05, 0);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.11, 0.55, 3, 8), shirt);
    arm.position.y = -0.35;
    arm.castShadow = true;
    pivot.add(arm);
    pivot.rotation.x = -1.05;
    person.add(pivot);
    return pivot;
  });
  group.add(person);

  const tag = label("", "label agent-label");
  tag.body.style.setProperty("--c", color);
  tag.position.set(-0.35, 3.75, -0.5);
  group.add(tag);

  for (const mesh of [torso, head, screen, rug]) {
    mesh.userData = { kind: "agent", id };
    pickables.push(mesh);
  }
  scene.add(group);
  return { id, group, screen, shade, lamp, person, head, torso, arms, tag, rug, state: "idle", task: null, sig: "" };
}

function drawScreen(view, agent) {
  const state = agent.state;
  const tex = canvasTexture(512, 296, (ctx, w, h) => {
    const bg = state === "running" ? "#16324a" : state === "error" ? "#fde2e2" : "#eef2f7";
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = AGENT_COLORS[view.id];
    ctx.fillRect(0, 0, w, 16);
    if (state === "running") {
      // 代码行
      const palette = ["#7dd3fc", "#86efac", "#fcd34d", "#c4b5fd", "#f9a8d4"];
      for (let i = 0; i < 9; i++) {
        ctx.fillStyle = palette[i % palette.length];
        ctx.globalAlpha = 0.75;
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

export function updateDesk(view, agent) {
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
}

export function tickDesk(view, t, selectedId) {
  const running = view.state === "running";
  const error = view.state === "error";
  const phase = view.id.length;
  // 运行中打字，空闲时慢慢呼吸
  view.arms.forEach((pivot, i) => {
    pivot.rotation.x = running ? -1.05 + Math.sin(t * 16 + i * Math.PI) * 0.09 : -1.0 + Math.sin(t * 0.8 + phase) * 0.02;
  });
  view.torso.scale.y = 1 + Math.sin(t * 1.6 + phase) * (running ? 0.01 : 0.025);
  view.head.position.y = 2.55 + (running ? Math.sin(t * 8) * 0.025 : Math.sin(t * 1.6 + phase) * 0.02);
  view.head.rotation.y = running ? Math.sin(t * 0.9) * 0.15 : Math.sin(t * 0.4 + phase) * 0.3;
  view.lamp.intensity = running ? 3.5 : 0;
  view.shade.material.emissiveIntensity = running ? 0.9 : 0;
  const flicker = running ? 0.92 + Math.sin(t * 25) * 0.04 : error ? (Math.sin(t * 8) > 0 ? 1 : 0.55) : 1;
  view.screen.material.color.setScalar(flicker);
  const selected = selectedId === view.id;
  view.rug.material.emissive?.set(selected ? AGENT_COLORS[view.id] : "#000000");
  if (view.rug.material.emissive) view.rug.material.emissiveIntensity = selected ? 0.25 : 0;
  view.tag.body.classList.toggle("selected", selected);
}
