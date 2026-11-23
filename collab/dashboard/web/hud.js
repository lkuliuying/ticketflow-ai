import {
  AGENT_COLORS,
  STAGE_COLORS,
  STAGE_HINT,
  STATE_LABEL,
  esc,
  relTime,
  shortTime
} from "./theme.js";

const $ = id => document.getElementById(id);
const KIND_ICON = { commit: "◆", dispatch: "▶", finish: "■", report: "✎", review: "◎" };

function chip(state) {
  return `<span class="chip ${state}">${STATE_LABEL[state] ?? esc(state)}</span>`;
}

function stageChip(stage) {
  return `<span class="stage-chip" style="--c:${STAGE_COLORS[stage]}">${esc(stage)}</span>`;
}

function verdictChip(verdict) {
  if (!verdict) return "";
  const ok = verdict === "APPROVE";
  return `<span class="verdict ${ok ? "ok" : "bad"}">${ok ? "APPROVE" : "REQUEST_CHANGES"}</span>`;
}

function stageTrack(stages, current) {
  const idx = stages.indexOf(current);
  return `<div class="track">${stages
    .map((s, i) => `<i class="${i < idx ? "past" : i === idx ? "now" : ""}" style="--c:${STAGE_COLORS[s]}" title="${s}"></i>`)
    .join("")}</div>`;
}

// ---------------------------------------------------------------- 顶栏

export function renderTop(data, ok) {
  const counts = {};
  for (const t of data.tasks) counts[t.stage] = (counts[t.stage] ?? 0) + 1;
  $("stage-pills").innerHTML = data.stages
    .filter(s => counts[s])
    .map(s => `<span class="pill" style="--c:${STAGE_COLORS[s]}">${s}<b>${counts[s]}</b></span>`)
    .join("");
  const running = Object.values(data.agents).filter(a => a.state === "running").length;
  $("live-dot").className = `live-dot ${ok ? "ok" : "bad"}`;
  $("live-text").textContent = ok
    ? `${running} 个代理运行中 · 更新于 ${shortTime(data.now)}`
    : "状态服务不可达，显示最后一次数据";
  $("legend").innerHTML = data.stages
    .map(s => `<span title="${esc(STAGE_HINT[s])}"><i style="background:${STAGE_COLORS[s]}"></i>${s}</span>`)
    .join("");
}

// ---------------------------------------------------------------- 左侧代理卡片

function claudeExtra(a) {
  return `
    <dl>
      <dt>检出分支</dt><dd><code>${esc(a.checkout)}</code></dd>
      <dt>状态更新</dt><dd>${relTime(a.updated)}</dd>
    </dl>
    ${a.notes?.length ? `<ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}`;
}

function codexExtra(a) {
  const log = a.log ?? {};
  const h = log.header ?? {};
  const cmds = (log.commands ?? []).slice(-6).reverse();
  return `
    <dl>
      <dt>工作目录</dt><dd><code>${esc(h.workdir ?? "—")}</code></dd>
      <dt>推理强度</dt><dd>${esc(h.reasoning_effort ?? "—")}</dd>
      <dt>命令</dt><dd>${log.command_total ?? 0} 条 · <span class="bad-text">${log.command_failed ?? 0} 失败</span></dd>
      <dt>改动文件</dt><dd>${log.patched?.length ?? 0} 个</dd>
      <dt>日志</dt><dd>${relTime(log.updated)}${log.size ? ` · ${(log.size / 1024).toFixed(0)} KB` : ""}</dd>
    </dl>
    <div class="cmds">${cmds
      .map(
        c => `<div class="cmd ${c.status}" title="${esc(c.output?.join("\n") ?? "")}">
          <span class="dot"></span><code>${esc(c.cmd.slice(0, 120))}</code>
          <em>${c.ms != null ? (c.ms > 1000 ? `${(c.ms / 1000).toFixed(1)}s` : `${c.ms}ms`) : c.status === "running" ? "运行中" : ""}</em>
        </div>`
      )
      .join("")}</div>`;
}

function geminiExtra(a) {
  const r = a.last_round;
  const blockers = r ? r.issues.filter(i => i.level === "阻断").length : 0;
  return `
    <dl>
      <dt>已评审任务</dt><dd>${a.reviewed} 个 · 共 ${a.total_rounds} 轮</dd>
      <dt>最近结论</dt><dd>${r ? `${verdictChip(r.verdict)} 阻断 ${blockers}` : "—"}</dd>
      <dt>最近时间</dt><dd>${esc(r?.time ?? "—")}</dd>
      <dt>权限</dt><dd>plan 模式 · 无文件/终端权限</dd>
    </dl>`;
}

export function renderAgents(data, selected, onSelect) {
  const el = $("agents");
  el.innerHTML = Object.values(data.agents)
    .map(
      a => `
      <section class="agent-card ${a.state} ${selected?.kind === "agent" && selected.id === a.id ? "selected" : ""}"
               data-agent="${a.id}" style="--c:${AGENT_COLORS[a.id]}">
        <header>
          <span class="avatar"></span>
          <div>
            <h2>${esc(a.name)} ${chip(a.state)}</h2>
            <p>${esc(a.role)} · <code>${esc(a.model)}</code> · ${esc(a.tool)}</p>
          </div>
        </header>
        <div class="now-task">${a.task ? `任务 <b>${esc(a.task)}</b>` : "暂无任务"}</div>
        <p class="activity">${esc(a.activity || "—")}</p>
        ${a.id === "claude" ? claudeExtra(a) : a.id === "codex" ? codexExtra(a) : geminiExtra(a)}
      </section>`
    )
    .join("");
  el.querySelectorAll("[data-agent]").forEach(node =>
    node.addEventListener("click", () => onSelect({ kind: "agent", id: node.dataset.agent }))
  );
}

// ---------------------------------------------------------------- 右侧：流水线

export function renderPipeline(data, selected, onSelect) {
  const el = $("tab-pipeline");
  el.innerHTML = `
    <div class="flow-steps">
      ${["Claude 写任务书", "执行者实现自测", "写完成报告", "Gemini 评审", "用户确认合并"]
        .map((s, i) => `<span><b>${i + 1}</b>${s}</span>`)
        .join("<i>→</i>")}
    </div>
    ${data.tasks
      .map(
        t => `
      <article class="task-row ${selected?.kind === "task" && selected.id === t.id ? "selected" : ""}" data-task="${t.id}"
               style="--c:${STAGE_COLORS[t.stage]}; --a:${AGENT_COLORS[t.agent]}">
        <div class="task-head">
          <code class="task-id">${t.id}</code>
          <span class="task-title">${esc(t.title)}</span>
          ${stageChip(t.stage)}
        </div>
        ${stageTrack(data.stages, t.stage)}
        <div class="task-meta">
          <span class="who"><i></i>${esc(t.executor)}</span>
          ${t.branch ? `<code>${esc(t.branch)}</code>` : ""}
          ${t.branch_info ? `<span>+${t.branch_info.ahead} / −${t.branch_info.behind}</span>` : ""}
          ${t.depends.length ? `<span class="deps">依赖 ${t.depends.map(esc).join("、")}</span>` : ""}
          ${t.review?.rounds?.length ? `<span>评审 ${t.review.rounds.length} 轮</span>` : ""}
        </div>
      </article>`
      )
      .join("")}`;
  el.querySelectorAll("[data-task]").forEach(node =>
    node.addEventListener("click", () => onSelect({ kind: "task", id: node.dataset.task }))
  );
}

// ---------------------------------------------------------------- 右侧：详情

function taskDetail(t, data) {
  const runs = [...(t.runs ?? [])].reverse();
  const rounds = t.review?.rounds ?? [];
  const log = t.log ?? {};
  return `
    <div class="detail-head" style="--c:${STAGE_COLORS[t.stage]}">
      <code>${t.id}</code><h3>${esc(t.title)}</h3>${stageChip(t.stage)}
    </div>
    <p class="hint">${esc(STAGE_HINT[t.stage])}</p>
    ${stageTrack(data.stages, t.stage)}
    <dl class="grid">
      <dt>执行者</dt><dd style="color:${AGENT_COLORS[t.agent]}">${esc(t.executor)}</dd>
      <dt>分支</dt><dd><code>${esc(t.branch ?? "—")}</code></dd>
      ${t.branch_info ? `<dt>相对 main</dt><dd>领先 ${t.branch_info.ahead} · 落后 ${t.branch_info.behind}</dd>
      <dt>最新提交</dt><dd><code>${esc(t.branch_info.sha)}</code> ${esc(t.branch_info.subject)}</dd>` : ""}
      <dt>依赖</dt><dd>${t.depends.length ? t.depends.map(d => {
        const dep = data.tasks.find(x => x.id === d);
        return `${esc(d)} ${dep ? stageChip(dep.stage) : ""}`;
      }).join(" ") : "无"}</dd>
      <dt>看板状态</dt><dd>${esc(t.board_status)}</dd>
    </dl>
    ${t.points?.length ? `<h4>任务书要点</h4><ul class="points">${t.points.map(p => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
    <h4>完成报告</h4>
    ${t.report ? `<p>更新于 ${relTime(t.report.updated)}${t.report.commit ? ` · 提交 <code>${esc(t.report.commit)}</code>` : ""}</p>
      ${t.report.unverified?.length ? `<div class="warn-box"><b>未完成或未验证</b><ul>${t.report.unverified.map(u => `<li>${esc(u)}</li>`).join("")}</ul></div>` : ""}`
      : `<p class="muted">尚未提交</p>`}
    <h4>评审记录</h4>
    ${rounds.length ? rounds.map(r => `
      <div class="round">
        <div class="round-head">第 ${r.round} 轮 ${verdictChip(r.verdict)} <span class="muted">${esc(r.time ?? "")} · ${esc(r.model ?? "")}</span></div>
        ${r.issues.length ? `<table>${r.issues.map(i => `<tr><td class="lv ${i.level}">${esc(i.level)}</td><td><code>${esc(i.where)}</code><br>${esc(i.what)}</td></tr>`).join("")}</table>` : `<p class="muted">无阻断或一般问题</p>`}
        ${r.suggestions.length ? `<details><summary>${r.suggestions.length} 条建议</summary><ul>${r.suggestions.map(s => `<li>${esc(s)}</li>`).join("")}</ul></details>` : ""}
      </div>`).join("") : `<p class="muted">尚未评审</p>`}
    <h4>调度记录</h4>
    ${runs.length ? `<ul class="runs">${runs.map(r => `<li style="--a:${AGENT_COLORS[r.agent]}"><i></i>${esc(r.kind === "task" ? "执行" : "评审")} · ${esc(r.detail ?? "")}<span>${shortTime(r.started)} → ${r.ended ? shortTime(r.ended) : r.status === "running" ? "运行中" : "—"} · ${esc(r.status)}</span></li>`).join("")}</ul>` : `<p class="muted">无</p>`}
    ${log.commands?.length ? `<h4>Codex 命令（最近 ${log.commands.length} / 共 ${log.command_total}）</h4>
      <div class="cmds tall">${[...log.commands].reverse().map(c => `<div class="cmd ${c.status}"><span class="dot"></span><code>${esc(c.cmd)}</code><em>${c.ms != null ? `${c.ms}ms` : ""}</em>${c.output?.length ? `<pre>${esc(c.output.join("\n"))}</pre>` : ""}</div>`).join("")}</div>` : ""}
    ${log.patched?.length ? `<h4>改动文件（${log.patched.length}）</h4><ul class="files">${log.patched.map(f => `<li><code>${esc(f)}</code></li>`).join("")}</ul>` : ""}
    ${log.messages?.length ? `<h4>Codex 进展播报</h4><ol class="messages">${log.messages.map(m => `<li>${esc(m)}</li>`).join("")}</ol>` : ""}`;
}

function agentDetail(a, data) {
  const tasks = data.tasks.filter(t => t.agent === a.id);
  return `
    <div class="detail-head" style="--c:${AGENT_COLORS[a.id]}">
      <h3>${esc(a.name)}</h3>${chip(a.state)}
    </div>
    <p class="hint">${esc(a.role)} · ${esc(a.tool)} · <code>${esc(a.model)}</code></p>
    <p class="activity big">${esc(a.activity || "—")}</p>
    <h4>负责的任务</h4>
    ${tasks.length ? tasks.map(t => `<div class="mini-task">${stageChip(t.stage)} <code>${t.id}</code> ${esc(t.title)}</div>`).join("") : `<p class="muted">无</p>`}
    ${a.id === "codex" && a.log?.messages?.length ? `<h4>进展播报</h4><ol class="messages">${a.log.messages.map(m => `<li>${esc(m)}</li>`).join("")}</ol>` : ""}
    ${a.id === "codex" && a.log?.errors?.length ? `<h4>错误</h4><pre class="err">${esc(a.log.errors.join("\n"))}</pre>` : ""}
    ${a.id === "gemini" && a.last_round ? `<h4>最近一轮评审</h4><p>${verdictChip(a.last_round.verdict)} ${esc(a.task ?? "")} 第 ${a.last_round.round} 轮</p>` : ""}
    ${a.id === "claude" && a.notes?.length ? `<h4>备注</h4><ul class="notes">${a.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}`;
}

function stageDetail(stage, data) {
  const tasks = data.tasks.filter(t => t.stage === stage);
  return `
    <div class="detail-head" style="--c:${STAGE_COLORS[stage]}"><h3>${esc(stage)}</h3></div>
    <p class="hint">${esc(STAGE_HINT[stage])}</p>
    ${tasks.length ? tasks.map(t => `<div class="mini-task"><code>${t.id}</code> ${esc(t.title)} · ${esc(t.executor)}</div>`).join("") : `<p class="muted">当前没有任务处于该阶段</p>`}`;
}

export function renderDetail(data, selected) {
  const el = $("tab-detail");
  if (!selected) {
    el.innerHTML = `<p class="muted pad">点击仓库进入内部查看货架和流水线；点击 main 归档库或分支堆场的集装箱查看分支；也可以在左右面板中点击条目查看详情。</p>`;
    return;
  }
  if (selected.kind === "task") {
    const t = data.tasks.find(x => x.id === selected.id);
    el.innerHTML = t ? taskDetail(t, data) : "";
  } else if (selected.kind === "agent") {
    el.innerHTML = agentDetail(data.agents[selected.id], data);
  } else if (selected.kind === "stage") {
    el.innerHTML = stageDetail(selected.id, data);
  } else if (selected.kind === "trunk") {
    el.innerHTML = gitHtml(data.git);
  } else if (selected.kind === "branch") {
    el.innerHTML = branchDetail(selected.id, data);
  }
}

function branchDetail(name, data) {
  const b = data.git.branches.find(x => x.name === name);
  if (!b) return `<p class="muted pad">分支 ${esc(name)} 已不存在</p>`;
  const tasks = data.tasks.filter(t => t.branch === name);
  const worktree = data.git.worktrees.find(w => w.branch === name);
  const commits = data.git.commits.filter(c => c.refs.split(", ").some(r => r.replace("HEAD -> ", "") === name));
  return `
    <div class="detail-head" style="--c:${b.ahead ? "#3b7ddd" : "#9aa3b2"}">
      <h3><code>${esc(b.name)}</code></h3>${b.name === data.git.current ? '<span class="chip running">当前检出</span>' : ""}
    </div>
    <p class="hint">${b.ahead ? "领先 main，尚未合入" : "已全部合入 main"}</p>
    <dl class="grid">
      <dt>相对 main</dt><dd>领先 ${b.ahead} · 落后 ${b.behind}</dd>
      <dt>最新提交</dt><dd><code>${esc(b.sha)}</code> ${esc(b.subject)}</dd>
      <dt>提交时间</dt><dd>${relTime(b.date)}</dd>
      <dt>工作目录</dt><dd>${worktree ? `<code>${esc(worktree.worktree)}</code>${worktree.dirty ? ` · <b class="bad-text">${worktree.dirty} 个未提交改动</b>` : ""}` : "未检出"}</dd>
    </dl>
    <h4>关联任务</h4>
    ${tasks.length ? tasks.map(t => `<div class="mini-task">${stageChip(t.stage)} <code>${t.id}</code> ${esc(t.title)}</div>`).join("") : '<p class="muted">无</p>'}
    ${commits.length ? `<h4>分支头提交</h4><ul class="commits">${commits.map(c => `<li style="--a:${AGENT_COLORS[c.author]}"><i></i><code>${esc(c.sha)}</code> ${esc(c.subject)}<em>${relTime(c.date)}</em></li>`).join("")}</ul>` : ""}`;
}

// ---------------------------------------------------------------- 右侧：Git

function gitHtml(git) {
  return `
    <h4>分支（相对 main）</h4>
    <table class="branches">${git.branches
      .map(b => `<tr class="${b.name === git.current ? "current" : ""}"><td><code>${esc(b.name)}</code></td>
        <td class="num">+${b.ahead}</td><td class="num">−${b.behind}</td><td>${esc(b.subject)}</td></tr>`)
      .join("")}</table>
    <h4>工作目录</h4>
    ${git.worktrees
      .map(w => `<div class="worktree"><code>${esc(w.worktree)}</code><span><code>${esc(w.branch ?? w.HEAD?.slice(0, 8))}</code> · ${w.dirty ? `<b class="bad-text">${w.dirty} 个未提交改动</b>` : "干净"}</span>
        ${w.dirty_files?.length ? `<details><summary>未提交文件</summary><ul class="files">${w.dirty_files.map(f => `<li><code>${esc(f)}</code></li>`).join("")}</ul></details>` : ""}</div>`)
      .join("")}
    <h4>最近提交（全部分支）</h4>
    <ul class="commits">${git.commits
      .map(c => `<li style="--a:${AGENT_COLORS[c.author]}"><i></i><code>${esc(c.sha)}</code> ${esc(c.subject)}
        ${c.refs ? `<span class="refs">${esc(c.refs)}</span>` : ""}<em>${relTime(c.date)}</em></li>`)
      .join("")}</ul>`;
}

export function renderGit(data) {
  $("tab-git").innerHTML = gitHtml(data.git);
}

// ---------------------------------------------------------------- 底部事件流

export function renderEvents(data) {
  const last = data.events[0];
  $("latest").innerHTML = last
    ? `<span style="color:${AGENT_COLORS[last.agent] ?? "#999"}">${KIND_ICON[last.kind] ?? "•"}</span> ${esc(last.text)} <span class="muted">· ${relTime(last.time)}</span>`
    : "";
  $("events").innerHTML = data.events
    .map(
      e => `<div class="event ${e.kind}" style="--a:${AGENT_COLORS[e.agent] ?? "#999"}">
        <span class="ico">${KIND_ICON[e.kind] ?? "•"}</span>
        <div><time>${shortTime(e.time)} · ${relTime(e.time)}</time><p>${esc(e.text)}</p></div>
      </div>`
    )
    .join("");
}
