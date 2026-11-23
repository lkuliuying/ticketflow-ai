// 代理仓库场景：渲染器、相机、灯光、拾取与动画循环。仓库见 warehouse.js，传送带与归档库见 belt.js。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { AGENT_COLORS, ownerOf } from "./theme.js";
import { WAREHOUSES, buildWarehouse, buildYard, locationOf, slotIn, tickWarehouse, updateWarehouse } from "./warehouse.js";
import {
  buildLanes,
  buildVault,
  createCard,
  disposeCard,
  laneEnergy,
  refreshCard,
  tickLanes,
  tickVault,
  travelPath,
  updateVault,
  vaultSlot
} from "./belt.js";

// 默认视角：斜前方俯视；距离按可见区域自动计算，让三座仓库都放得下
const HOME = { direction: new THREE.Vector3(3, 24, 21).normalize(), target: new THREE.Vector3(0, 0.8, -1.8) };
const FIT_WIDTH = 34;
const FIT_HEIGHT = 19;
const TRAVEL_SPEED = 5;

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

    this.#setup();
    buildYard(this.scene);
    this.warehouses = Object.fromEntries(Object.keys(WAREHOUSES).map(id => [id, buildWarehouse(this.scene, id, this.pickables)]));
    this.lanes = buildLanes(this.scene);
    this.vault = buildVault(this.scene, this.pickables);
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
    sun.shadow.camera.left = -24;
    sun.shadow.camera.right = 24;
    sun.shadow.camera.top = 20;
    sun.shadow.camera.bottom = -20;
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
    const counts = {};
    for (const t of data.tasks) {
      const loc = locationOf(t, ownerOf(t));
      ((counts[loc] ??= {})[t.stage] = (counts[loc]?.[t.stage] ?? 0) + 1);
    }
    for (const [id, view] of Object.entries(this.warehouses)) {
      if (data.agents[id]) updateWarehouse(view, data.agents[id], counts[id] ?? {});
    }
    this.#updateTasks(data);
    for (const lane of this.lanes) lane.energy = laneEnergy(lane, data);
    updateVault(this.scene, this.vault, data.git);
  }

  #updateTasks(data) {
    // 按“所在仓库 + 阶段”分组，组内依次排到货架、工作台或托盘上
    const groups = {};
    for (const t of data.tasks) {
      const loc = locationOf(t, ownerOf(t));
      (groups[loc === "vault" ? "vault" : `${loc}|${t.stage}`] ??= []).push(t);
    }
    const seen = new Set();
    for (const [key, list] of Object.entries(groups)) {
      list.forEach((task, i) => {
        seen.add(task.id);
        const loc = key === "vault" ? "vault" : key.split("|")[0];
        const slot = loc === "vault" ? vaultSlot(i) : slotIn(loc, task.stage, i);
        let card = this.cards.get(task.id);
        if (!card) {
          card = createCard(this.scene, task, slot, this.pickables);
          card.loc = loc;
          this.cards.set(task.id, card);
        }
        if (card.stage !== task.stage || card.task.branch !== task.branch) {
          card.stage = task.stage;
          refreshCard(card, task);
          const zone = this.warehouses[loc]?.zones[task.stage];
          if (zone) zone.pulse = 1;
        }
        card.task = task;
        if (card.loc !== loc) {
          // 换仓库：沿传送带运过去
          const trip = travelPath(this.lanes, card.loc, loc, slot);
          this.#endTrip(card);
          card.path = trip.points;
          card.pathLanes = trip.lanes;
          for (const id of trip.lanes) this.lanes.find(l => l.id === id).transit += 1;
          card.loc = loc;
        } else if (card.path.length) {
          card.path[card.path.length - 1] = slot.clone();
        }
        card.target = slot;
        const agent = data.agents[ownerOf(task)];
        card.active =
          agent?.state === "running" &&
          loc !== "vault" &&
          (agent.task === task.id || (ownerOf(task) === "gemini" && task.stage === "评审中"));
      });
    }
    for (const [id, card] of this.cards) {
      if (!seen.has(id)) {
        this.#endTrip(card);
        disposeCard(this.scene, card, this.pickables);
        this.cards.delete(id);
      }
    }
  }

  #endTrip(card) {
    for (const id of card.pathLanes ?? []) {
      const lane = this.lanes.find(l => l.id === id);
      lane.transit = Math.max(0, lane.transit - 1);
    }
    card.pathLanes = [];
    card.path = [];
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
    // 可见区域窄时同步缩小场景标签，避免标签盖住仓库
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

    for (const view of Object.values(this.warehouses)) tickWarehouse(view, t, dt, sel);
    tickLanes(this.lanes, t, dt);

    for (const card of this.cards.values()) {
      const g = card.group;
      if (card.path.length) {
        // 沿路径点匀速运输：上带 → 各段车道 → 落到目标位置
        let step = TRAVEL_SPEED * dt;
        while (step > 0 && card.path.length) {
          const next = card.path[0];
          const dist = g.position.distanceTo(next);
          if (dist <= step) {
            g.position.copy(next);
            card.path.shift();
            step -= dist;
          } else {
            g.position.addScaledVector(next.clone().sub(g.position).normalize(), step);
            step = 0;
          }
        }
        if (!card.path.length) this.#endTrip(card);
      } else {
        // 同一仓库内换位置：与帧率无关的阻尼
        g.position.lerp(card.target, 1 - Math.exp(-3.6 * dt));
      }
      // 卡片始终朝向镜头（只绕竖轴转）
      g.rotation.y = Math.atan2(this.camera.position.x - g.position.x, this.camera.position.z - g.position.z);
      const isSel = sel?.kind === "task" && sel.id === card.task.id;
      const pulse = 0.5 + 0.5 * Math.sin(t * 4);
      // 卡面已是阶段色：描边只用于选中（深色）和处理中（代理色呼吸）
      card.edge.material.color.set(isSel ? "#1f2937" : AGENT_COLORS[ownerOf(card.task)]);
      card.edge.material.opacity = isSel ? 1 : card.active ? 0.4 + pulse * 0.6 : 0;
      g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x, isSel ? 1.3 : card.active ? 1.08 + pulse * 0.05 : 1, 0.12));
    }

    tickVault(this.scene, this.vault, dt, sel?.kind === "trunk");

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }
}
