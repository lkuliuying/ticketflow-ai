// 仓库内部：点击总览里的仓库后进入。左侧货架放等待中的任务，中间流水线是正在处理的任务，右侧出货区是送出的任务。
import * as THREE from "three";
import { AGENT_COLORS, STAGE_COLORS, STATE_LABEL, esc, ownerOf } from "./theme.js";
import { cardTexture, chevronTexture } from "./belt.js";
import { ROLE_TITLE, box, label, locationOf, mat, tint } from "./warehouse.js";

// 每座仓库内部放哪些阶段：货架（入库等待）、流水线（处理中）、出货区（已送出 / 待合并）
const PLAN = {
  claude: {
    shelves: ["待开始", "阻塞", "需修改"],
    line: "执行中",
    out: { title: "待合并", pick: (t, loc) => loc === "claude" && t.stage === "已通过", faded: false }
  },
  codex: {
    shelves: ["需修改"],
    line: "执行中",
    out: { title: "已送评审", pick: t => t.agent === "codex" && ["待评审", "评审中", "已通过"].includes(t.stage), faded: true }
  },
  gemini: {
    shelves: ["待评审"],
    line: "评审中",
    out: { title: "已放行 / 已退回", pick: t => ["已通过", "需修改"].includes(t.stage), faded: true }
  }
};
const ROOM = { w: 26, d: 14 };
const RACK_W = 4.8;
const LEVELS = [0.85, 2.1, 3.35];
const CARD = { w: 2.0, h: 1.17 };
const LINE = { z: 1.4, top: 0.9, from: -11, to: 5.5, station: -1.5 };
const DOCK = new THREE.Vector3(9.2, 0, 1.6);

export class Interior {
  constructor(scene) {
    this.scene = scene;
    this.group = null;
    this.agent = null;
    this.cards = new Map();
    this.pickables = [];
    this.zones = {};
    this.state = "idle";
  }

  open(id) {
    this.close();
    this.agent = id;
    const color = AGENT_COLORS[id];
    const plan = PLAN[id];
    const group = (this.group = new THREE.Group());

    const floor = box(ROOM.w, 0.1, ROOM.d, mat(tint(color, 0.9)), 0, 0.05, 0);
    floor.castShadow = false;
    group.add(floor);
    // 切开式：只有后墙和左墙
    const wall = mat("#fbfbfc");
    group.add(box(ROOM.w, 4.6, 0.2, wall, 0, 2.3, -ROOM.d / 2));
    group.add(box(0.2, 4.6, ROOM.d, wall, -ROOM.w / 2, 2.3, 0));
    group.add(box(ROOM.w, 0.3, 0.24, mat(color), 0, 4.45, -ROOM.d / 2));
    group.add(box(0.24, 0.3, ROOM.d, mat(color), -ROOM.w / 2, 4.45, 0));
    const title = label(`<b>${esc(id === "claude" ? "Claude" : id === "codex" ? "Codex" : "Gemini")}</b><span>${esc(ROLE_TITLE[id])}</span>`, "label room-title");
    title.body.style.setProperty("--c", color);
    title.position.set(0, 5.4, -ROOM.d / 2);
    group.add(title);

    // 货架
    this.zones = {};
    plan.shelves.forEach((stage, i) => {
      const x = -ROOM.w / 2 + 3.4 + i * (RACK_W + 0.8);
      const boards = this.#rack(group, x, -ROOM.d / 2 + 1.4);
      this.#zone(stage, "货架", new THREE.Vector3(x, 4.5, -ROOM.d / 2 + 1.4), boards);
      this.zones[stage].slot = k => {
        const col = k % 2;
        const level = Math.floor(k / 2) % LEVELS.length;
        const layer = Math.floor(k / (2 * LEVELS.length));
        // 超过 6 张时往前叠一层，并错开半张卡，后排仍露出编号
        return new THREE.Vector3(x + (col - 0.5) * 2.25 + layer * 0.45, LEVELS[level] + 0.66 - layer * 0.12, -ROOM.d / 2 + 1.95 + layer * 0.3);
      };
    });

    // 流水线：传送带 + 工作站
    const length = LINE.to - LINE.from;
    const lineGroup = new THREE.Group();
    lineGroup.position.set((LINE.from + LINE.to) / 2, 0, LINE.z);
    lineGroup.add(box(length, 0.2, 2.0, mat("#c9ced6"), 0, LINE.top - 0.1, 0));
    for (let x = -length / 2 + 0.6; x < length / 2; x += 2.2) lineGroup.add(box(0.16, LINE.top - 0.2, 1.2, mat("#b5bbc5"), x, (LINE.top - 0.2) / 2, 0));
    this.lineTex = chevronTexture("#7b8494", "#c5cbd5");
    this.lineTex.repeat.set(length / 1.4, 1);
    const surface = new THREE.Mesh(new THREE.PlaneGeometry(length, 1.7), new THREE.MeshStandardMaterial({ map: this.lineTex, roughness: 0.8 }));
    surface.rotation.x = -Math.PI / 2;
    surface.position.y = LINE.top + 0.005;
    lineGroup.add(surface);
    group.add(lineGroup);
    const sx = LINE.station;
    // 工作站：细龙门架横跨传送带，横梁上是状态灯，下面挂一个随运行上下动的压头
    for (const dz of [-1.25, 1.25]) group.add(box(0.22, 3.0, 0.22, mat(tint(color, 0.2)), sx, 1.5, LINE.z + dz));
    group.add(box(0.36, 0.3, 2.9, mat(color), sx, 3.0, LINE.z));
    this.lamp = new THREE.Mesh(new THREE.SphereGeometry(0.24, 12, 8), new THREE.MeshStandardMaterial({ color: "#c3c8d0", emissive: "#c3c8d0", emissiveIntensity: 0.2 }));
    this.lamp.position.set(sx, 3.38, LINE.z);
    group.add(this.lamp);
    this.arm = box(0.5, 0.18, 0.7, mat("#6b7280"), sx, 2.4, LINE.z);
    group.add(this.arm, box(0.08, 0.6, 0.08, mat("#9ca3af"), sx, 2.7, LINE.z));
    const lineBoards = [surface];
    this.#zone(plan.line, "流水线", new THREE.Vector3(sx, 4.6, LINE.z), lineBoards);
    this.zones[plan.line].slot = k => new THREE.Vector3(sx - 2.6 - k * 2.4, LINE.top + 0.7, LINE.z);

    // 出货区
    const pallet = box(5.0, 0.2, 3.0, mat("#d8bf9a"), DOCK.x, 0.2, DOCK.z);
    group.add(pallet);
    this.#zone("__out", "出货区", DOCK.clone().setY(0.4).add(new THREE.Vector3(0, 0, 2.0)), [pallet], plan.out.title);
    this.zones.__out.slot = k => {
      const col = k % 2;
      const row = Math.floor(k / 2);
      return DOCK.clone().add(new THREE.Vector3((col - 0.5) * 2.3, 0.95 + row * 0.62, 0.8 - row * 0.75));
    };

    floor.userData = { kind: "agent", id };
    this.pickables.push(floor);
    this.scene.add(group);
  }

  close() {
    if (!this.group) return;
    this.scene.remove(this.group);
    this.group.traverse(o => {
      o.geometry?.dispose();
      for (const m of [o.material].flat()) {
        m?.map?.dispose();
        m?.dispose();
      }
      if (o.isCSS2DObject) o.element.remove();
    });
    this.group = null;
    this.agent = null;
    this.cards.clear();
    this.pickables = [];
    this.zones = {};
  }

  #rack(group, x, z) {
    const upright = mat("#5b8bd0");
    const beam = mat("#f0a24e");
    const boards = [];
    for (const dx of [-RACK_W / 2, RACK_W / 2]) for (const dz of [-0.4, 0.4]) group.add(box(0.1, 4.2, 0.1, upright, x + dx, 2.1, z + dz));
    for (const y of LEVELS) {
      const board = box(RACK_W, 0.08, 0.9, mat("#e3dfd8"), x, y, z);
      group.add(board, box(RACK_W + 0.06, 0.12, 0.08, beam, x, y - 0.06, z + 0.46));
      boards.push(board);
    }
    return boards;
  }

  #zone(stage, kind, at, meshes, title = stage) {
    const color = stage === "__out" ? "#9aa3b2" : STAGE_COLORS[stage];
    const tag = label("", "label zone-label");
    tag.body.style.setProperty("--c", color);
    tag.position.copy(at);
    this.group.add(tag);
    for (const m of meshes) {
      m.userData = stage === "__out" ? { kind: "agent", id: this.agent } : { kind: "stage", id: stage };
      this.pickables.push(m);
    }
    this.zones[stage] = { tag, kind, title, count: 0 };
  }

  /** 把数据里属于这座仓库的任务放到货架、流水线和出货区上 */
  update(data) {
    if (!this.group) return;
    const plan = PLAN[this.agent];
    const agent = data.agents[this.agent];
    this.state = agent?.state ?? "idle";
    const lists = Object.fromEntries(Object.keys(this.zones).map(k => [k, []]));
    for (const t of data.tasks) {
      const loc = locationOf(t, ownerOf(t));
      if (loc === this.agent && lists[t.stage]) lists[t.stage].push(t);
      else if (plan.out.pick(t, loc)) lists.__out.push(t);
    }
    const seen = new Set();
    for (const [zoneKey, list] of Object.entries(lists)) {
      const zone = this.zones[zoneKey];
      zone.count = list.length;
      zone.tag.body.innerHTML = `<span class="zone-kind">${esc(zone.kind)}</span><b>${esc(zone.title)}</b><span class="count">${list.length}</span>`;
      zone.tag.body.classList.toggle("empty", list.length === 0);
      list.forEach((task, k) => {
        seen.add(task.id);
        const faded = zoneKey === "__out" && plan.out.faded;
        const slot = zone.slot(k);
        let card = this.cards.get(task.id);
        const sig = `${task.stage}|${task.title}|${task.agent}|${faded}`;
        if (!card) {
          card = this.#card(task, slot, faded);
          this.cards.set(task.id, card);
        } else if (card.sig !== sig) {
          card.mesh.material[4].map?.dispose();
          card.mesh.material[4].map = cardTexture(task, faded ? "已送出" : "");
          card.mesh.material[4].opacity = faded ? 0.55 : 1;
          card.mesh.material[4].needsUpdate = true;
        }
        card.sig = sig;
        card.task = task;
        card.target = slot;
        card.processing = zoneKey === plan.line;
        card.active = card.processing && agent?.state === "running";
      });
    }
    for (const [id, card] of this.cards) {
      if (seen.has(id)) continue;
      this.group.remove(card.group);
      card.group.traverse(o => {
        o.geometry?.dispose();
        for (const m of [o.material].flat()) {
          m?.map?.dispose();
          m?.dispose();
        }
      });
      const i = this.pickables.indexOf(card.mesh);
      if (i >= 0) this.pickables.splice(i, 1);
      this.cards.delete(id);
    }
    const c = { running: "#2fb383", error: "#e5484d", waiting: "#f0a92e" }[this.state] ?? "#c3c8d0";
    this.lamp.material.color.set(c);
    this.lamp.material.emissive.set(c);
    const lineZone = this.zones[plan.line];
    lineZone.tag.body.insertAdjacentHTML("beforeend", `<span class="chip ${this.state}">${STATE_LABEL[this.state] ?? esc(this.state)}</span>`);
  }

  #card(task, slot, faded) {
    const group = new THREE.Group();
    const side = mat("#f3f4f6");
    const face = new THREE.MeshBasicMaterial({ map: cardTexture(task, faded ? "已送出" : ""), transparent: true, opacity: faded ? 0.55 : 1 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(CARD.w, CARD.h, 0.06), [side, side, side, side, face, side]);
    mesh.castShadow = true;
    group.add(mesh);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: "#1f2937", transparent: true, opacity: 0 }));
    edge.scale.setScalar(1.04);
    group.add(edge);
    mesh.userData = { kind: "task", id: task.id };
    this.pickables.push(mesh);
    group.position.copy(slot);
    this.group.add(group);
    return { group, mesh, edge, task, target: slot.clone(), bob: Math.random() * 6 };
  }

  tick(t, dt, camera, selected) {
    if (!this.group) return;
    const running = this.state === "running";
    this.lineTex.offset.x -= dt * (running ? 0.5 : 0.04);
    this.lamp.material.emissiveIntensity = running ? 0.6 + 0.5 * Math.sin(t * 4) : this.state === "error" ? (Math.sin(t * 8) > 0 ? 1.2 : 0.1) : 0.15;
    this.arm.position.y = 2.4 - (running ? (0.5 + 0.5 * Math.sin(t * 3)) * 0.9 : 0);
    for (const card of this.cards.values()) {
      const g = card.group;
      g.position.lerp(card.target, 1 - Math.exp(-5 * dt));
      if (card.active) g.position.y += Math.sin(t * 6 + card.bob) * 0.01;
      g.rotation.y = Math.atan2(camera.position.x - g.position.x, camera.position.z - g.position.z) * 0.6;
      const isSel = selected?.kind === "task" && selected.id === card.task.id;
      const pulse = 0.5 + 0.5 * Math.sin(t * 4);
      card.edge.material.color.set(isSel ? "#1f2937" : AGENT_COLORS[this.agent]);
      card.edge.material.opacity = isSel ? 1 : card.active ? 0.4 + pulse * 0.6 : 0;
      g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x, isSel ? 1.12 : 1, 1 - Math.exp(-8 * dt)));
    }
    for (const [stage, zone] of Object.entries(this.zones)) {
      zone.tag.body.classList.toggle("selected", selected?.kind === "stage" && selected.id === stage);
    }
  }
}
