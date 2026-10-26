"use strict";
/* تب «تیم»: متخصص‌های تخصصی (۲ تا ۶ نفر) با بحث، مستندسازی، ساخت، بازبینی و تحویل نهایی */
(() => {
  const ST = { idle: "آماده", running: "در حال کار", paused: "مکث", done: "تحویل شد", stopped: "متوقف", error: "خطا" };
  const KIND = { idea: "ایده", scenarios: "سناریوها", design: "طراحی", question: "سؤال", answer: "پاسخ", critique: "نقد", plan: "طرح", decision: "تصمیم", review: "بازبینی", build: "ساخت", deliver: "تحویل", summary: "خلاصه", reply: "پیام" };
  const PH = [["discuss", "بحث"], ["finalize", "مستندسازی"], ["build", "ساخت و بازبینی"], ["polish", "صیقل"], ["done", "تحویل"]];
  const COLORS = ["#3CCFE3", "#B794F6", "#F6AD55", "#68D391", "#F687B3", "#63B3ED"];
  const SKI = { strategist: "bulb", designer: "brush", architect: "layers", developer: "code", qa: "shield", skeptic: "eye", custom: "spark" };
  const D = { gen: 0, duo: null, ids: new Set(), seq: 0, live: {}, meta: null, form: null, stick: true, raf: 0 };
  const root = () => $("du");
  const pill = s => `<span class="st-pill ${s}">${ST[s] || s}</span>`;
  const ag = id => D.duo.agents.find(a => a.id === id);
  const sk = id => D.meta.skills.find(s => s.id === id) || D.meta.skills[D.meta.skills.length - 1];
  const avatar = (a, i, sm) => `<span class="av ${sm ? "sm" : ""}" style="--c:${a.color || COLORS[i % 6]}">${ic(SKI[a.skill] || "spark")}</span>`;
  const mkAgent = id => { const s = sk(id); return { skill: s.id, name: s.name, role: s.fa, persona: "", model: "", discuss: s.discuss, builds: s.builds, reviews: s.reviews }; };
  const tokens = c => fa(Math.round((c || 0) / 3.6));
  const mode = () => (D.duo && D.duo.mode === "build" ? "تا خروجی نهایی" : "برنامه‌ریزی");
  const closeSheet = () => sheet("ovTeam", false);
  const openSheet = html => { $("tsh").onclick = null; $("tsh").innerHTML = html; sheet("ovTeam", true); };

  hooks.project.push(() => { D.gen++; D.duo = null; if (S.view === "team") list(); });
  hooks.view.team = [() => { if (D.duo) open(D.duo.id); else list(); }];

  async function meta() { if (!D.meta) D.meta = await api("/api/duo/presets"); return D.meta; }

  /* ───── لیست ───── */
  async function list() {
    D.gen++; D.duo = null; root().className = "";
    const el = root(); el.innerHTML = '<div class="tm-in mu">در حال بارگذاری…</div>';
    try {
      const ds = (await api("/api/projects/" + S.P + "/duos")).duos;
      el.innerHTML = `<div class="tm-in"><div style="display:flex;align-items:center;gap:8px"><h2 style="flex:1">تیم متخصص‌ها</h2><button class="btn p" id="dn">${ic("plus")}تیم جدید</button></div>
        <div class="mu" style="font-size:12.8px">هر متخصص یک کانال تخصصی داره: ایده‌پرداز سناریوها رو می‌چینه، طراح هویت بصری می‌سازه، معمار و برنامه‌نویس پیاده می‌کنن، تستر روی فایل‌های واقعی بازبینی می‌کنه و در پایان یک خروجی یکپارچه تحویل می‌گیری.</div>`
        + (ds.length ? ds.map(d => `<button class="tcard" data-id="${d.id}"><div class="tt"><b>${esc(d.title)}</b>${pill(d.status)}</div><div class="gl">${esc(d.goal)}</div><div class="avs">${d.agents.map(a => `<span class="av sm" style="--c:${a.color}" title="${esc(a.name)}">${ic(SKI[a.skill] || "spark")}</span>`).join("")}</div><div class="mt"><span>راند ${fa(d.round)}/${fa(d.max_rounds)}</span><span>${fa(d.decisions)} تصمیم</span><span>${d.mode === "build" ? "تا تحویل نهایی" : "برنامه‌ریزی"}</span></div></button>`).join("") : '<div class="mu" style="padding:6px 2px">هنوز تیمی نساختی.</div>') + "</div>";
      $("dn").onclick = newForm;
      el.querySelectorAll(".tcard").forEach(c => c.onclick = () => open(c.dataset.id));
    } catch (e) { el.innerHTML = '<div class="tm-in mu">' + esc(e.message) + "</div>"; }
  }

  /* ───── ویرایشگر مشترک متخصص‌ها (فرم ساخت + ویرایش) ───── */
  function agentCard(a, i) {
    const s = sk(a.skill), cu = a.skill === "custom";
    return `<div class="agc" style="--c:${COLORS[i % 6]}" data-i="${i}"><div class="ah">${avatar({ skill: a.skill }, i, true)}<b>${esc(s.fa)}</b><span class="fl">${a.builds ? "می‌سازه" : a.reviews ? "بازبینی" : "مشاور"}</span><button class="ib" data-x="${i}" aria-label="حذف" style="width:28px;height:28px">${ic("x")}</button></div>
      <div class="g2"><input type="text" data-f="name" value="${esc(a.name)}" placeholder="نام"><input type="text" data-f="role" value="${esc(a.role)}" placeholder="عنوان"></div>
      <textarea data-f="persona" placeholder="${cu ? "تخصص و رفتار این متخصص رو بنویس (انگلیسی بهتره)…" : "دستور اختصاصی برای این متخصص (اختیاری)"}">${esc(a.persona || "")}</textarea>
      ${cu ? `<div class="flg"><label><input type="checkbox" data-c="discuss" ${a.discuss ? "checked" : ""}> در بحث شرکت کنه</label><label><input type="checkbox" data-c="builds" ${a.builds ? "checked" : ""}> فایل بسازه/ویرایش کنه</label><label><input type="checkbox" data-c="reviews" ${a.reviews ? "checked" : ""}> بازبینی و تأیید کنه</label></div>` : `<div class="sub">${esc(s.short)}</div>`}
      <input type="text" data-f="model" class="ltr" value="${esc(a.model || "")}" placeholder="مدل اختیاری (خالی = پیش‌فرض سرور)"></div>`;
  }
  function agentsEditor(host, list) {
    const max = D.meta.max_agents;
    const paint = lib => {
      host.innerHTML = list.map(agentCard).join("")
        + (list.length < max ? `<button class="btn" data-add="1" style="justify-content:center">${ic("plus")}افزودن متخصص</button>` : "")
        + (lib ? `<div class="lib">${D.meta.skills.map(s => { const used = s.id !== "custom" && list.some(a => a.skill === s.id); return `<button class="lc" data-sk="${s.id}" ${used ? "disabled" : ""}>${avatar({ skill: s.id }, D.meta.skills.indexOf(s), true)}<span><b>${esc(s.fa)}</b><small>${esc(s.short)}</small></span>${used ? ic("check", "ok") : ""}</button>`; }).join("")}</div>` : "");
    };
    host.oninput = e => { const t = e.target, c = t.closest(".agc"); if (!c || !t.dataset.f) return; list[+c.dataset.i][t.dataset.f] = t.value; };
    host.onchange = e => { const t = e.target, c = t.closest(".agc"); if (!c || !t.dataset.c) return; const a = list[+c.dataset.i]; a[t.dataset.c] = t.checked; if (t.dataset.c === "builds" && t.checked) a.reviews = false; if (t.dataset.c === "reviews" && t.checked) a.builds = false; paint(); };
    host.onclick = e => {
      const x = e.target.closest("[data-x]"), ad = e.target.closest("[data-add]"), s = e.target.closest("[data-sk]");
      if (x) { if (list.length <= 2) return toast("حداقل ۲ متخصص لازمه"); list.splice(+x.dataset.x, 1); paint(); }
      else if (ad) paint(true);
      else if (s && !s.disabled) { list.push(mkAgent(s.dataset.sk)); paint(); }
    };
    paint();
  }

  /* ───── فرم ساخت ───── */
  async function newForm() {
    try { await meta(); } catch (e) { return toast(e.message); }
    const t = D.meta.teams[0];
    D.form = { goal: "", team: t.id, agents: t.skills.map(mkAgent), mode: t.mode, max_rounds: 3, build_cycles: 3, manual: false, parallel: true };
    paintForm();
  }
  function paintForm() {
    const f = D.form, team = D.meta.teams.find(p => p.id === f.team);
    root().className = "";
    root().innerHTML = `<div class="ar-top"><button class="ib" id="fb" aria-label="بازگشت">${ic("back")}</button><b>تیم جدید</b></div><div class="tm-in">
      <div class="fld"><label>هدف پروژه (هرچی دقیق‌تر، خروجی بهتر)</label><textarea id="fg" placeholder="مثلاً: یک وب‌اپ مدیریت وظایف فارسی با حالت تاریک/روشن، فیلتر و ذخیره‌ی محلی…">${esc(f.goal)}</textarea></div>
      <div class="fld"><label>تیم آماده (بعدش می‌تونی متخصص اضافه/حذف کنی)</label><div class="chips" id="fp">${D.meta.teams.map(p => `<button data-id="${p.id}" class="${p.id === f.team ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div><div class="mu" style="font-size:12px">${esc(team ? team.hint : "ترکیب سفارشی")}</div></div>
      <div class="fld"><label>حالت کار</label><div class="seg" id="fm"><button data-m="plan" class="${f.mode === "plan" ? "on" : ""}">فقط برنامه‌ریزی (SPEC.md)</button><button data-m="build" class="${f.mode === "build" ? "on" : ""}">تا خروجی نهایی</button></div></div>
      <div class="fld"><label>متخصص‌های تیم (${fa(f.agents.length)}/${fa(D.meta.max_agents)})</label><div id="fa" class="col"></div></div>
      <div class="fld"><label>حداکثر راند بحث: <b id="rv">${fa(f.max_rounds)}</b></label><input type="range" id="fr" min="1" max="10" value="${f.max_rounds}"></div>
      <div class="fld" id="cyw" style="${f.mode === "build" ? "" : "display:none"}"><label>حداکثر دور رفع ایراد: <b id="cv">${fa(f.build_cycles)}</b></label><input type="range" id="fc" min="1" max="6" value="${f.build_cycles}"></div>
      <label class="chk"><input type="checkbox" id="fpar" ${f.parallel ? "checked" : ""}> نظر اولیه‌ی متخصص‌ها هم‌زمان (سریع‌تر و بدون اثر لنگر)</label>
      <label class="chk"><input type="checkbox" id="fman" ${f.manual ? "checked" : ""}> حالت گام‌به‌گام (بعد از هر نوبت مکث می‌کنه)</label>
      <button class="btn p" id="fgo" style="justify-content:center;padding:8px">ساخت و ورود به صحنه</button></div>`;
    $("fb").onclick = list;
    $("fg").oninput = e => f.goal = e.target.value;
    $("fp").onclick = e => { const b = e.target.closest("button"); if (!b) return; const t = D.meta.teams.find(p => p.id === b.dataset.id), g = f.goal; f.team = t.id; f.agents = t.skills.map(mkAgent); f.mode = t.mode; paintForm(); $("fg").value = g; };
    $("fm").onclick = e => { const b = e.target.closest("button"); if (!b) return; f.mode = b.dataset.m; $("fm").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); $("cyw").style.display = f.mode === "build" ? "" : "none"; };
    agentsEditor($("fa"), f.agents);
    $("fr").oninput = e => { f.max_rounds = +e.target.value; $("rv").textContent = fa(f.max_rounds); };
    $("fc").oninput = e => { f.build_cycles = +e.target.value; $("cv").textContent = fa(f.build_cycles); };
    $("fman").onchange = e => f.manual = e.target.checked;
    $("fpar").onchange = e => f.parallel = e.target.checked;
    $("fgo").onclick = async () => {
      if (f.mode === "build" && !f.agents.some(a => a.builds)) return toast("برای ساخت، حداقل یک متخصص سازنده (برنامه‌نویس/طراح) لازمه");
      try { const r = await api("/api/projects/" + S.P + "/duos", "POST", f); await open(r.id); } catch (e) { toast(e.message); }
    };
  }

  /* ───── صحنه ───── */
  async function open(id) {
    const g = ++D.gen;
    root().className = ""; root().innerHTML = '<div class="tm-in mu">در حال بارگذاری…</div>';
    try {
      await meta();
      const r = await api("/api/duos/" + id);
      D.duo = r.duo; D.ids = new Set(); D.seq = r.seq; D.live = r.live || {}; D.stick = true;
      paintArena(); r.msgs.forEach(m => addMsg(m, true)); paintLive(); tlEnd(true);
      poll(g);
    } catch (e) { toast(e.message); list(); }
  }

  function paintArena() {
    root().className = "ar";
    root().innerHTML = `<div class="ar-top"><button class="ib" id="ab" aria-label="بازگشت">${ic("back")}</button><div class="tt"><b id="at"></b><span class="mu" id="as"></span></div><span id="ast"></span><button class="ib" id="am" aria-label="منو">${ic("more")}</button></div>
      <div class="ar-ag" id="aag"></div><div class="steps" id="astp"></div><div class="prog"><i id="apg"></i></div><div class="ar-meta" id="amt"></div>
      <div id="tl"></div>
      <div class="tctl"><div class="row" id="acb"></div>
        <div class="say"><select id="ato" aria-label="مخاطب"></select><textarea id="asy" rows="1" placeholder="به‌عنوان کارگردان به تیم پیام بده…"></textarea><button class="go" id="asb" aria-label="ارسال">${ic("send")}</button></div></div>`;
    $("ab").onclick = list; $("am").onclick = menu;
    $("tl").onscroll = () => { const t = $("tl"); D.stick = t.scrollHeight - t.scrollTop - t.clientHeight < 90; };
    $("asb").onclick = say;
    $("asy").oninput = e => { e.target.style.height = "auto"; e.target.style.height = Math.min(90, e.target.scrollHeight) + "px"; };
    paintHead();
  }
  function paintHead() {
    const d = D.duo; if (!d || !$("at")) return;
    $("at").textContent = d.title; $("ast").innerHTML = pill(d.status); $("as").textContent = mode();
    const liveIds = Object.keys(D.live), act = id => liveIds.includes(id) || (!liveIds.length && d.status === "running" && d.next === id);
    $("aag").innerHTML = d.agents.map((a, i) => `<div class="agb ${act(a.id) ? "act" : ""}" style="--c:${a.color}">${avatar(a, i, true)}<div class="nm"><b>${esc(a.name)}</b><span>${liveIds.includes(a.id) ? "در حال نوشتن…" : esc(a.role)}</span></div>${d.flags[a.id] || d.appr[a.id] ? `<span class="okm" title="موافق/تأیید">${ic("check")}</span>` : ""}</div>`).join("");
    const steps = d.mode === "build" ? PH : [PH[0], PH[1], ["done", "پایان"]], cur = steps.findIndex(p => p[0] === d.phase);
    $("astp").innerHTML = steps.map((p, i) => `<span class="${i === cur ? "on" : i < cur ? "dn" : ""}">${p[1]}</span>`).join("");
    $("apg").style.width = (d.phase === "done" ? 100 : d.phase === "discuss" ? Math.min(30, (d.round / d.max_rounds) * 30) : d.phase === "finalize" ? 40 : d.phase === "build" ? Math.min(85, 45 + (d.cycle / d.build_cycles) * 40) : 92) + "%";
    $("amt").innerHTML = `<span>راند ${fa(d.round)}/${fa(d.max_rounds)}${d.mode === "build" && d.phase === "build" ? " · دور " + fa(d.cycle + 1) + "/" + fa(d.build_cycles) : ""}</span><span>${fa(d.decisions.length)} تصمیم · ${fa(d.turns)} نوبت</span>`;
    const sel = $("ato"), v = sel.value; sel.innerHTML = '<option value="all">همه</option>' + d.agents.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join(""); sel.value = v || "all";
    const run = d.status === "running";
    $("acb").innerHTML = (run
      ? `<button class="btn" id="c1">${ic("pause")}مکث</button><button class="btn d" id="c2">${ic("stop")}توقف</button>`
      : `<button class="btn p" id="c1">${ic("play")}${d.status === "idle" ? "شروع" : "ادامه"}</button><button class="btn" id="c4">${ic("step")}یک گام</button>`)
      + `<button class="btn" id="c3">${ic("pin")}${fa(d.decisions.length)} تصمیم</button><button class="btn" id="c5">${ic("box")}تحویل</button>`;
    if (run) { $("c1").onclick = () => ctl("pause"); $("c2").onclick = () => ctl("stop"); }
    else { $("c1").onclick = () => ctl(d.status === "idle" ? "start" : "resume"); $("c4").onclick = () => ctl("step"); }
    $("c3").onclick = decisions; $("c5").onclick = delivery;
  }
  async function ctl(a) { try { await api("/api/duos/" + D.duo.id + "/ctl", "POST", { action: a }); haptic(); await pollOnce(); } catch (e) { toast(e.message); } }

  /* ───── پیام‌ها ───── */
  function msgHtml(m) {
    if (m.agent === "sys") return `<div class="sysn">${esc(m.text)}</div>`;
    if (m.agent === "user") return `<div class="tb me"><div class="bx"><div class="bh"><b style="color:var(--wn)">تو (کارگردان)</b><span class="mu">${m.to === "all" || !m.to ? "← همه" : "← " + esc((ag(m.to) || {}).name || "")}</span></div><div class="a">${md(m.text)}</div></div></div>`;
    const i = D.duo.agents.findIndex(a => a.id === m.agent), a = ag(m.agent) || { name: "؟", role: "عضو سابق", color: "#888", skill: "custom" };
    const tr = (m.trace || []).length ? `<div class="grp"><button class="gh" data-g="1">${ic("list")}<span style="flex:1">${fa(m.trace.length)} اقدام</span>${ic("chev", "cv")}</button><div class="gb">${m.trace.map(t => t.k === "file" ? `<div class="rw"><div class="rh">${ic("file")}<span class="rp ltr mono">${esc(t.p)}</span><span class="k ${t.ok ? "ok" : "no"}">${ic(t.ok ? "check" : "x")}</span></div></div>` : `<div class="rw o"><div class="rh">${ic("play")}<span class="rp ltr mono">${esc(t.p)}</span></div><div class="rd"><div>${esc(t.x || "")}</div></div></div>`).join("")}</div></div>` : "";
    return `<div class="tb" style="--c:${a.color}">${avatar(a, i)}<div class="bx"><div class="bh"><b>${esc(a.name)}</b><span class="mu">${esc(a.role)}</span><span class="kd">${KIND[m.kind] || esc(m.kind)}</span><span class="mu">R${fa(m.round)}</span></div>
      <div class="a">${md(m.text)}</div>${(m.decs || []).map(x => `<div class="dec">${esc(x)}</div>`).join("")}${tr}
      <div class="tft">${m.agree ? `<span class="chip ok">${ic("check")}موافق</span>` : ""}${m.approve ? `<span class="chip ok">${ic("check")}تأیید کار</span>` : ""}${(m.files || []).map(f => `<button class="chip ltr mono" data-open="${esc(f)}">${ic("file")}${esc(f)}</button>`).join("")}<span>${fa(m.dur)} ث · ~${tokens(m.chars)} توکن</span></div></div></div>`;
  }
  function addMsg(m, quiet) {
    if (D.ids.has(m.id)) return;
    D.ids.add(m.id);
    const t = $("tl"); if (!t) return;
    const w = document.createElement("div"); w.innerHTML = msgHtml(m);
    t.insertBefore(w.firstElementChild, t.querySelector(".tb.live") || null);
    if (!quiet) tlEnd();
  }
  function paintLive() {
    const t = $("tl"); if (!t) return;
    t.querySelectorAll(".tb.live").forEach(el => { if (!D.live[el.dataset.a]) el.remove(); });
    Object.values(D.live).forEach(L => {
      const a = ag(L.agent); if (!a) return;
      let el = t.querySelector(`.tb.live[data-a="${L.agent}"]`);
      if (!el) { el = document.createElement("div"); el.className = "tb live"; el.dataset.a = L.agent; t.appendChild(el); }
      el.style.setProperty("--c", a.color);
      el.innerHTML = `${avatar(a, D.duo.agents.indexOf(a))}<div class="bx"><div class="bh"><b>${esc(a.name)}</b><span class="mu">${esc(a.role)}</span><span class="kd">${L.phase === "discuss" ? "در حال نوشتن" : L.phase === "build" ? "در حال کار" : L.phase === "polish" ? "صیقل نهایی" : "مستندسازی"}</span></div><div class="a">${md(L.text)}</div>${DOTS}</div>`;
    });
    tlEnd();
  }
  function tlEnd(force) { const t = $("tl"); if (t && (force || D.stick)) t.scrollTop = t.scrollHeight; }
  document.addEventListener("click", e => {
    const t = e.target.closest("#tl [data-g]"); if (t) { t.parentElement.classList.toggle("o"); return; }
    const o = e.target.closest("#tl [data-open]"); if (o) openFile(o.dataset.open);
  });

  /* ───── رویدادها و polling ───── */
  function onEv(e) {
    if (e.t === "state") { D.duo = e.duo; paintHead(); }
    else if (e.t === "start") { D.live[e.agent] = { agent: e.agent, text: "", phase: e.phase }; paintHead(); paintLive(); }
    else if (e.t === "delta") { const L = D.live[e.agent]; if (L) { L.text += e.x; if (!D.raf) D.raf = requestAnimationFrame(() => { D.raf = 0; paintLive(); }); } }
    else if (e.t === "msg") { if (e.m.agent !== "sys" && e.m.agent !== "user") delete D.live[e.m.agent]; addMsg(e.m); paintLive(); paintHead(); if (e.m.files && e.m.files.length) api("/api/projects/" + S.P).then(p => drawFiles(p.files)).catch(() => {}); }
  }
  async function pollOnce() {
    const r = await api("/api/duos/" + D.duo.id + "/poll?after=" + D.seq);
    if (r.reset) return open(D.duo.id);
    D.seq = r.seq; r.ev.forEach(onEv);
  }
  async function poll(g) {
    let errs = 0;
    while (g === D.gen && D.duo) {
      if (S.view === "team") { try { await pollOnce(); errs = 0; } catch (e) { if (++errs > 20) return toast(e.message); } }
      await sleep(D.duo && D.duo.status === "running" ? 500 : 2500);
    }
  }

  /* ───── دخالت کارگردان ───── */
  async function say() {
    const text = $("asy").value.trim(); if (!text) return;
    try {
      const r = await api("/api/duos/" + D.duo.id + "/say", "POST", { text, to: $("ato").value });
      $("asy").value = ""; $("asy").style.height = "auto"; await pollOnce();
      if (r.reopened) toast("کار دوباره باز شد؛ «ادامه» رو بزن");
      else if (D.duo.status !== "running") toast("پیام ثبت شد؛ با «ادامه» یا «یک گام» تیم می‌بینه");
    } catch (e) { toast(e.message); }
  }

  /* ───── تابلوی تصمیم، تحویل و منو ───── */
  function decisions() {
    const d = D.duo;
    openSheet(`<h3>تابلوی تصمیم‌ها<button class="ib" data-x aria-label="بستن">${ic("x")}</button></h3><div class="mu" style="font-size:12.5px">متخصص‌ها این قرارها رو در همه‌ی نوبت‌ها می‌بینن. سنجاق‌شده‌ها قطعی‌ان.</div>`
      + (d.decisions.length ? d.decisions.map(x => `<div class="drow"><div class="tx">${esc(x.text)}<div class="by">${x.by === "user" ? "کارگردان" : esc((ag(x.by) || {}).name || "")} · راند ${fa(x.round)}</div></div><button class="ib" data-a="pin" data-id="${x.id}" style="${x.pinned ? "color:var(--ac)" : ""}">${ic("pin")}</button><button class="ib" data-a="del" data-id="${x.id}">${ic("trash")}</button></div>`).join("") : '<div class="mu">هنوز قراری ثبت نشده.</div>')
      + '<div style="display:flex;gap:6px"><input id="dnw" placeholder="افزودن قرار دستی…"><button class="btn p" id="dna">افزودن</button></div>');
    const act = async b => { try { await api("/api/duos/" + d.id + "/decisions", "POST", b); await pollOnce(); decisions(); } catch (e) { toast(e.message); } };
    $("tsh").onclick = e => { if (e.target.closest("[data-x]")) return closeSheet(); const b = e.target.closest("[data-a]"); if (b) act({ action: b.dataset.a, id: b.dataset.id }); };
    $("dna").onclick = () => { const t = $("dnw").value.trim(); if (t) act({ action: "add", text: t }); };
  }
  async function delivery() {
    openSheet(`<h3>خروجی و تحویل<button class="ib" data-x aria-label="بستن">${ic("x")}</button></h3><div class="mu">در حال بررسی پروژه…</div>`);
    $("tsh").onclick = e => { if (e.target.closest("[data-x]")) closeSheet(); };
    try {
      const r = await api("/api/duos/" + D.duo.id + "/delivery");
      drawFiles(r.files);
      openSheet(`<h3>خروجی و تحویل<button class="ib" data-x aria-label="بستن">${ic("x")}</button></h3>${r.report ? `<div class="rep a">${md(r.report)}</div>` : '<div class="mu" style="font-size:12.8px">گزارش تحویل نهایی بعد از فاز صیقل نوشته می‌شه.</div>'}
        <div class="sec">بررسی خودکار پروژه</div>${r.issues.length ? r.issues.map(x => `<div class="chip bad" style="white-space:normal;border-radius:10px;padding:3px 10px">${ic("x")}${esc(x)}</div>`).join("") : `<div class="chip ok" style="align-self:flex-start">${ic("check")}سینتکس، لینک‌ها و idها سالم‌ان</div>`}
        <div class="sec">فایل‌ها (${fa(r.files.length)})</div>${r.files.map(f => `<button class="fr" data-f="${esc(f.path)}">${ic("file")}<span class="n">${esc(f.path)}</span><span class="z">${fa(f.lines)} خط</span></button>`).join("") || '<div class="mu">فایلی نیست.</div>'}
        <div class="grid"><button class="btn p" id="dpv">${ic("eye")}پیش‌نمایش</button><button class="btn" id="dzp">${ic("down")}zip در چت</button></div>`);
      $("tsh").onclick = e => { if (e.target.closest("[data-x]")) return closeSheet(); const b = e.target.closest("[data-f]"); if (b) { closeSheet(); openFile(b.dataset.f); } };
      $("dpv").onclick = () => { closeSheet(); goTab("pv"); };
      $("dzp").onclick = async () => { try { await api("/api/projects/" + S.P + "/sendzip", "POST"); toast("zip به تلگرام ارسال شد"); } catch (e) { toast(e.message); } };
    } catch (e) { toast(e.message); }
  }
  function menu() {
    const d = D.duo, row = (a, i, t, d2) => `<button class="li ${d2 ? "" : ""}" data-a="${a}">${ic(i)}<span style="${a === "del" ? "color:var(--bd)" : ""}">${t}</span></button>`;
    openSheet(`<h3>${esc(d.title)}<button class="ib" data-x aria-label="بستن">${ic("x")}</button></h3>
      ${row("manual", d.manual ? "check" : "pause", "حالت گام‌به‌گام " + (d.manual ? "(روشن)" : "(خاموش)"))}
      ${row("par", d.parallel ? "check" : "pause", "نظر اولیه‌ی هم‌زمان " + (d.parallel ? "(روشن)" : "(خاموش)"))}
      ${row("edit", "edit", "ویرایش / افزودن / حذف متخصص‌ها و سقف راندها")}
      ${row("copy", "file", "کپی گزارش کامل (Markdown)")}
      ${row("pub", "box", "ذخیره‌ی تصمیم‌ها و گزارش در فایل‌های پروژه")}
      ${row("del", "trash", "حذف این تیم")}`);
    $("tsh").onclick = async e => {
      if (e.target.closest("[data-x]")) return closeSheet();
      const b = e.target.closest("[data-a]"); if (!b) return; const a = b.dataset.a;
      try {
        if (a === "manual") { await api("/api/duos/" + d.id, "PATCH", { manual: !d.manual }); await pollOnce(); menu(); }
        else if (a === "par") { await api("/api/duos/" + d.id, "PATCH", { parallel: !d.parallel }); await pollOnce(); menu(); }
        else if (a === "edit") editForm();
        else if (a === "copy") { const r = await fetch("/api/duos/" + d.id + "/export", { headers: hdr() }); cpyText(await r.text()); closeSheet(); }
        else if (a === "pub") { await api("/api/duos/" + d.id + "/publish", "POST"); drawFiles((await api("/api/projects/" + S.P)).files); toast("توی docs/ ذخیره شد"); closeSheet(); }
        else if (a === "del") { if (await yes("این تیم و تمام پیام‌هاش حذف بشه؟")) { await api("/api/duos/" + d.id, "DELETE"); closeSheet(); list(); } }
      } catch (er) { toast(er.message); }
    };
  }
  function editForm() {
    const d = D.duo, f = { agents: JSON.parse(JSON.stringify(d.agents)), max_rounds: d.max_rounds, build_cycles: d.build_cycles };
    openSheet(`<h3>ویرایش تیم<button class="ib" data-x aria-label="بستن">${ic("x")}</button></h3>${d.status === "running" ? '<div class="mu" style="font-size:12.5px">برای تغییر ترکیب متخصص‌ها اول تیم رو مکث کن.</div>' : ""}<div id="ea" class="col"></div>
      <div class="fld"><label>حداکثر راند: <b id="rv">${fa(f.max_rounds)}</b></label><input type="range" id="fr" min="${Math.max(1, d.round + 1)}" max="24" value="${f.max_rounds}"></div>
      <div class="fld"><label>حداکثر دور رفع ایراد: <b id="cv">${fa(f.build_cycles)}</b></label><input type="range" id="fc" min="1" max="6" value="${f.build_cycles}"></div>
      <button class="btn p" id="fsv" style="justify-content:center;padding:8px">ذخیره (از نوبت بعدی اعمال می‌شه)</button>`);
    $("tsh").addEventListener("click", e => { if (e.target.closest("[data-x]") && !e.target.closest(".agc")) closeSheet(); });
    agentsEditor($("ea"), f.agents);
    $("fr").oninput = e => { f.max_rounds = +e.target.value; $("rv").textContent = fa(f.max_rounds); };
    $("fc").oninput = e => { f.build_cycles = +e.target.value; $("cv").textContent = fa(f.build_cycles); };
    $("fsv").onclick = async () => { try { await api("/api/duos/" + d.id, "PATCH", f); await pollOnce(); closeSheet(); toast("ذخیره شد"); } catch (e) { toast(e.message); } };
  }
})();
