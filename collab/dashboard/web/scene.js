import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  CSS2DRenderer,
  CSS2DObject
} from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { AGENT_COLORS, STAGE_COLORS, STATE_LABEL, esc, ownerOf } from "./theme.js";

const RING_RADIUS = 8.5;
const AGENT_RADIUS = 14;
// 阶段沿逆时针排布：Claude 在正后方下发任务，Codex 在左前方执行，Gemini 在右前方评审，
// 评审结论再回到 Claude 合并，环形流水线与交接方向一致
const STAGE_START = 118;
const STAGE_STEP = 37;
const AGENT_ANGLE = { claude: 90, codex: 218, gemini: 322 };
const HANDOFFS = [
  { from: "claude", to: "codex", label: "任务书" },
  { from: "codex", to: "gemini", label: "完成报告" },
  { from: "gemini", to: "claude", label: "评审结论" },
  { from: "gemini", to: "codex", label: "退回修改" }
];

const polar = (deg, r, y = 0) => {
  const a = THREE.MathUtils.degToRad(deg);
  return new THREE.Vector3(r * Math.cos(a), y, -r * Math.sin(a));
};

function label(html, className) {
  const el = document.createElement("div");
  el.className = className;
  el.innerHTML = html;
  return new CSS2DObject(el);
}

function cardTexture(task, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 300;
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 512, 300);
  grad.addColorStop(0, "#111a2b");
  grad.addColorStop(1, "#0a101c");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 300);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 512, 14);
  ctx.fillRect(0, 0, 14, 300);
  ctx.fillStyle = AGENT_COLORS[task.agent] ?? "#ccc";
  ctx.beginPath();
  ctx.arc(470, 62, 18, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#e8eef9";
  ctx.font = "700 74px 'JetBrains Mono', monospace";
  ctx.fillText(task.id, 40, 100);
  ctx.font = "500 36px 'Noto Sans SC', sans-serif";
  const title = task.title.length > 13 ? `${task.title.slice(0, 13)}…` : task.title;
  ctx.fillText(title, 40, 170);
  ctx.fillStyle = color;
  ctx.font = "700 34px 'Noto Sans SC', sans-serif";
  ctx.fillText(task.stage, 40, 250);
  ctx.fillStyle = "#7f8ba3";
  ctx.font = "400 28px 'JetBrains Mono', monospace";
  ctx.fillText(task.branch ?? "—", 200, 250);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

export class AgentScene {
  constructor(container, { onSelect, onHover }) {
    this.container = container;
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.clock = new THREE.Clock();
    this.agents = {};
    this.cards = new Map();
    this.gates = {};
    this.beams = [];
    this.handoffs = [];
    this.bursts = [];
    this.trunkRings = [];
    this.knownCommits = null;
    this.pickables = [];
    this.selected = null;

    this.#setupRenderer();
    this.#buildGround();
    this.#buildTrunk();
    this.#buildRing();
    for (const id of Object.keys(AGENT_ANGLE)) this.#buildAgent(id);
    this.#buildHandoffs();
    this.#bindPointer();
    window.addEventListener("resize", () => this.#resize());
    this.#resize();
    this.renderer.setAnimationLoop(() => this.#tick());
  }

  // ------------------------------------------------------------ 构建

  #setupRenderer() {
    const scene = (this.scene = new THREE.Scene());
    scene.background = new THREE.Color("#05080f");
    scene.fog = new THREE.FogExp2("#05080f", 0.018);

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
    this.camera.position.set(0, 27, 39);

    const renderer = (this.renderer = new THREE.WebGLRenderer({ antialias: true }));
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    this.container.appendChild(renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "label-layer";
    this.container.appendChild(this.labels.domElement);

    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.target.set(0, 2, 0);
    this.controls.maxPolarAngle = Math.PI * 0.47;
    this.controls.minDistance = 12;
    this.controls.maxDistance = 70;
    this.controls.autoRotate = false;
    this.controls.autoRotateSpeed = 0.35;

    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.75, 0.55, 0.18);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    scene.add(new THREE.HemisphereLight("#8fb3ff", "#0b0f18", 0.55));
    const key = new THREE.DirectionalLight("#ffffff", 1.2);
    key.position.set(10, 25, 12);
    scene.add(key);
  }

  #buildGround() {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1024;
    const ctx = canvas.getContext("2d");
    const g = ctx.createRadialGradient(512, 512, 40, 512, 512, 512);
    g.addColorStop(0, "#14213a");
    g.addColorStop(0.55, "#0b1322");
    g.addColorStop(1, "#05080f");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1024, 1024);
    ctx.strokeStyle = "rgba(120,160,230,0.08)";
    for (let r = 40; r < 512; r += 40) {
      ctx.beginPath();
      ctx.arc(512, 512, r, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let a = 0; a < 360; a += 15) {
      const rad = (a * Math.PI) / 180;
      ctx.beginPath();
      ctx.moveTo(512, 512);
      ctx.lineTo(512 + 512 * Math.cos(rad), 512 + 512 * Math.sin(rad));
      ctx.stroke();
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(60, 96),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0.1 })
    );
    ground.rotation.x = -Math.PI / 2;
    this.scene.add(ground);

    // 漂浮的尘埃粒子，增加纵深
    const count = 600;
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 90;
      pos[i * 3 + 1] = Math.random() * 30;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 90;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.dust = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ color: "#5b7bb5", size: 0.08, transparent: true, opacity: 0.6 })
    );
    this.scene.add(this.dust);
  }

  #buildTrunk() {
    const group = (this.trunk = new THREE.Group());
    const core = new THREE.Mesh(
      new THREE.CylinderGeometry(0.55, 0.85, 9, 24, 1, true),
      new THREE.MeshStandardMaterial({
        color: "#9be37b",
        emissive: "#3d7a2a",
        emissiveIntensity: 0.9,
        transparent: true,
        opacity: 0.55,
        side: THREE.DoubleSide
      })
    );
    core.position.y = 4.5;
    group.add(core);
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(2.4, 2.9, 0.5, 48),
      new THREE.MeshStandardMaterial({ color: "#121c2e", metalness: 0.7, roughness: 0.35 })
    );
    base.position.y = 0.25;
    group.add(base);
    const halo = new THREE.Mesh(
      new THREE.TorusGeometry(2.6, 0.05, 8, 96),
      new THREE.MeshBasicMaterial({ color: "#9be37b" })
    );
    halo.rotation.x = Math.PI / 2;
    halo.position.y = 0.55;
    group.add(halo);
    this.trunkLabel = label("", "label trunk-label");
    this.trunkLabel.position.set(0, 0.4, 3.4);
    group.add(this.trunkLabel);
    core.userData = { kind: "trunk" };
    this.pickables.push(core);
    this.scene.add(group);
  }

  #buildRing() {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(RING_RADIUS, 0.07, 10, 240),
      new THREE.MeshBasicMaterial({ color: "#2b3d60" })
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.08;
    this.scene.add(ring);

    // 沿流水线方向流动的光点
    const n = 90;
    this.flowDots = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.07, 8, 8),
      new THREE.MeshBasicMaterial({ color: "#8fb3ff" }),
      n
    );
    this.flowDots.userData.phase = Array.from({ length: n }, (_, i) => i / n);
    this.scene.add(this.flowDots);

    this.stageAngles = {};
    Object.keys(STAGE_COLORS).forEach((stage, i) => {
      const angle = STAGE_START + i * STAGE_STEP;
      this.stageAngles[stage] = angle;
      const color = new THREE.Color(STAGE_COLORS[stage]);
      const gate = new THREE.Group();
      const arch = new THREE.Mesh(
        new THREE.TorusGeometry(1.5, 0.09, 10, 48, Math.PI),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.8 })
      );
      gate.add(arch);
      const pos = polar(angle, RING_RADIUS);
      gate.position.copy(pos);
      gate.lookAt(0, 0, 0);
      gate.rotateY(Math.PI / 2);
      this.scene.add(gate);
      const pad = new THREE.Mesh(
        new THREE.CircleGeometry(1.6, 40),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.12 })
      );
      pad.rotation.x = -Math.PI / 2;
      pad.position.copy(pos).setY(0.1);
      this.scene.add(pad);
      const tag = label(`<b>${stage}</b><span class="count">0</span>`, "label gate-label");
      tag.element.style.setProperty("--c", STAGE_COLORS[stage]);
      tag.position.copy(pos).setY(2.25);
      this.scene.add(tag);
      arch.userData = { kind: "stage", id: stage };
      this.pickables.push(arch);
      this.gates[stage] = { gate, arch, pad, tag, pulse: 0 };
    });
  }

  #buildAgent(id) {
    const color = new THREE.Color(AGENT_COLORS[id]);
    const group = new THREE.Group();
    group.position.copy(polar(AGENT_ANGLE[id], AGENT_RADIUS));

    const platform = new THREE.Mesh(
      new THREE.CylinderGeometry(2.3, 2.8, 0.7, 6),
      new THREE.MeshStandardMaterial({ color: "#111a2b", metalness: 0.8, roughness: 0.3 })
    );
    platform.position.y = 0.35;
    group.add(platform);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(platform.geometry),
      new THREE.LineBasicMaterial({ color })
    );
    edges.position.copy(platform.position);
    group.add(edges);

    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.05, 2),
      new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.6,
        metalness: 0.2,
        roughness: 0.25,
        flatShading: true
      })
    );
    core.position.y = 3;
    group.add(core);
    const shell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.6, 1),
      new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.35 })
    );
    shell.position.y = 3;
    group.add(shell);

    const ringA = new THREE.Mesh(
      new THREE.TorusGeometry(2.1, 0.035, 8, 96),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8 })
    );
    ringA.position.y = 3;
    ringA.rotation.x = Math.PI / 2.3;
    group.add(ringA);
    const ringB = ringA.clone();
    ringB.rotation.set(Math.PI / 1.7, 0.6, 0);
    group.add(ringB);

    // 运行时的轨道粒子与光柱
    const orbitCount = 48;
    const orbit = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.055, 6, 6),
      new THREE.MeshBasicMaterial({ color }),
      orbitCount
    );
    orbit.userData.seeds = Array.from({ length: orbitCount }, () => ({
      r: 2.2 + Math.random() * 0.9,
      speed: 0.6 + Math.random() * 1.4,
      tilt: Math.random() * Math.PI,
      phase: Math.random() * Math.PI * 2,
      y: (Math.random() - 0.5) * 1.6
    }));
    group.add(orbit);
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.35, 1.1, 16, 24, 1, true),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.DoubleSide
      })
    );
    beam.position.y = 11;
    group.add(beam);

    const light = new THREE.PointLight(color, 8, 14, 1.6);
    light.position.y = 3;
    group.add(light);

    const tag = label("", "label agent-label");
    tag.element.style.setProperty("--c", AGENT_COLORS[id]);
    tag.position.set(0, 5.4, 0);
    // 左右两侧的标签向场景内侧展开，避免被侧边面板遮住
    const side = Math.cos(THREE.MathUtils.degToRad(AGENT_ANGLE[id]));
    tag.center.set(side < -0.3 ? 0.12 : side > 0.3 ? 0.88 : 0.5, 1);
    group.add(tag);

    for (const mesh of [platform, core, shell]) {
      mesh.userData = { kind: "agent", id };
      this.pickables.push(mesh);
    }
    this.scene.add(group);
    this.agents[id] = { group, core, shell, ringA, ringB, orbit, beam, light, tag, edges, state: "idle" };
  }

  #arc(from, to, lift) {
    const mid = from.clone().add(to).multiplyScalar(0.5);
    mid.y += lift;
    return new THREE.QuadraticBezierCurve3(from, mid, to);
  }

  #buildHandoffs() {
    for (const h of HANDOFFS) {
      const from = this.agents[h.from].group.position.clone().setY(3);
      const to = this.agents[h.to].group.position.clone().setY(3);
      const curve = this.#arc(from, to, h.label === "退回修改" ? 3.5 : 8);
      const line = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 80, 0.03, 6, false),
        new THREE.MeshBasicMaterial({
          color: AGENT_COLORS[h.from],
          transparent: true,
          opacity: h.label === "退回修改" ? 0.18 : 0.3
        })
      );
      this.scene.add(line);
      const dots = new THREE.InstancedMesh(
        new THREE.SphereGeometry(0.11, 8, 8),
        new THREE.MeshBasicMaterial({ color: AGENT_COLORS[h.from] }),
        5
      );
      this.scene.add(dots);
      const tag = label(esc(h.label), "label handoff-label");
      tag.element.style.setProperty("--c", AGENT_COLORS[h.from]);
      tag.position.copy(curve.getPoint(0.5));
      this.scene.add(tag);
      this.handoffs.push({ ...h, curve, line, dots, tag, energy: 0.2 });
    }
  }

  // ------------------------------------------------------------ 数据更新

  update(data) {
    this.data = data;
    this.#updateAgents(data.agents);
    this.#updateTasks(data.tasks);
    this.#updateTrunk(data.git);
    this.#updateHandoffs(data);
  }

  #updateAgents(agents) {
    for (const [id, view] of Object.entries(this.agents)) {
      const a = agents[id];
      if (!a) continue;
      view.state = a.state;
      const activity = a.activity ? esc(a.activity.slice(0, 90)) + (a.activity.length > 90 ? "…" : "") : "—";
      view.tag.element.innerHTML = `
        <div class="agent-name">${esc(a.name)}<span class="chip ${a.state}">${STATE_LABEL[a.state] ?? a.state}</span></div>
        <div class="agent-role">${esc(a.role)} · <code>${esc(a.model)}</code></div>
        <div class="agent-task">${a.task ? `当前任务 <b>${esc(a.task)}</b>` : "暂无任务"}</div>
        <div class="agent-activity">${activity}</div>`;
    }
  }

  #slotPosition(stage, index, total) {
    const spread = Math.min(STAGE_STEP * 0.7, 9 * (total - 1));
    const angle = this.stageAngles[stage] + (total > 1 ? (spread * index) / (total - 1) - spread / 2 : 0);
    const radius = RING_RADIUS + 2.8 + (index % 2) * 0.7;
    return { angle, radius, y: 1.6 + (index % 2) * 0.5 };
  }

  #updateTasks(tasks) {
    const byStage = {};
    for (const t of tasks) (byStage[t.stage] ??= []).push(t);
    for (const [stage, gate] of Object.entries(this.gates)) {
      const count = byStage[stage]?.length ?? 0;
      gate.tag.element.querySelector(".count").textContent = count;
      gate.tag.element.classList.toggle("empty", count === 0);
      gate.arch.material.emissiveIntensity = count ? 1.4 : 0.45;
      gate.pad.material.opacity = count ? 0.22 : 0.08;
    }
    const seen = new Set();
    for (const [stage, list] of Object.entries(byStage)) {
      list.forEach((task, i) => {
        seen.add(task.id);
        const slot = this.#slotPosition(stage, i, list.length);
        let card = this.cards.get(task.id);
        if (!card) {
          card = this.#createCard(task, slot);
          this.cards.set(task.id, card);
        }
        if (card.stage !== task.stage) {
          if (card.stage) this.gates[task.stage].pulse = 1;
          card.stage = task.stage;
          card.mesh.material[4].map?.dispose();
          card.mesh.material[4].map = cardTexture(task, STAGE_COLORS[task.stage]);
          card.mesh.material[4].needsUpdate = true;
          card.edge.material.color.set(STAGE_COLORS[task.stage]);
        }
        card.task = task;
        card.target = slot;
      });
    }
    for (const [id, card] of this.cards) {
      if (!seen.has(id)) {
        this.scene.remove(card.group);
        this.cards.delete(id);
      }
    }
    this.#rebuildBeams();
  }

  #createCard(task, slot) {
    const group = new THREE.Group();
    const side = new THREE.MeshStandardMaterial({ color: "#16223a", metalness: 0.6, roughness: 0.4 });
    const face = new THREE.MeshBasicMaterial({ map: cardTexture(task, STAGE_COLORS[task.stage]) });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2.6, 1.52, 0.12), [side, side, side, side, face, side]);
    group.add(mesh);
    const edge = new THREE.LineSegments(
      new THREE.EdgesGeometry(mesh.geometry),
      new THREE.LineBasicMaterial({ color: STAGE_COLORS[task.stage] })
    );
    group.add(edge);
    const halo = new THREE.Mesh(
      new THREE.RingGeometry(1.7, 1.85, 48),
      new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0, side: THREE.DoubleSide })
    );
    halo.rotation.x = -Math.PI / 2;
    halo.position.y = -slot.y + 0.12;
    group.add(halo);
    mesh.userData = { kind: "task", id: task.id };
    this.pickables.push(mesh);
    const current = { ...slot };
    group.position.copy(polar(current.angle, current.radius, current.y));
    this.scene.add(group);
    return { group, mesh, edge, halo, stage: task.stage, task, target: slot, current, bob: Math.random() * 6 };
  }

  #rebuildBeams() {
    for (const beam of this.beams) {
      this.scene.remove(beam.line, beam.dots);
      beam.line.geometry.dispose();
    }
    this.beams = [];
    for (const card of this.cards.values()) {
      const owner = ownerOf(card.task);
      const agent = this.agents[owner];
      if (!agent || card.task.stage === "已合并") continue;
      const active = agent.state === "running" && (this.data.agents[owner]?.task === card.task.id || owner === "gemini");
      const from = agent.group.position.clone().setY(3);
      const to = polar(card.target.angle, card.target.radius, card.target.y);
      const curve = this.#arc(from, to, 5);
      const line = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 60, active ? 0.045 : 0.02, 6, false),
        new THREE.MeshBasicMaterial({
          color: AGENT_COLORS[owner],
          transparent: true,
          opacity: active ? 0.75 : 0.18
        })
      );
      const dots = new THREE.InstancedMesh(
        new THREE.SphereGeometry(active ? 0.13 : 0.07, 8, 8),
        new THREE.MeshBasicMaterial({ color: AGENT_COLORS[owner] }),
        active ? 6 : 2
      );
      this.scene.add(line, dots);
      this.beams.push({ curve, line, dots, active, speed: active ? 0.55 : 0.12 });
    }
  }

  #updateTrunk(git) {
    const main = git.branches.find(b => b.name === "main");
    const ahead = git.branches.filter(b => b.name !== "main" && b.ahead > 0);
    this.trunkLabel.element.innerHTML = `
      <div class="trunk-title">main <code>${esc(main?.sha ?? "")}</code></div>
      <div class="trunk-sub">${esc(main?.subject ?? "")}</div>
      <div class="trunk-sub">${ahead.length} 个分支领先 main · 当前检出 <code>${esc(git.current)}</code></div>`;

    const commits = git.commits.slice(0, 14);
    const shas = commits.map(c => c.sha);
    if (this.knownCommits) {
      for (const c of commits) if (!this.knownCommits.has(c.sha)) this.#burst(AGENT_COLORS[c.author] ?? "#fff");
    }
    this.knownCommits = new Set(shas);
    for (const r of this.trunkRings) this.trunk.remove(r);
    this.trunkRings = commits.map((c, i) => {
      const color = new THREE.Color(AGENT_COLORS[c.author] ?? "#c9d3e6");
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(0.95 - i * 0.02, 0.06, 8, 40),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 1 - i * 0.05 })
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 8.6 - i * 0.6;
      ring.userData = { kind: "commit", id: c.sha };
      this.trunk.add(ring);
      return ring;
    });
  }

  #updateHandoffs(data) {
    const stages = new Set(data.tasks.map(t => t.stage));
    for (const h of this.handoffs) {
      let energy = 0.25;
      if (h.from === "claude" && (stages.has("待开始") || stages.has("执行中"))) energy = 0.6;
      if (h.from === "codex" && data.agents.codex.state === "running") energy = 1;
      if (h.from === "gemini" && h.to === "claude" && stages.has("已通过")) energy = 0.8;
      if (h.from === "gemini" && h.to === "codex" && stages.has("需修改")) energy = 1;
      if (h.from === "gemini" && data.agents.gemini.state === "running") energy = 1;
      h.energy = energy;
      h.line.material.opacity = 0.12 + energy * 0.35;
      h.tag.element.classList.toggle("hot", energy >= 0.8);
    }
  }

  #burst(color) {
    const count = 40;
    const mesh = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.08, 6, 6),
      new THREE.MeshBasicMaterial({ color, transparent: true }),
      count
    );
    const vel = Array.from({ length: count }, () =>
      new THREE.Vector3((Math.random() - 0.5) * 4, 3 + Math.random() * 5, (Math.random() - 0.5) * 4)
    );
    this.scene.add(mesh);
    this.bursts.push({ mesh, vel, life: 0 });
  }

  // ------------------------------------------------------------ 交互

  #bindPointer() {
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const pick = event => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      const hit = ray.intersectObjects(this.pickables, false)[0];
      return hit?.object.userData;
    };
    let down = null;
    this.renderer.domElement.addEventListener("pointerdown", e => (down = [e.clientX, e.clientY]));
    this.renderer.domElement.addEventListener("pointerup", e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const target = pick(e);
      if (target) this.onSelect(target);
    });
    this.renderer.domElement.addEventListener("pointermove", e => {
      const target = pick(e);
      this.renderer.domElement.style.cursor = target ? "pointer" : "grab";
      this.onHover(target, e);
    });
  }

  select(target) {
    // 只高亮，不移动镜头：保持整体布局稳定，方便对照左右面板
    this.selected = target;
  }

  setAutoRotate(on) {
    this.controls.autoRotate = on;
  }

  #resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.camera.aspect = w / h;
    // 顶栏矮、底部事件流高：把画面中心上移到两者之间的可见区域
    const left = document.querySelector(".panel.left")?.offsetWidth ?? 0;
    const right = document.querySelector(".panel.right")?.offsetWidth ?? 0;
    this.camera.setViewOffset(w, h, w > 760 ? (right - left) / 2 : 0, w > 760 ? 44 : 0, w, h);
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    this.composer.setSize(w, h);
    this.bloom.setSize(w, h);
  }

  // ------------------------------------------------------------ 动画

  #tick() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3(1, 1, 1);
    const p = new THREE.Vector3();

    for (const [id, a] of Object.entries(this.agents)) {
      const running = a.state === "running";
      const error = a.state === "error";
      const pulse = running ? 0.5 + 0.5 * Math.sin(t * 4) : 0.5 + 0.5 * Math.sin(t * 1.2);
      a.core.material.emissiveIntensity = error ? (Math.sin(t * 10) > 0 ? 1.6 : 0.2) : running ? 1 + pulse * 1.4 : 0.35 + pulse * 0.25;
      a.core.rotation.y += dt * (running ? 1.2 : 0.25);
      a.core.position.y = 3 + Math.sin(t * 1.5 + id.length) * 0.15;
      a.shell.rotation.x -= dt * (running ? 0.8 : 0.15);
      a.shell.rotation.y += dt * (running ? 0.5 : 0.1);
      a.ringA.rotation.z += dt * (running ? 1.4 : 0.3);
      a.ringB.rotation.z -= dt * (running ? 1.1 : 0.2);
      a.light.intensity = running ? 10 + pulse * 10 : 4;
      a.beam.material.opacity = THREE.MathUtils.lerp(a.beam.material.opacity, running ? 0.16 + pulse * 0.08 : 0, 0.05);
      a.orbit.visible = running || this.selected?.id === id;
      if (a.orbit.visible) {
        a.orbit.userData.seeds.forEach((seed, i) => {
          const ang = seed.phase + t * seed.speed;
          p.set(Math.cos(ang) * seed.r, 3 + seed.y + Math.sin(ang + seed.tilt) * 0.6, Math.sin(ang) * seed.r);
          a.orbit.setMatrixAt(i, m.compose(p, q, s));
        });
        a.orbit.instanceMatrix.needsUpdate = true;
      }
      a.tag.element.classList.toggle("selected", this.selected?.kind === "agent" && this.selected.id === id);
    }

    // 卡片沿环形流水线滑动到目标阶段
    for (const card of this.cards.values()) {
      const c = card.current;
      c.angle = THREE.MathUtils.lerp(c.angle, card.target.angle, 0.04);
      c.radius = THREE.MathUtils.lerp(c.radius, card.target.radius, 0.06);
      c.y = THREE.MathUtils.lerp(c.y, card.target.y, 0.06);
      card.group.position.copy(polar(c.angle, c.radius, c.y + Math.sin(t * 1.3 + card.bob) * 0.12));
      card.group.lookAt(this.camera.position.x, card.group.position.y, this.camera.position.z);
      const isSel = this.selected?.kind === "task" && this.selected.id === card.task.id;
      const running = card.task.stage === "执行中" || card.task.stage === "评审中";
      card.halo.material.opacity = isSel ? 0.9 : running ? 0.35 + 0.25 * Math.sin(t * 4) : 0;
      card.halo.material.color.set(isSel ? "#ffffff" : STAGE_COLORS[card.task.stage]);
      card.group.scale.setScalar(THREE.MathUtils.lerp(card.group.scale.x, isSel ? 1.18 : 1, 0.1));
    }

    for (const beam of this.beams) {
      for (let i = 0; i < beam.dots.count; i++) {
        const u = (t * beam.speed + i / beam.dots.count) % 1;
        beam.dots.setMatrixAt(i, m.compose(beam.curve.getPoint(u), q, s));
      }
      beam.dots.instanceMatrix.needsUpdate = true;
    }
    for (const h of this.handoffs) {
      const n = h.dots.count;
      for (let i = 0; i < n; i++) {
        const u = (t * (0.08 + h.energy * 0.25) + i / n) % 1;
        const scale = 0.4 + h.energy;
        h.dots.setMatrixAt(i, m.compose(h.curve.getPoint(u), q, new THREE.Vector3(scale, scale, scale)));
      }
      h.dots.instanceMatrix.needsUpdate = true;
    }

    const phases = this.flowDots.userData.phase;
    for (let i = 0; i < phases.length; i++) {
      const deg = STAGE_START + ((phases[i] + t * 0.02) % 1) * STAGE_STEP * 7.6;
      this.flowDots.setMatrixAt(i, m.compose(polar(deg, RING_RADIUS, 0.12), q, s));
    }
    this.flowDots.instanceMatrix.needsUpdate = true;

    for (const gate of Object.values(this.gates)) {
      if (gate.pulse > 0) {
        gate.pulse = Math.max(0, gate.pulse - dt * 0.6);
        gate.pad.scale.setScalar(1 + (1 - gate.pulse) * 1.8);
        gate.pad.material.opacity = 0.5 * gate.pulse + 0.1;
      } else {
        gate.pad.scale.setScalar(1);
      }
    }

    this.bursts = this.bursts.filter(b => {
      b.life += dt;
      b.vel.forEach((v, i) => {
        v.y -= dt * 4;
        p.set(v.x * b.life, 9 + v.y * b.life, v.z * b.life);
        b.mesh.setMatrixAt(i, m.compose(p, q, s));
      });
      b.mesh.instanceMatrix.needsUpdate = true;
      b.mesh.material.opacity = Math.max(0, 1 - b.life / 2.2);
      if (b.life > 2.2) {
        this.scene.remove(b.mesh);
        return false;
      }
      return true;
    });

    this.trunk.children[0].material.emissiveIntensity = 0.7 + 0.3 * Math.sin(t * 2);
    this.trunkRings.forEach((r, i) => (r.rotation.z = t * (0.3 + i * 0.05)));
    this.dust.rotation.y += dt * 0.01;

    this.controls.update();
    this.composer.render();
    this.labels.render(this.scene, this.camera);
  }
}
