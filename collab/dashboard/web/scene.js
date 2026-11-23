// 代理仓库场景：总览（三座仓库、传送带、main、分支堆场）与仓库内部两种视图，负责渲染、镜头、拾取和切换。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { ownerOf } from "./theme.js";
import { WAREHOUSES, buildGround, buildWarehouse, locationOf, tickWarehouse, updateWarehouse } from "./warehouse.js";
import { buildLanes, buildVault, disposeParcel, laneEnergy, spawnParcel, tickLanes, tickParcels, tickVault, updateVault } from "./belt.js";
import { buildYard, tickYard, updateYard } from "./branches.js";
import { Interior } from "./interior.js";

// 两种视图各自的默认镜头；距离按可见区域自动计算，保证内容放得下
const VIEWS = {
  overview: { direction: new THREE.Vector3(2, 24, 19).normalize(), target: new THREE.Vector3(0, 0.5, 0.6), width: 34, height: 25 },
  interior: { direction: new THREE.Vector3(0, 12, 16).normalize(), target: new THREE.Vector3(0, 1.8, -0.4), width: 27, height: 13 }
};

function lights(scene) {
  scene.add(new THREE.HemisphereLight("#ffffff", "#e3e6ea", 1.7));
  const sun = new THREE.DirectionalLight("#fffaf0", 1.6);
  sun.position.set(12, 26, 16);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -26, right: 26, top: 22, bottom: -22 });
  sun.shadow.bias = -0.0005;
  sun.shadow.radius = 4;
  scene.add(sun);
  const fill = new THREE.DirectionalLight("#e6eeff", 0.45);
  fill.position.set(-18, 12, 10);
  scene.add(fill);
}

export class AgentScene {
  constructor(container, { onSelect, onHover, onMode }) {
    this.container = container;
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.onMode = onMode ?? (() => {});
    this.clock = new THREE.Clock();
    this.pickables = [];
    this.selected = null;
    this.data = null;
    this.mode = "overview";
    this.locations = new Map();
    this.parcels = [];

    this.#setup();
    const overview = (this.overview = new THREE.Scene());
    lights(overview);
    buildGround(overview);
    this.warehouses = Object.fromEntries(Object.keys(WAREHOUSES).map(id => [id, buildWarehouse(overview, id, this.pickables)]));
    this.lanes = buildLanes(overview);
    this.vault = buildVault(overview, this.pickables);
    this.yard = buildYard(overview);

    const inside = (this.inside = new THREE.Scene());
    lights(inside);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(120, 90), new THREE.MeshStandardMaterial({ color: "#eef0f3", roughness: 1 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.01;
    floor.receiveShadow = true;
    inside.add(floor);
    this.interior = new Interior(inside);

    this.#bindPointer();
    window.addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => this.#tick());
  }

  #setup() {
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.5, 300);
    this.userMoved = false;

    const renderer = (this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }));
    renderer.setClearAlpha(0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "label-layer";
    this.container.appendChild(this.labels.domElement);

    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minPolarAngle = 0.3;
    this.controls.maxPolarAngle = 1.2;
    this.controls.minDistance = 10;
    this.controls.autoRotateSpeed = 0.4;
    // 只有真正拖动或缩放过才停止自动适配；单纯点击也会触发 start / end
    let before = null;
    this.controls.addEventListener("start", () => (before = this.camera.position.clone()));
    this.controls.addEventListener("end", () => {
      if (before && before.distanceTo(this.camera.position) > 0.05) this.userMoved = true;
    });
  }

  get activeScene() {
    return this.mode === "interior" ? this.inside : this.overview;
  }

  // ------------------------------------------------------------ 视图切换

  /** 进入某个代理的仓库内部 */
  enter(id) {
    if (!WAREHOUSES[id]) return;
    if (this.mode === "interior" && this.interior.agent === id) return;
    this.#hideLabels(this.overview);
    this.interior.open(id);
    if (this.data) this.interior.update(this.data);
    this.mode = "interior";
    this.#switched();
  }

  /** 回到总览 */
  exit() {
    if (this.mode === "overview") return;
    this.interior.close();
    this.mode = "overview";
    this.#switched();
  }

  #switched() {
    this.userMoved = false;
    this.controls.autoRotate = false;
    this.container.classList.remove("fade-in");
    void this.container.offsetWidth;
    this.container.classList.add("fade-in");
    this.#fit();
    this.onMode(this.mode, this.interior.agent);
  }

  // CSS2DRenderer 只更新当前渲染的场景，切走的场景的标签要手动隐藏
  #hideLabels(scene) {
    scene.traverse(o => {
      if (o.isCSS2DObject) o.element.style.display = "none";
    });
  }

  // ------------------------------------------------------------ 数据更新

  update(data) {
    this.data = data;
    const counts = {};
    for (const t of data.tasks) {
      const loc = locationOf(t, ownerOf(t));
      ((counts[loc] ??= {})[t.stage] = (counts[loc]?.[t.stage] ?? 0) + 1);
      // 任务换了仓库：在总览的传送带上运一个货箱过去
      const prev = this.locations.get(t.id);
      if (prev && prev !== loc) {
        this.parcels = this.parcels.filter(p => {
          if (p.task !== t.id) return true;
          disposeParcel(this.overview, this.lanes, p);
          return false;
        });
        const parcel = spawnParcel(this.overview, this.lanes, prev, loc, t);
        if (parcel) this.parcels.push(parcel);
      }
      this.locations.set(t.id, loc);
    }
    for (const [id, view] of Object.entries(this.warehouses)) {
      if (data.agents[id]) updateWarehouse(view, data.agents[id], counts[id] ?? {});
    }
    for (const lane of this.lanes) lane.energy = laneEnergy(lane, data);
    updateVault(this.overview, this.vault, data.git);
    updateYard(this.yard, data.git, this.pickables);
    this.interior.update(data);
  }

  // ------------------------------------------------------------ 交互

  #bindPointer() {
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const pick = event => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      const list = this.mode === "interior" ? this.interior.pickables : this.pickables;
      return ray.intersectObjects(list, false)[0]?.object.userData;
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

  /** 选中对象：代理进入其仓库；任务进入它所在的仓库；main 与分支回到总览 */
  select(target) {
    this.selected = target;
    if (!target) return;
    if (target.kind === "agent") this.enter(target.id);
    else if (target.kind === "task") {
      const task = this.data?.tasks.find(t => t.id === target.id);
      const loc = task && locationOf(task, ownerOf(task));
      if (loc && loc !== "vault") this.enter(loc);
      else this.exit();
    } else if (target.kind === "trunk" || target.kind === "branch") this.exit();
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
    const view = VIEWS[this.mode];
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const { wFrac = 1, hFrac = 1 } = this.visible ?? {};
    // 宽和高各算一次所需距离，取较大者
    const byWidth = view.width / 2 / (tanV * this.camera.aspect * Math.max(0.35, wFrac));
    const byHeight = view.height / 2 / (tanV * Math.max(0.25, hFrac));
    const distance = Math.min(140, Math.max(byWidth, byHeight));
    this.controls.maxDistance = Math.max(80, distance * 1.3);
    this.camera.position.copy(view.target).addScaledVector(view.direction, distance);
    this.controls.target.copy(view.target);
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
    this.camera.setViewOffset(w, h, (right - left) / 2, h / 2 - (top + bottom) / 2, w, h);
    this.camera.updateProjectionMatrix();
    this.visible = { wFrac: (w - left - right) / w, hFrac: (bottom - top) / h };
    // 可见区域窄时同步缩小场景标签
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
    if (this.mode === "overview") {
      for (const view of Object.values(this.warehouses)) tickWarehouse(view, t, sel);
      tickVault(this.overview, this.vault, dt, sel?.kind === "trunk");
      tickYard(this.yard, sel);
    } else {
      this.interior.tick(t, dt, this.camera, sel);
    }
    // 传送带和货箱在两种视图下都推进，回到总览时状态是连续的
    tickLanes(this.lanes, t, dt);
    this.parcels = tickParcels(this.overview, this.lanes, this.parcels, dt);
    this.controls.update();
    this.renderer.render(this.activeScene, this.camera);
    this.labels.render(this.activeScene, this.camera);
  }
}
