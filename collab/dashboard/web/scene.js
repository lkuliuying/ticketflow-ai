// 代理办公室场景：渲染器、相机、灯光、拾取与动画循环。房间与工位见 office.js，传送带与归档柜见 belt.js。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { AGENT_COLORS, STAGE_COLORS, ownerOf } from "./theme.js";
import { DESKS, buildDesk, buildRoom, drawWhiteboard, tickDesk, updateDesk } from "./office.js";
import {
  buildBelt,
  buildCabinet,
  createCard,
  disposeCard,
  linkLine,
  refreshCard,
  slotPosition,
  tickCabinet,
  updateCabinet
} from "./belt.js";

// 默认视角：斜前方俯视；距离按可见区域宽度自动计算，让整间办公室（约 32 个单位宽）放得下
const HOME = { direction: new THREE.Vector3(7, 22, 27).normalize(), target: new THREE.Vector3(1.4, 0.5, 0.8) };
const FIT_WIDTH = 37;
const FIT_HEIGHT = 17;

export class AgentScene {
  constructor(container, { onSelect, onHover }) {
    this.container = container;
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.clock = new THREE.Clock();
    this.pickables = [];
    this.cards = new Map();
    this.selected = null;
    this.data = null;
    this.busy = false;

    this.#setup();
    const room = buildRoom(this.scene);
    this.board = room.board;
    this.desks = Object.fromEntries(Object.keys(DESKS).map(id => [id, buildDesk(this.scene, id, this.pickables)]));
    const belt = buildBelt(this.scene, this.pickables);
    this.gates = belt.gates;
    this.beltTextures = belt.textures;
    this.cabinet = buildCabinet(this.scene, this.pickables);
    this.#bindPointer();
    window.addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => this.#tick());
  }

  #setup() {
    const scene = (this.scene = new THREE.Scene());
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.5, 300);
    this.userMoved = false;

    const renderer = (this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }));
    renderer.setClearAlpha(0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "label-layer";
    this.container.appendChild(this.labels.domElement);

    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.target.copy(HOME.target);
    this.controls.minPolarAngle = 0.35;
    this.controls.maxPolarAngle = 1.15;
    this.controls.minDistance = 16;
    this.controls.maxDistance = 75;
    this.controls.autoRotateSpeed = 0.4;
    // 只有真正拖动或缩放过才停止自动适配；单纯点击也会触发 start / end
    let before = null;
    this.controls.addEventListener("start", () => (before = this.camera.position.clone()));
    this.controls.addEventListener("end", () => {
      if (before && before.distanceTo(this.camera.position) > 0.05) this.userMoved = true;
    });

    scene.add(new THREE.HemisphereLight("#ffffff", "#e6dccd", 1.6));
    const sun = new THREE.DirectionalLight("#fff6e8", 1.9);
    sun.position.set(12, 26, 16);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -22;
    sun.shadow.camera.right = 22;
    sun.shadow.camera.top = 16;
    sun.shadow.camera.bottom = -16;
    sun.shadow.bias = -0.0005;
    sun.shadow.radius = 4;
    scene.add(sun);
    const fill = new THREE.DirectionalLight("#dfe9ff", 0.5);
    fill.position.set(-18, 12, 10);
    scene.add(fill);
  }

  // ------------------------------------------------------------ 数据更新

  update(data) {
    this.data = data;
    for (const [id, view] of Object.entries(this.desks)) if (data.agents[id]) updateDesk(view, data.agents[id]);
    this.#updateTasks(data);
    updateCabinet(this.scene, this.cabinet, data.git);
    drawWhiteboard(this.board, data);
    this.busy =
      Object.values(data.agents).some(a => a.state === "running") ||
      data.tasks.some(t => t.stage === "执行中" || t.stage === "评审中");
  }

  #updateTasks(data) {
    const byStage = {};
    for (const t of data.tasks) (byStage[t.stage] ??= []).push(t);
    for (const [stage, gate] of Object.entries(this.gates)) {
      const count = byStage[stage]?.length ?? 0;
      gate.tag.body.querySelector(".count").textContent = count;
      gate.tag.body.classList.toggle("empty", count === 0);
    }
    const seen = new Set();
    for (const [stage, list] of Object.entries(byStage)) {
      list.forEach((task, i) => {
        seen.add(task.id);
        const slot = slotPosition(stage, i, list.length);
        let card = this.cards.get(task.id);
        if (!card) {
          card = createCard(this.scene, task, slot, this.pickables);
          this.cards.set(task.id, card);
        } else if (card.stage !== task.stage || card.task.branch !== task.branch) {
          if (card.stage !== task.stage && this.gates[task.stage]) this.gates[task.stage].pulse = 1;
          card.stage = task.stage;
          refreshCard(card, task);
        }
        card.task = task;
        card.target = slot;
        this.#updateLink(card, data);
      });
    }
    for (const [id, card] of this.cards) {
      if (!seen.has(id)) {
        disposeCard(this.scene, card, this.pickables);
        this.cards.delete(id);
      }
    }
  }

  // 代理正在处理这张卡片时，画一条到工位的虚线
  #updateLink(card, data) {
    const owner = ownerOf(card.task);
    const agent = data.agents[owner];
    const active =
      agent?.state === "running" &&
      card.task.stage !== "已合并" &&
      (agent.task === card.task.id || (owner === "gemini" && card.task.stage === "评审中"));
    card.active = Boolean(active);
    const key = active ? `${owner}|${card.target.toArray().join(",")}` : "";
    if (card.linkKey === key) return;
    card.linkKey = key;
    if (card.link) {
      this.scene.remove(card.link);
      card.link.geometry.dispose();
      card.link = null;
    }
    if (!active) return;
    const desk = DESKS[owner].clone().setY(2.6).add(new THREE.Vector3(0, 0, 1.3));
    card.link = linkLine(desk, card.target.clone().setY(card.target.y + 0.5), AGENT_COLORS[owner]);
    this.scene.add(card.link);
  }

  // ------------------------------------------------------------ 交互

  #bindPointer() {
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const pick = event => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      return ray.intersectObjects(this.pickables, false)[0]?.object.userData;
    };
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", e => (down = [e.clientX, e.clientY]));
    el.addEventListener("pointerup", e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const target = pick(e);
      if (target) this.onSelect(target);
    });
    el.addEventListener("pointermove", e => {
      const target = pick(e);
      el.style.cursor = target ? "pointer" : "grab";
      this.onHover(target, e);
    });
    el.addEventListener("pointerleave", e => this.onHover(null, e));
  }

  select(target) {
    // 只高亮，不移动镜头：保持整体布局稳定，方便对照左右面板
    this.selected = target;
  }

  setAutoRotate(on) {
    this.controls.autoRotate = on;
  }

  resetView() {
    this.controls.autoRotate = false;
    document.getElementById("rotate-toggle")?.classList.add("off");
    this.userMoved = false;
    this.#fit();
  }

  #fit() {
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const { wFrac = 1, hFrac = 1 } = this.visible ?? {};
    // 宽和高各算一次所需距离，取较大者，保证整间办公室都放得下
    const byWidth = FIT_WIDTH / 2 / (tanV * this.camera.aspect * Math.max(0.35, wFrac));
    const byHeight = FIT_HEIGHT / 2 / (tanV * Math.max(0.25, hFrac));
    const distance = Math.min(130, Math.max(byWidth, byHeight));
    this.controls.maxDistance = Math.max(75, distance * 1.3);
    this.camera.position.copy(HOME.target).addScaledVector(HOME.direction, distance);
    this.controls.target.copy(HOME.target);
    this.controls.update();
  }

  resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.camera.aspect = w / h;
    const rect = sel => document.querySelector(sel)?.getBoundingClientRect();
    const overlap = r => (r ? Math.max(0, Math.min(r.right, w) - Math.max(r.left, 0)) : 0);
    const wide = w > 760;
    // 可见区域：宽屏在左右面板之间、顶栏与事件流之间；窄屏在顶栏与下方面板之间
    const left = wide ? overlap(rect(".panel.left")) : 0;
    const right = wide ? overlap(rect(".panel.right")) : 0;
    const top = rect(".topbar")?.bottom ?? 60;
    const bottom = wide ? (rect(".timeline")?.top ?? h) : Math.min(rect(".panel.right")?.top ?? h, rect(".timeline")?.top ?? h);
    const offsetX = (right - left) / 2;
    const offsetY = h / 2 - (top + bottom) / 2;
    this.camera.setViewOffset(w, h, offsetX, offsetY, w, h);
    this.camera.updateProjectionMatrix();
    this.visible = { wFrac: (w - left - right) / w, hFrac: (bottom - top) / h };
    // 可见区域窄时同步缩小场景标签，避免标签盖住整个办公室
    const zoom = Math.min(1, Math.max(0.62, Math.min((w - left - right) / 1000, (bottom - top) / 520)));
    this.labels.domElement.style.setProperty("--label-zoom", String(zoom));
    if (!this.userMoved) this.#fit();
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
  }

  // ------------------------------------------------------------ 动画

  #tick() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;
    const sel = this.selected;

    for (const view of Object.values(this.desks)) tickDesk(view, t, sel?.kind === "agent" ? sel.id : null);

    // 传送带滚动：有任务在处理时转得快一些
    const speed = this.busy ? 0.35 : 0.06;
    this.beltTextures[0].offset.x -= dt * speed;
    this.beltTextures[1].offset.x += dt * speed;

    for (const card of this.cards.values()) {
      const g = card.group;
      g.position.lerp(card.target, 0.06);
      g.position.y += Math.sin(t * 1.4 + card.bob) * 0.004;
      // 卡片始终朝向镜头（只绕竖轴转）
      g.rotation.y = Math.atan2(this.camera.position.x - g.position.x, this.camera.position.z - g.position.z);
      const isSel = sel?.kind === "task" && sel.id === card.task.id;
      const pulse = 0.5 + 0.5 * Math.sin(t * 4);
      card.edge.material.color.set(isSel ? "#1f2937" : card.active ? AGENT_COLORS[ownerOf(card.task)] : STAGE_COLORS[card.task.stage]);
      card.edge.material.opacity = isSel ? 1 : card.active ? 0.5 + pulse * 0.5 : 0.6;
      g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x, isSel ? 1.25 : card.active ? 1.06 + pulse * 0.04 : 1, 0.12));
      if (card.link) card.link.material.opacity = 0.45 + pulse * 0.45;
    }

    for (const [stage, gate] of Object.entries(this.gates)) {
      gate.pulse = Math.max(0, gate.pulse - dt * 0.7);
      const isSel = sel?.kind === "stage" && sel.id === stage;
      if (gate.strip.material.emissiveIntensity !== undefined) {
        gate.strip.material.emissiveIntensity = 0.1 + gate.pulse * 0.9 + (isSel ? 0.35 : 0);
      }
      gate.tag.body.classList.toggle("selected", isSel);
    }

    tickCabinet(this.scene, this.cabinet, dt, t, sel?.kind === "trunk");

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }
}
