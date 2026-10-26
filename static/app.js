"use strict";
/* CodeWise — رابط اصلی: چت ایجنت، فایل‌ها، پیش‌نمایش، تنظیمات (تیم متخصص‌ها در duo.js) */
const tg = window.Telegram && Telegram.WebApp;
if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
const $ = id => document.getElementById(id);
const ic = (n, c) => `<svg class="ic ${c || ""}"><use href="#i-${n}"/></svg>`;
const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fa = n => String(n).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]);
const LS = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
const haptic = t => { try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(t || "success"); } catch (e) {} };
const MODES = {
  write: ["بساز", "ساخت و ویرایش فایل‌ها، تا کار کامل شه"], debug: ["دیباگ", "ریشه‌ی خطا رو پیدا و اصلاح می‌کنه"], explain: ["توضیح", "کد پروژه رو توضیح می‌ده، فایلی تغییر نمی‌کنه"],
  review: ["بازبینی", "ممیزی باگ/امنیت با اولویت‌بندی P0-P2"], optimize: ["بهینه", "سرعت و خوانایی بدون تغییر رفتار"], idea: ["ایده", "۳ سناریو با امتیازدهی، انتخاب و MVP"], design: ["طراحی", "سیستم طراحی و پیاده‌سازی بصری UI"] };
const VERB = { list: "فهرست", read: "خواندن", grep: "جستجو", write: "نوشتن", edit: "ویرایش", delete: "حذف", run: "اجرا" };
const TICON = { list: "list", read: "file", grep: "search", write: "file", edit: "edit", delete: "trash", run: "play" };
const S = { key: LS.get("cw_key") || "", P: null, projects: [], mode: "write", modes: Object.keys(MODES), busy: false, jid: null, canRun: true, files: [], chat: [], live: null, last: null, tab: "chat", open: new Set(), view: "chat", wide: matchMedia("(min-width:980px)"), uid: 0 };
const hooks = { project: [], view: {} };

/* ---- تم و شبکه ---- */
function setTheme(t) {
  document.documentElement.dataset.theme = t; LS.set("cw_theme", t);
  const c = t === "dark" ? "#0f1217" : "#f6f7f9";
  const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = c;
  try { if (tg && tg.setHeaderColor) { tg.setHeaderColor(c); tg.setBackgroundColor(c); } } catch (e) {}
}
setTheme(LS.get("cw_theme") || (tg && tg.colorScheme) || "dark");
function hdr() { const h = { "Content-Type": "application/json" }; if (tg && tg.initData) h["X-Init-Data"] = tg.initData; else if (S.key) h["X-Admin-Key"] = S.key; return h; }
async function api(path, method = "GET", body) {
  let r;
  try { r = await fetch(path, { method, headers: hdr(), body: body ? JSON.stringify(body) : undefined }); } catch (e) { throw new Error("اتصال به سرور برقرار نیست"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.error || "خطا " + r.status); e.status = r.status; e.data = j; throw e; }
  return j;
}
function toast(t) { const el = $("toast"); el.textContent = t; el.style.display = "block"; clearTimeout(toast.t); toast.t = setTimeout(() => el.style.display = "none", 2600); }
function dlg(title, input, val, ph) {
  return new Promise(res => {
    const i = $("dli"); $("dlt").textContent = title; i.style.display = input ? "" : "none"; i.value = val || ""; i.placeholder = ph || "";
    $("dlg").classList.add("on"); if (input) setTimeout(() => i.focus(), 50);
    const done = v => { $("dlg").classList.remove("on"); $("dlo").onclick = $("dlc").onclick = i.onkeydown = null; res(v); };
    $("dlo").onclick = () => done(input ? i.value.trim() : true); $("dlc").onclick = () => done(input ? "" : false);
    i.onkeydown = e => { if (e.key === "Enter") done(i.value.trim()); };
  });
}
const ask = (t, v, ph) => dlg(t, true, v, ph), yes = t => dlg(t, false);
const sheet = (id, on) => $(id).classList.toggle("on", on);
document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => b.closest(".ov").classList.remove("on"));
document.querySelectorAll(".ov").forEach(o => o.addEventListener("click", e => { if (e.target === o) o.classList.remove("on"); }));
const cpyText = t => { try { navigator.clipboard.writeText(t); toast("کپی شد"); } catch (e) { toast("کپی نشد"); } };

/* ---- مارک‌داون ---- */
const TOOLTAGS = /<(write|edit|replace|insert)\s+path="[^"]*"[^>]*>[\s\S]*?(?:<\/\1>|$)|<(read|delete|revert)\s+path="[^"]*"[^>]*\/>|<ls\s*\/>|<run\s+cmd="[^"]*"\s*\/>|<grep[^>]*>[\s\S]*?(?:<\/grep>|$)|<think>[\s\S]*?(?:<\/think>|$)|<\/?(?:write|edit|replace|insert|grep|think)\b[^>]*$|<done\s*\/>|<agree\s*\/>|<approve\s*\/>|<\/?decision>/g;
const inl = s => esc(s).split(/(`[^`\n]+`)/).map(x => x.length > 2 && x[0] === "`" ? "<code>" + x.slice(1, -1) + "</code>" : x
  .replace(/\*\*([^*\n]+?)\*\*/g, "<b>$1</b>")
  .replace(/(^|[\s(،])\*([^*\s][^*\n]*?)\*(?=$|[\s).,،؛:!؟?])/g, "$1<i>$2</i>")
  .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')).join("");
function md(src) {
  const out = [];
  String(src || "").replace(TOOLTAGS, "").split(/(```[^\n]*\n[\s\S]*?(?:```|$))/).forEach((seg, k) => {
    if (k % 2) { const m = seg.match(/^```([^\n]*)\n([\s\S]*?)(?:```)?$/); if (m) out.push(`<pre><button class="cp">کپی</button><code>${esc(m[2].replace(/\n$/, ""))}</code></pre>`); return; }
    let list = null, tbl = [];
    const endList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const endTbl = () => { if (tbl.length) { const rows = tbl.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r)).map(r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => inl(c.trim())));
      out.push('<div class="tbl"><table>' + rows.map((r, i) => "<tr>" + r.map(c => i ? `<td>${c}</td>` : `<th>${c}</th>`).join("") + "</tr>").join("") + "</table></div>"); tbl = []; } };
    seg.split("\n").forEach(ln => {
      if (/^\s*\|.*\|\s*$/.test(ln)) { endList(); tbl.push(ln); return; } endTbl();
      let m;
      if ((m = ln.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/))) { const t = /\d/.test(m[1]) ? "ol" : "ul"; if (list !== t) { endList(); out.push(`<${t}>`); list = t; } out.push(`<li>${inl(m[2])}</li>`); return; }
      endList();
      if ((m = ln.match(/^(#{1,4})\s+(.*)$/))) out.push(`<h${m[1].length}>${inl(m[2])}</h${m[1].length}>`);
      else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(ln)) out.push("<hr>");
      else if ((m = ln.match(/^>\s?(.*)$/))) out.push(`<blockquote>${inl(m[1])}</blockquote>`);
      else if (ln.trim()) out.push(`<p>${inl(ln)}</p>`);
    });
    endList(); endTbl();
  });
  return out.join("");
}
document.addEventListener("click", e => { const b = e.target.closest(".cp"); if (b) { cpyText(b.nextSibling.textContent); b.textContent = "کپی شد"; setTimeout(() => b.textContent = "کپی", 1200); } });

/* ---- رندر پیام‌ها (متن + گروه ابزارها با diff) ---- */
const DOTS = '<div class="dots"><i></i><i></i><i></i></div>';
function rowHTML(p) {
  const st = (p.add || p.dele) ? `<span class="st"><b>+${p.add || 0}</b> <i>−${p.dele || 0}</i></span>` : "";
  let d = "";
  if (p.d) d = p.d.split("\n").map(l => `<div class="${l[0] === "+" ? "p" : l[0] === "-" ? "m" : "h"}">${esc(l) || " "}</div>`).join("");
  else if (p.o) d = `<div>${esc(p.o)}</div>`;
  const o = S.open.has("r" + p.id);
  return `<div class="rw ${o ? "o" : ""}"><button class="rh" data-r="${p.id}">${ic(TICON[p.n] || "file")}<span class="rv">${VERB[p.n] || esc(p.n)}</span><span class="rp ltr mono">${esc(p.a)}</span>${st}<span class="k ${p.ok ? "ok" : "no"}">${ic(p.ok ? "check" : "x")}</span></button>${d ? `<div class="rd">${d}</div>` : ""}</div>`;
}
function grpHTML(g, live) {
  const files = new Set(g.filter(p => ["write", "edit", "delete"].includes(p.n)).map(p => p.a)).size, key = "g" + g[0].id, o = S.open.has(key) || (live && g === live);
  const title = `${fa(g.length)} اقدام` + (files ? ` · ${fa(files)} فایل تغییر کرد` : "");
  return `<div class="grp ${o ? "o" : ""}"><button class="gh" data-g="${key}">${ic("list")}<span style="flex:1;min-width:0">${title}</span>${ic("chev", "cv")}</button><div class="gb">${g.map(rowHTML).join("")}</div></div>`;
}
function partsHTML(parts, live) {
  let h = "", g = [];
  const fl = last => { if (g.length) { h += grpHTML(g, live && last ? g : null); g = []; } };
  parts.forEach(p => { if (p.k === "tool") g.push(p); else { fl(false); h += md(p.x); } });
  fl(true);
  return h;
}
function footHTML(m) {
  let h = "";
  if (m.changed && m.changed.length) h += m.changed.slice(0, 8).map(f => `<button class="chip ltr mono" data-open="${esc(f)}">${ic("file")}${esc(f)}</button>`).join("") + (m.changed.length > 8 ? `<span class="chip">+${fa(m.changed.length - 8)}</span>` : "") + (m.snap ? `<button class="chip" data-undo="${esc(m.snap)}">${ic("undo")}برگردان</button>` : "");
  return h ? `<div class="foot">${h}</div>` : "";
}
const SUGG = ["یک اپ تودو با ذخیره‌ی محلی و ظاهر مینیمال بساز", "پروژه رو بررسی کن و باگ‌ها و ریسک‌ها رو بگو", "برای توابع اصلی تست بنویس و اجرا کن"];
function drawChat() {
  const box = $("msgs"), n = S.chat.length;
  let h = S.chat.map((m, i) => m.role === "user" ? `<div class="u">${esc(m.content)}</div>` : `<div class="a">${m.parts ? partsHTML(m.parts) : md(m.content)}${i === n - 1 && S.last ? footHTML(S.last) : ""}</div>`).join("");
  if (!n && !S.live) h = `<div class="empty"><h2>چی بسازیم؟</h2>${SUGG.map(s => `<button data-sg="${esc(s)}">${esc(s)}</button>`).join("")}<button data-team="1" style="color:var(--ac);border-color:var(--ac)">${ic("users")} یا یک تیم متخصص برای کار بزرگ‌تر بساز…</button></div>`;
  box.innerHTML = h + '<div id="liveBox"></div>';
  drawLive(); scrollEnd(true);
}
function drawLive() {
  const b = $("liveBox"); if (!b) return;
  if (!S.live) { b.innerHTML = ""; return; }
  b.innerHTML = `<div class="a">${partsHTML(S.live.parts, true)}${DOTS}</div>`;
}
let raf = 0;
function redraw() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; const m = $("msgs"), st = m.scrollHeight - m.scrollTop - m.clientHeight < 90; drawLive(); if (st) scrollEnd(); }); }
function scrollEnd(force) { const m = $("msgs"); m.style.scrollBehavior = force ? "auto" : ""; m.scrollTop = m.scrollHeight; $("jump").hidden = true; }
$("msgs").addEventListener("scroll", () => { const m = $("msgs"); $("jump").hidden = m.scrollHeight - m.scrollTop - m.clientHeight < 240; });
$("jump").onclick = () => scrollEnd();
$("msgs").addEventListener("click", e => {
  const t = e.target.closest("[data-g],[data-r],[data-open],[data-undo],[data-sg],[data-team]"); if (!t) return;
  if (t.dataset.g) toggle(t.dataset.g); else if (t.dataset.r) toggle("r" + t.dataset.r);
  else if (t.dataset.open) openFile(t.dataset.open); else if (t.dataset.undo) undo(t.dataset.undo);
  else if (t.dataset.sg) { $("inp").value = t.dataset.sg; $("inp").focus(); autoH(); } else if (t.dataset.team) goTab("team");
});
function toggle(k) { S.open.has(k) ? S.open.delete(k) : S.open.add(k); drawChat(); }

/* ---- ارسال و دنبال کردن کار ---- */
function setMode(m) { S.mode = m; LS.set("cw_mode", m); const b = $("modeBtn"); b.textContent = (MODES[m] || [m])[0]; b.className = "pill " + m; $("inp").placeholder = m === "explain" || m === "idea" ? "بپرس یا ایده بخواه (فایلی تغییر نمی‌کنه)…" : "بنویس چی ساخته یا درست بشه…"; }
$("modeBtn").onclick = () => {
  $("mlist").innerHTML = S.modes.map(m => `<button class="li ${m === S.mode ? "on" : ""}" data-m="${m}"><span><b>${(MODES[m] || [m])[0]}</b><small>${(MODES[m] || ["", ""])[1]}</small></span>${m === S.mode ? ic("check") : ""}</button>`).join("");
  $("mlist").querySelectorAll("[data-m]").forEach(b => b.onclick = () => { setMode(b.dataset.m); sheet("ovMode", false); });
  sheet("ovMode", true);
};
function setBusy(b) { S.busy = b; $("go").innerHTML = ic(b ? "stop" : "send"); $("go").classList.toggle("stop", b); $("go").setAttribute("aria-label", b ? "توقف" : "ارسال"); }
function autoH() { const t = $("inp"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 150) + "px"; }
$("inp").addEventListener("input", autoH);
$("inp").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && matchMedia("(pointer:fine)").matches) { e.preventDefault(); send(); } });
$("go").onclick = async () => { if (S.busy) { try { await api(`/api/jobs/${S.jid}/stop`, "POST"); } catch (e) {} } else send(); };
async function send(text) {
  text = (text || $("inp").value).trim(); if (!text || S.busy) return;
  try {
    const r = await api(`/api/projects/${S.P}/chat`, "POST", { text, mode: S.mode });
    $("inp").value = ""; autoH(); S.last = null;
    S.chat.push({ role: "user", content: text }); attach(r.job);
  } catch (e) { toast(e.message); if (e.status === 409 && e.data && e.data.job) attach(e.data.job); }
}
let uid = 0;
async function attach(jid) {
  S.jid = jid; setBusy(true); S.live = { parts: [] }; drawChat();
  let n = 0, fin = null;
  while (S.jid === jid) {
    let j;
    try { j = await api(`/api/jobs/${jid}?after=${n}`); } catch (e) { if (e.status === 404) break; await sleep(1500); continue; }
    n = j.n; j.ev.forEach(ev => { if (ev.t === "final") fin = ev; applyEv(ev); });
    if (j.done) break; await sleep(500);
  }
  const parts = S.live ? S.live.parts : [];
  S.live = null; S.jid = null; setBusy(false); haptic();
  try { const p = await api("/api/projects/" + S.P); S.chat = p.chat; S.files = p.files; } catch (e) {}
  const lm = S.chat[S.chat.length - 1];
  if (lm && lm.role === "assistant" && parts.some(p => p.k === "tool")) lm.parts = parts;      // ردپای ابزارها (diff فایل‌ها) روی پیام می‌مونه
  S.last = fin && { changed: fin.changed, snap: fin.snap };
  drawChat(); drawFiles();
  if (fin && fin.changed.length && S.tab === "pv") loadPv();
}
function addTool(p) { const L = S.live; if (!L) return; L.parts.push({ k: "tool", id: ++uid, ...p }); }
function applyEv(ev) {
  const L = S.live; if (!L) return;
  if (ev.t === "turn") L.parts.push({ k: "text", x: "" });
  else if (ev.t === "delta") { const l = L.parts[L.parts.length - 1]; if (l && l.k === "text") l.x += ev.x; else L.parts.push({ k: "text", x: ev.x }); }
  else if (ev.t === "file") addTool({ n: ev.n || "edit", a: ev.path, ok: ev.ok, add: ev.add, dele: ev.dele, d: ev.d });
  else if (ev.t === "tool") addTool({ n: ev.n, a: ev.a, ok: ev.ok });
  else if (ev.t === "result") addTool({ n: "run", a: ev.name.replace(/^run\s+/, ""), ok: !/(Traceback|Error|exit code [1-9])/i.test(ev.x), o: ev.x });
  else if (ev.t === "error") toast(ev.x);
  redraw();
}

/* ---- پروژه‌ها ---- */
async function init() {
  try {
    const me = await api("/api/me");
    S.projects = me.projects; S.canRun = me.run; S.modes = me.modes.filter(m => MODES[m]); $("model").textContent = me.model || "";
    setMode(S.modes.includes(LS.get("cw_mode")) ? LS.get("cw_mode") : "write"); setBusy(false);
    const sv = LS.get("cw_pid");
    await openProject(S.projects.some(p => p.id === sv) ? sv : S.projects[0].id);
  } catch (e) {
    if (e.status === 401 && !(tg && tg.initData)) { const k = await ask("کلید ورود (ADMIN_WEB_KEY)"); if (k) { S.key = k; LS.set("cw_key", k); return init(); } }
    $("msgs").innerHTML = `<div class="empty"><h2>ورود ناموفق</h2><div class="mu">${esc(e.message)}</div></div>`;
  }
}
async function openProject(id) {
  S.P = id; LS.set("cw_pid", id);
  const p = await api("/api/projects/" + id);
  S.files = p.files; S.chat = p.chat; S.live = null; S.last = null; $("rules").value = p.rules || "";
  $("projName").textContent = p.name; const cur = S.projects.find(x => x.id === id); if (cur) cur.name = p.name;
  drawChat(); drawFiles(); sheet("ovProj", false); hooks.project.forEach(f => f());
  if (p.job) attach(p.job); else setBusy(false);
  if (S.tab === "pv") loadPv();
}
function drawProjects() {
  $("plist").innerHTML = S.projects.map(p => `<button class="li ${p.id === S.P ? "on" : ""}" data-p="${esc(p.id)}"><span>${esc(p.name)}</span>${p.id === S.P ? ic("check") : ""}</button>`).join("");
  $("plist").querySelectorAll("[data-p]").forEach(b => b.onclick = () => { if (!S.busy) openProject(b.dataset.p); else toast("اول کار جاری رو متوقف کن"); });
}
$("projBtn").onclick = () => { drawProjects(); sheet("ovProj", true); };
$("pnew").onclick = async () => {
  const name = await ask("نام پروژه"); if (!name) return;
  try { const r = await api("/api/projects", "POST", { name }); S.projects.unshift({ id: r.id, name }); await openProject(r.id); } catch (e) { toast(e.message); }
};
$("setBtn").onclick = () => { sheet("ovSet", true); loadSt(); };
async function loadProviders() {
  const box = $("providerStatus");
  if (!box) return;
  box.innerHTML = '<div class="mu">در حال دریافت وضعیت…</div>';
  try {
    const data = await api("/api/ai/providers");
    const rows = data.providers || [];
    box.innerHTML = rows.length ? rows.map(p => {
      const cooling = Number(p.cooldown_seconds || 0) > 0;
      const state = cooling ? `موقتاً کنار گذاشته شده · ${fa(p.cooldown_seconds)} ثانیه` : (Number(p.failures || 0) > 0 ? "در دسترس برای تلاش بعدی؛ خطای قبلی ثبت شده" : "آماده / هنوز خطایی ثبت نشده");
      const roles = Object.entries(p.role_models || {}).map(([r, m]) => `${r}: ${m}`).join(" · ");
      const err = p.last_error ? `<small>آخرین خطا: ${esc(p.last_error)}</small>` : "";
      return `<div class="li provider-row"><span><b>${esc(p.name)}</b><small>${esc((p.models || []).join(", "))}</small><small>${esc(state)}</small><small>موفق: ${fa(p.successes || 0)} · ناموفق: ${fa(p.failures || 0)} · پاسخ: ${p.latency_ms == null ? "—" : fa(p.latency_ms) + " ms"}</small>${roles ? `<small>مدل‌های نقش: ${esc(roles)}</small>` : ""}${err}</span></div>`;
    }).join("") : '<div class="mu">هیچ سرویس AI پیکربندی نشده است.</div>';
  } catch (e) {
    box.innerHTML = `<div class="mu">دریافت وضعیت ناموفق بود: ${esc(e.message)}</div>`;
  }
}
$("providerRefresh")?.addEventListener("click", loadProviders);

const TASK_RESUMABLE = new Set(["needs_continuation", "verification_failed", "stopped", "failed", "completed", "running"]);
async function loadTasks() {
  const box = $("taskHistory");
  if (!box || !S.P) return;
  box.innerHTML = '<div class="mu">در حال دریافت وظایف…</div>';
  try {
    const data = await api(`/api/projects/${S.P}/tasks`);
    const rows = data.tasks || [];
    box.innerHTML = rows.length ? rows.map(t => {
      const label = `${t.status || "unknown"} · ${t.phase || "—"} · مرحله ${fa(t.current_step || 0)}`;
      const resume = TASK_RESUMABLE.has(t.status) ? `<button class="btn" data-task-resume="${esc(t.id)}">ادامه</button>` : "";
      return `<div class="li task-row"><span><b>${esc((t.goal || "وظیفه").slice(0, 180))}</b><small>${esc(label)}</small><small>${t.updated ? esc(new Date(t.updated).toLocaleString()) : ""} · ${fa(t.files_count || 0)} فایل</small></span><div class="row-actions"><button class="btn" data-task-events="${esc(t.id)}">رویدادها</button>${resume}</div><div class="task-events" id="events-${esc(t.id)}" hidden></div></div>`;
    }).join("") : '<div class="mu">هنوز وظیفه‌ای ثبت نشده است.</div>';
    box.querySelectorAll("[data-task-events]").forEach(b => b.onclick = async () => {
      const id = b.dataset.taskEvents, panel = $("events-" + id);
      if (!panel) return;
      if (!panel.hidden) { panel.hidden = true; return; }
      panel.hidden = false; panel.innerHTML = '<small>در حال بارگذاری رویدادها…</small>';
      try {
        const r = await api(`/api/tasks/${id}/events?limit=30`);
        const evs = r.events || [];
        panel.innerHTML = evs.length ? evs.map(e => `<div class="task-event"><small>#${fa(e.seq)} · ${esc(e.event.type || "event")}</small><div>${esc(e.event.path || e.event.tool || e.event.x || e.event.text || "رویداد ثبت شد")}</div></div>`).join("") : '<small>رویداد مهمی ثبت نشده است.</small>';
      } catch (e) { panel.innerHTML = `<small>${esc(e.message)}</small>`; }
    });
    box.querySelectorAll("[data-task-resume]").forEach(b => b.onclick = async () => {
      if (S.busy) return toast("اول کار جاری رو متوقف کن");
      b.disabled = true;
      try { const r = await api(`/api/tasks/${b.dataset.taskResume}/resume`, "POST", {}); sheet("ovSet", false); attach(r.job); setBusy(true); toast("ادامه‌ی وظیفه شروع شد"); }
      catch (e) { toast(e.message); b.disabled = false; }
    });
  } catch (e) { box.innerHTML = `<div class="mu">بارگذاری تاریخچه ناموفق بود: ${esc(e.message)}</div>`; }
}
$("taskRefresh")?.addEventListener("click", loadTasks);

async function loadSt() {
  loadProviders();
  loadTasks();
  try {
    const s = (await api(`/api/projects/${S.P}/snaps`)).snaps;
    $("snaps").innerHTML = s.length ? s.map(x => `<div class="li"><span>${esc(x.label)}<small>${new Date(x.t).toLocaleString("fa-IR")} · ${fa(x.n)} فایل</small></span><button class="btn" data-sn="${esc(x.id)}">${ic("undo")}بازگردانی</button></div>`).join("") : '<div class="mu">هنوز نسخه‌ای نیست؛ قبل از هر کار ایجنت یکی ساخته می‌شه.</div>';
    $("snaps").querySelectorAll("[data-sn]").forEach(b => b.onclick = () => undo(b.dataset.sn));
  } catch (e) {}
}
async function undo(id) {
  if (S.busy) return toast("اول کار جاری رو متوقف کن");
  if (!await yes("فایل‌ها به قبل از اون اجرا برمی‌گردن (نسخه‌ی فعلی هم پشتیبان می‌شه). ادامه بدم؟")) return;
  try { const r = await api(`/api/projects/${S.P}/restore`, "POST", { id }); S.files = r.files; S.last = null; drawFiles(); drawChat(); sheet("ovSet", false); toast("برگشت "); if (S.tab === "pv") loadPv(); } catch (e) { toast(e.message); }
}
$("rsave").onclick = async () => { try { await api(`/api/projects/${S.P}/rules`, "PUT", { rules: $("rules").value }); toast("ذخیره شد "); } catch (e) { toast(e.message); } };
$("rname").onclick = async () => { const n = await ask("نام جدید", $("projName").textContent); if (!n) return; try { await api("/api/projects/" + S.P, "PATCH", { name: n }); $("projName").textContent = n; S.projects.find(x => x.id === S.P).name = n; } catch (e) { toast(e.message); } };
$("theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
$("tsend").onclick = async () => { try { await api(`/api/projects/${S.P}/sendzip`, "POST"); toast("zip به تلگرام ارسال شد"); } catch (e) { toast(e.message); } };
$("cclr").onclick = async () => { if (S.busy || !await yes("کل گفتگوی این پروژه پاک بشه؟ (فایل‌ها می‌مونن)")) return; await api(`/api/projects/${S.P}/clear`, "POST"); S.chat = []; S.last = null; drawChat(); sheet("ovSet", false); };
$("pdel").onclick = async () => {
  if (S.busy || !await yes("پروژه با همه‌ی فایل‌ها و گفتگوهاش حذف بشه؟")) return;
  try { await api("/api/projects/" + S.P, "DELETE"); } catch (e) { return toast(e.message); }
  S.projects = S.projects.filter(p => p.id !== S.P); sheet("ovSet", false);
  if (!S.projects.length) return init(); openProject(S.projects[0].id);
};

/* ---- فایل‌ها و ادیتور ---- */
function drawFiles(list) {
  if (Array.isArray(list)) S.files = list;
  const q = $("ffilter").value.trim().toLowerCase(), fs = S.files.filter(f => !q || f.path.toLowerCase().includes(q));
  $("flist").innerHTML = fs.length ? fs.map(f => { const i = f.path.lastIndexOf("/"); return `<button class="fr" data-f="${esc(f.path)}">${ic("file")}<span class="n">${i >= 0 ? `<em>${esc(f.path.slice(0, i + 1))}</em>` : ""}${esc(f.path.slice(i + 1))}</span><span class="z">${f.lines ? fa(f.lines) + " خط · " : ""}${f.size > 1024 ? fa((f.size / 1024).toFixed(1)) + " KB" : fa(f.size) + " B"}</span></button>`; }).join("") : `<div class="mu" style="padding:18px 8px">${S.files.length ? "فایلی پیدا نشد" : "هنوز فایلی نیست؛ از ایجنت بخواه بسازه یا آپلود کن."}</div>`;
  $("flist").querySelectorAll("[data-f]").forEach(b => b.onclick = () => openFile(b.dataset.f));
}
$("ffilter").oninput = () => drawFiles();
async function openFile(p, isNew) {
  S.file = p; $("edp").textContent = p; $("edo").hidden = true; $("edr").hidden = !S.canRun || !/\.(py|js)$/.test(p); $("edd").hidden = !!isNew;
  try { $("edt").value = isNew ? "" : (await api(`/api/projects/${S.P}/file?path=` + encodeURIComponent(p))).content; } catch (e) { return toast(e.message); }
  $("ed").classList.add("on");
}
async function saveFile() { try { await api(`/api/projects/${S.P}/file?path=` + encodeURIComponent(S.file), "PUT", { content: $("edt").value }); S.files = (await api("/api/projects/" + S.P)).files; drawFiles(); toast("ذخیره شد "); return true; } catch (e) { toast(e.message); } }
$("eds").onclick = saveFile;
$("edx").onclick = () => $("ed").classList.remove("on");
$("edd").onclick = async () => { if (!await yes("این فایل حذف بشه؟")) return; await api(`/api/projects/${S.P}/file?path=` + encodeURIComponent(S.file), "DELETE"); S.files = S.files.filter(f => f.path !== S.file); drawFiles(); $("ed").classList.remove("on"); };
$("edr").onclick = async () => { if (!await saveFile()) return; const o = $("edo"); o.hidden = false; o.textContent = "در حال اجرا…"; try { o.textContent = (await api(`/api/projects/${S.P}/run`, "POST", { cmd: (/\.js$/.test(S.file) ? "node " : "python ") + S.file })).out; } catch (e) { o.textContent = e.message; } };
$("edt").addEventListener("keydown", e => { if (e.key === "Tab") { e.preventDefault(); const t = e.target; t.setRangeText("  ", t.selectionStart, t.selectionEnd, "end"); } });
$("fnew").onclick = async () => { const p = await ask("مسیر فایل (مثلاً src/main.py)"); if (p) openFile(p, true); };
$("fup").onclick = () => $("fin").click();
$("fin").onchange = async e => {
  const files = [];
  for (const f of e.target.files) { if (f.size > 300000) { toast(f.name + " خیلی بزرگه"); continue; } try { files.push({ path: f.webkitRelativePath || f.name, content: await f.text() }); } catch (x) {} }
  e.target.value = ""; if (!files.length) return;
  try { const r = await api(`/api/projects/${S.P}/import`, "POST", { files }); S.files = (await api("/api/projects/" + S.P)).files; drawFiles(); toast(fa(files.length - r.skipped.length) + " فایل اضافه شد"); } catch (x) { toast(x.message); }
};
$("fzip").onclick = async () => {
  if (tg && tg.initData) return $("tsend").click();
  try { const r = await fetch(`/api/projects/${S.P}/zip`, { headers: hdr() }); if (!r.ok) throw 0; const b = await r.blob(), a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = ($("projName").textContent || "project") + ".zip"; a.click(); } catch (e) { toast("دانلود نشد"); }
};

/* ---- پیش‌نمایش و تب‌ها ---- */
async function loadPv() {
  $("pvm").textContent = "…";
  try { $("pvf").srcdoc = (await api(`/api/projects/${S.P}/preview`)).html; $("pvm").textContent = ""; } catch (e) { $("pvf").srcdoc = ""; $("pvm").textContent = e.message; }
}
$("pvr").onclick = loadPv;
function goTab(v) {
  if (S.wide.matches && v === "chat") v = "files";
  S.tab = S.view = v;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  document.querySelectorAll(".pane").forEach(p => p.classList.toggle("on", p.id === "v-" + v));
  if (v === "pv") loadPv();
  (hooks.view[v] || []).forEach(f => f());
}
const go = goTab;
$("tabs").onclick = e => { const b = e.target.closest("button"); if (b) goTab(b.dataset.v); };
S.wide.addEventListener("change", () => goTab(S.wide.matches ? (S.tab === "chat" ? "files" : S.tab) : S.tab));
if (S.wide.matches) goTab("files");
document.addEventListener("DOMContentLoaded", init);
