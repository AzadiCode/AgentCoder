# -*- coding: utf-8 -*-
"""
CodeWise Team — تیم متخصص‌ها (۲ تا ۶ ایجنت) با کانال تخصصی؛ بحث ← جمع‌بندی (SPEC/DESIGN) ← ساخت ← بازبینی ← صیقل نهایی ← تحویل

متخصص‌ها (هرکدام playbook و خروجی تعریف‌شده دارن، نه یه «شخصیت» کلی):
  strategist  ایده‌پرداز و استراتژیست سناریو   (۳ سناریو + ماتریس امتیاز + MVP)
  designer    طراح UI/UX و گرافیک              (توکن‌های طراحی، DESIGN.md، لایه‌ی بصری)
  architect   معمار و سرپرست تیم               (معماری، SPEC.md)
  developer   برنامه‌نویس ارشد                 (ساخت کامل و اجرا)
  qa          تستر، امنیت و پرفورمنس           (بازبینی روی فایل‌های واقعی)
  skeptic     منتقد (pre-mortem)               (ریسک‌های واقعی و راه‌حل)
  custom      متخصص دلخواه (شخصیت و دسترسی رو خودت تعیین می‌کنی)

فازها: discuss → finalize → build(سازنده‌ها ← بازبین‌ها، چرخه‌ی رفع ایراد) → polish(یکپارچه‌سازی و تحویل) → done
سرعت: راند اول بحث هم‌زمان (موازی) اجرا می‌شه و نظرها مستقل از هم نوشته می‌شن (سریع‌تر + بدون اثر لنگر).
"""
import os
import re
import time
import uuid
import threading
import logging

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from flask import jsonify, request, Response

log = logging.getLogger("codewise.duo")
db = None   # توسط register پر می‌شه
C = None    # ماژول هسته (app.py)

IDS = "abcdef"
COLORS = ["#3CCFE3", "#B794F6", "#F6AD55", "#68D391", "#F687B3", "#63B3ED"]
MAX_DUOS, MAX_AGENTS = 40, 6

# ───────────────────────── کتابخانه‌ی متخصص‌ها ─────────────────────────
SKILLS = {
    "strategist": {
        "fa": "ایده‌پرداز و استراتژیست", "en": "Ideation & Scenario Strategist", "icon": "💡", "name": "ایمان", "order": 10, "build_order": 0,
        "discuss": True, "builds": False, "reviews": False, "temp": 0.9,
        "short": "ایده‌های بکر، ۳ سناریوی امتیازدهی‌شده، انتخاب بهترین و برش MVP",
        "persona": "Ideation & scenario strategist. You think in user jobs-to-be-done, differentiation and sequencing. You never offer a single idea: you lay out the option space, score it honestly and commit to a recommendation. Creative yet buildable — every idea must be shippable by a small team.",
        "discuss1": ("Round 1 brief. Output: (1) Target user + job-to-be-done + 2 key assumptions (2-3 lines). (2) Exactly 3 scenarios — A Safe, B Balanced, C Bold — each with: concept, core flow in 3-5 steps, differentiator, main risk, effort S/M/L. "
                     "(3) A markdown scoring table (1-5) with columns: User value | Feasibility | Differentiation | Risk (lower=better) | Time-to-MVP | Total. (4) Your recommendation (one scenario or a hybrid), ONE signature 'wow' feature, the MVP cut (Must/Should/Won't) and one success metric. "
                     "Record the chosen direction and the MVP cut as <decision>. Up to ~380 words. Tag: [SCENARIOS]."),
        "discuss2": "Refine your recommendation using the team's critique: adjust the scores if warranted, tighten the MVP cut, and write acceptance criteria for the 3 most important user flows. Do not restart from scratch.",
    },
    "skeptic": {
        "fa": "منتقد و تحلیل‌گر ریسک", "en": "Pre-mortem Skeptic", "icon": "🧐", "name": "رها", "order": 30, "build_order": 0,
        "discuss": True, "builds": False, "reviews": False, "temp": 0.6,
        "short": "پیش‌مرگ‌کاوی: ریسک‌های واقعی را رتبه‌بندی می‌کند و برای هرکدام راه‌حل می‌دهد",
        "persona": "Pre-mortem skeptic and risk analyst. You find the flaw that would actually sink the project, rank it, and always attach a concrete fix. Evidence over opinion; you endorse what is strong.",
        "discuss1": ("Run a pre-mortem on the proposals so far (or, if you are writing blind, on the goal itself): (1) the 3 most likely failure modes ranked by likelihood × impact, each with an early-warning signal and a concrete mitigation; "
                     "(2) challenge any shaky assumption/score by name; (3) say what you endorse. Ask at most ONE sharp question. Up to ~250 words. Tag: [CRITIQUE]."),
        "discuss2": "Re-test the revised plan: which risks are now closed, which remain, and what is the single biggest threat left? Use <agree/> only if none is material.",
    },
    "designer": {
        "fa": "طراح UI/UX و گرافیک", "en": "UI/UX & Graphic Designer", "icon": "🎨", "name": "نگار", "order": 20, "build_order": 20,
        "discuss": True, "builds": True, "reviews": False, "temp": 0.7,
        "short": "هویت بصری، توکن‌های طراحی، DESIGN.md و پیاده‌سازی لایه‌ی بصری (CSS/SVG)",
        "persona": "Senior UI/UX and graphic designer for Persian/RTL, mobile-first products (Telegram mini-apps included). You design systems, not decoration: tokens, hierarchy, states, accessibility and purposeful motion. You give exact values (hex, px, ms), never vague adjectives.",
        "discuss1": ("Give the design direction: (1) mood in 3 words + the ONE design idea that makes this product feel distinct; (2) palette tokens in hex for dark AND light (bg, surface, text, muted, accent, ok, warn, danger) with contrast notes (text >= 4.5:1); "
                     "(3) type: Vazirmatn with a system fallback, a 5-step scale (px/weight); (4) spacing (4/8 grid), radius, shadow, motion (150-250ms, honor prefers-reduced-motion); "
                     "(5) key screens as short ASCII wireframes (mobile 360px, RTL) with components and their states (default/hover/active/disabled/loading/empty/error); (6) icon/logo approach (inline SVG). Up to ~380 words. Tag: [DESIGN]."),
        "discuss2": "Adjust the design direction to the technical constraints and critiques raised. Keep tokens consistent; flag any UX risk (tap targets >= 44px, empty/error states, long Persian text).",
        "final": ("Write DESIGN.md with <write>: Vision; Tokens as copy-paste-ready CSS custom properties (:root plus dark/light overrides); Typography; Layout & spacing; Components with the EXACT CSS class names the developer must use "
                  "(a 'class contract' table: class → purpose → states); Screens (ASCII wireframes); Motion; Accessibility checklist; Asset list. Then reply with a 3-line summary. Tag: [DESIGN]."),
        "build": ("The developer built the structure/logic. Implement the VISUAL layer now: read the real HTML/CSS first, then create/update the stylesheet (CSS custom properties from DESIGN.md, mobile-first, RTL-safe logical properties, dark+light, "
                  "all component states, subtle transitions, focus-visible rings, prefers-reduced-motion) and make SVG icons/logos. You may edit HTML only for class names, ARIA, semantic wrappers and SVG — never application logic or ids/data-attributes used by scripts. "
                  "No new external CDNs. Verify by reading markup against your selectors: every class used in the HTML is styled and there are no dead selectors. Finish with a short summary."),
        "fix": "Fix EVERY visual / UX / accessibility issue raised for your files, re-check against the markup, and summarize by issue number.",
    },
    "architect": {
        "fa": "معمار نرم‌افزار و سرپرست تیم", "en": "Software Architect & Team Lead", "icon": "🏛", "name": "آرتا", "order": 40, "build_order": 0,
        "discuss": True, "builds": False, "reviews": False, "temp": 0.4,
        "short": "معماری، قرارداد API و مدل داده، تصمیم‌گیری نهایی و نوشتن SPEC.md",
        "persona": "Pragmatic principal architect and the team lead. You make clean, minimal, testable designs with explicit trade-offs and you are decisive. You own the final spec and resolve disagreements with a clear rationale.",
        "discuss1": ("Propose the architecture for the recommended direction: modules/files each with a responsibility and approx line budget (<= 250 lines per file), data model, API/contract (routes + payloads), state & error handling, "
                     "security basics (validation, authz, secrets), build order and test strategy. Adopt good points from teammates by name; resolve conflicts explicitly. Up to ~380 words. Tag: [PLAN]."),
        "discuss2": "Resolve open disagreements, lock the contracts (ids, routes, payloads, class names) and fix the build order. Use <agree/> when the plan is complete and consistent.",
        "final": ("Consolidate everything agreed into SPEC.md with <write> (if DESIGN.md exists, <read> it and reference it): Goal; Scope & non-goals; Chosen scenario & MVP cut; Architecture & file map; Data model / APIs; Key decisions; "
                  "Task breakdown in build order (assign each task to a role); Acceptance criteria (testable, per flow); Risks & mitigations. Then reply with a 3-line summary. Tag: [PLAN]."),
    },
    "developer": {
        "fa": "برنامه‌نویس ارشد", "en": "Lead Developer", "icon": "💻", "name": "دانا", "order": 50, "build_order": 10,
        "discuss": True, "builds": True, "reviews": False, "temp": 0.2,
        "short": "ساخت کامل و کارکرد درست، اجرای تست، رفع ایراد بدون خراب‌کردن فایل‌ها",
        "persona": "Lead developer. You write complete, working, readable code with proper error handling and input validation and no placeholders. You honor the spec and teammates' contracts (ids, class names, routes). You verify by running.",
        "discuss1": "Feasibility voice, up to ~220 words: effort per module (S/M/L), the 2 riskiest technical points and how to de-risk them, library choices (prefer stdlib/minimal deps), what to simplify or cut to ship a polished MVP, and any contract you need from the others. Tag: [IDEA] or [CRITIQUE].",
        "discuss2": "Confirm the contracts you will build against and flag anything that still cannot be built as specified. Use <agree/> if you can start building.",
        "build": ("Implement the project now per SPEC.md (and DESIGN.md's class contract if present). Order: data/logic → structure (HTML/templates using the contract's class names and ids) → wiring. Complete files only; split modules over ~250 lines; then run/test. "
                  "If a designer is on the team, use semantic contract-named markup and leave visual polish to them; otherwise style it well yourself. Finish with a short summary of what you built and how to run it."),
        "fix": "Fix EVERY issue raised for your files, re-run to verify, and summarize the fixes by issue number.",
    },
    "qa": {
        "fa": "تستر، امنیت و پرفورمنس", "en": "QA, Security & Performance Engineer", "icon": "🛡", "name": "مهسا", "order": 60, "build_order": 0,
        "discuss": False, "builds": False, "reviews": True, "temp": 0.2,
        "short": "بازبینی روی فایل‌های واقعی: اجرا، باگ، امنیت، هماهنگی HTML/JS/CSS و تأیید نهایی",
        "persona": "QA & security engineer with a performance eye. You verify by reading and running, never by assumption. You report precise, reproducible issues with severity and a concrete fix.",
        "discuss1": "Contribute testability: list the acceptance tests and the top security/performance concerns for this goal in <= 150 words. Tag: [CRITIQUE].",
        "discuss2": "Confirm the acceptance criteria are testable.",
        "review": ("Review the REAL files now. Steps: <ls/>, read SPEC.md, read every source file (ranges for big ones), run the entrypoint/tests. Check: (a) each acceptance criterion in SPEC.md; (b) correctness & edge cases; "
                   "(c) input validation, XSS/injection/authz/secrets; (d) error handling; (e) cross-file consistency (HTML ids/classes ↔ JS ↔ CSS, routes ↔ fetch calls); (f) UI: RTL, responsive, states, accessibility; (g) obvious performance traps. "
                   "Output a verdict, then numbered issues as `[P0|P1|P2] file:line — problem — fix` (max 12, no nitpicks, name the owner role when clear). If there are no P0/P1 issues, say so and add <approve/>. Tag: [REVIEW]."),
    },
    "custom": {
        "fa": "متخصص دلخواه", "en": "Custom Specialist", "icon": "✨", "name": "متخصص", "order": 70, "build_order": 30,
        "discuss": True, "builds": False, "reviews": False, "temp": 0.6,
        "short": "تخصص و رفتار دلخواه خودت؛ تعیین کن بحث کند، بسازد یا بازبینی کند",
        "persona": "Domain specialist defined by the director's instructions below.",
        "discuss1": "Contribute your specialty to the goal: concrete proposals, risks and a recommendation, up to ~250 words, building on teammates' points.",
        "discuss2": "Respond to teammates' latest points from your specialty and advance the plan.",
        "build": "Do your part of the implementation per SPEC.md using the tools, verify it, and summarize.",
        "fix": "Fix every issue raised for your files and summarize.",
        "review": "Review the real files from your specialty's point of view. List numbered issues `[P0|P1|P2] file:line — problem — fix`; if none are P0/P1 add <approve/>.",
    },
}

TEAMS = {
    "full": {"label": "تیم کامل محصول", "hint": "ایده ← طراحی ← معماری ← ساخت ← تست؛ خروجی حرفه‌ای و کامل", "mode": "build",
             "skills": ["strategist", "designer", "architect", "developer", "qa"]},
    "build": {"label": "ساخت سریع", "hint": "معمار + برنامه‌نویس + تستر؛ کوتاه و کاربردی", "mode": "build", "skills": ["architect", "developer", "qa"]},
    "frontend": {"label": "طراحی و فرانت‌اند", "hint": "برای صفحه/وب‌اپ با ظاهر درجه‌یک", "mode": "build", "skills": ["designer", "developer", "qa"]},
    "ideas": {"label": "ایده و برنامه‌ریزی", "hint": "فقط بحث و SPEC.md؛ سناریوها، نقد ریسک و معماری", "mode": "plan", "skills": ["strategist", "skeptic", "architect"]},
    "duo": {"label": "دونفره: معمار ⟷ منتقد", "hint": "سبک و سریع، مناسب بررسی یک تصمیم", "mode": "plan", "skills": ["architect", "skeptic"]},
}

_KINDS = "IDEA|SCENARIOS|DESIGN|QUESTION|ANSWER|CRITIQUE|PLAN|DECISION|REVIEW|BUILD|DELIVER|SUMMARY"
KIND_ANY = re.compile(r"^[ \t`]*\[(" + _KINDS + r")\]", re.I | re.M)
KIND_LINE = re.compile(r"^[ \t]*\[(?:" + _KINDS + r")\][ \t]*", re.I | re.M)

DUO_SYS = """You are {name} — {title} — on a small team of AI specialists building ONE project for a human director.
TEAM: {roster}
The human director may interject with [DIRECTOR] messages — top priority; follow them. Reply in the director's language (Persian by default); keep code, file names and identifiers in English.

YOUR SPECIALTY (stay inside it; the others cover the rest):
{persona}{extra}

PROJECT GOAL:
{goal}

DECISION BOARD (agreed, binding):
{board}

TEAM RULES
- Begin your message with exactly ONE tag: [IDEA] [SCENARIOS] [DESIGN] [CRITIQUE] [PLAN] [DECISION] [QUESTION] [ANSWER] [REVIEW] [BUILD] [DELIVER].
- Deliver substance: concrete, specific, decision-ready. No filler, no flattery, no restating what was said. Build on teammates' latest points: adopt what is strong (credit them by name), challenge what is weak with a reason and a better alternative.
- Record settled points as <decision>one sentence</decision> (max 3 per turn). Use <agree/> at the very end only when the plan is complete and you have nothing material left to challenge (never in round 1).
- Quality gate: before sending, silently check your output against the specification of your task; close any gap.
{phase}"""


# ───────────────────────── وضعیت زنده ─────────────────────────
CTL, FEEDS, LIVE, THREADS, OWN = {}, {}, {}, {}, {}
LK = threading.RLock()


class Feed:
    def __init__(self):
        self.base, self.ev = 0, []

    def add(self, e):
        with LK:
            self.ev.append(e)
            if len(self.ev) > 2500:
                del self.ev[:800]
                self.base += 800

    def seq(self):
        return self.base + len(self.ev)

    def since(self, after):
        with LK:
            if after < self.base:
                return None, self.seq()
            return self.ev[after - self.base:], self.seq()


def feed(did):
    with LK:
        return FEEDS.setdefault(did, Feed())


def emit(did, **e):
    feed(did).add(e)


def alive(did):
    t = THREADS.get(did)
    return bool(t and t.is_alive())


# ───────────────────────── کمکی‌ها ─────────────────────────
def _oid(x):
    try:
        return ObjectId(x)
    except (InvalidId, TypeError):
        return None


def clamp(v, lo, hi, dflt):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


def clean_agents(raw):
    """لیست ایجنت‌ها (۲ تا ۶) را نرمال می‌کند؛ هر ایجنت یک skill از کتابخانه دارد (یا custom)"""
    if not isinstance(raw, list):
        return None
    out, used = [], set()
    for i, r in enumerate(raw[:MAX_AGENTS]):
        r = r if isinstance(r, dict) else {}
        skill = r.get("skill") if r.get("skill") in SKILLS else "custom"
        sk = SKILLS[skill]
        aid = r.get("id") if r.get("id") in tuple(IDS) and r.get("id") not in used else next(x for x in IDS if x not in used)
        used.add(aid)
        builds = bool(r.get("builds", sk["builds"])) if skill == "custom" else sk["builds"]
        out.append({"id": aid, "color": COLORS[IDS.index(aid)], "skill": skill, "icon": sk["icon"],
                    "name": str(r.get("name") or sk["name"]).strip()[:30] or sk["name"],
                    "role": str(r.get("role") or sk["fa"]).strip()[:60] or sk["fa"],
                    "persona": str(r.get("persona") or "").strip()[:1200],
                    "model": str(r.get("model") or "").strip()[:80],
                    "discuss": bool(r.get("discuss", sk["discuss"])) if skill == "custom" else sk["discuss"],
                    "builds": builds,
                    "reviews": (bool(r.get("reviews", sk["reviews"])) and not builds) if skill == "custom" else sk["reviews"],
                    "order": sk["order"] + (i if skill == "custom" else 0), "build_order": sk["build_order"] + (i if skill == "custom" else 0)})
    seen = {}
    for a in out:                                   # نام تکراری ممنوع
        n = seen.get(a["name"], 0)
        seen[a["name"]] = n + 1
        if n:
            a["name"] += f" {n + 1}"
    return out if len(out) >= 2 else None


def norm_duo(d):
    """دوئل‌های قدیمی (دو ایجنت بدون skill) را در حافظه با مدل جدید سازگار می‌کند"""
    ag = d.get("agents") or []
    if ag and any("skill" not in a for a in ag):
        old = []
        for i, a in enumerate(ag):
            old.append({**a, "skill": "custom", "discuss": True, "builds": i == 0, "reviews": i == 1})
        d["agents"] = clean_agents(old) or ag
    if "qi" not in d:
        d["qi"] = 0 if d.get("next", "a") == "a" else 1
    d.setdefault("appr", {})
    d.setdefault("fq", [])
    return d


def get_duo(did, uid):
    o = _oid(did)
    d = db.duos.find_one({"_id": o, "owner": uid}) if o else None
    return norm_duo(d) if d else None


def A(d):
    return {a["id"]: a for a in d["agents"]}


def lead(d):
    ag = d["agents"]
    return next((a for a in ag if a["skill"] == "architect"), None) or next((a for a in ag if a["skill"] == "developer"), None) or ag[0]


def builders(d):
    b = sorted([a for a in d["agents"] if a["builds"]], key=lambda a: a["build_order"])
    return b or [lead(d)]


def reviewers(d):
    return [a for a in d["agents"] if a["reviews"]]


def integrator(d):
    return next((a for a in builders(d) if a["skill"] == "developer"), None) or builders(d)[0]


def queue(d, phase):
    ag = sorted(d["agents"], key=lambda a: a["order"])
    if phase == "discuss":
        return [a["id"] for a in ag if a["discuss"]] or [a["id"] for a in ag]
    if phase == "finalize":
        q = [a["id"] for a in ag if a["skill"] == "designer"]
        L = lead(d)["id"]
        return q + ([L] if L not in q else [])
    if phase == "build":
        first = [a["id"] for a in builders(d)] if d.get("cycle", 0) == 0 else [i for i in d.get("fq", []) if i in A(d)] or [integrator(d)["id"]]
        return first + [a["id"] for a in reviewers(d) if a["id"] not in first]
    if phase == "polish":
        return [integrator(d)["id"]]
    return []


def fix_queue(d):
    """سازنده‌هایی که فایل‌هاشون در بازبینی‌ها ذکر شده (یا اسمشون اومده)؛ وگرنه برنامه‌نویس اصلی"""
    did, ag = str(d["_id"]), A(d)
    owner = {}
    for m in db.duo_msgs.find({"did": did, "files": {"$exists": True, "$ne": []}}).sort("seq", 1):
        for f in m.get("files", []):
            owner[f] = m["agent"]
    rv = [a["id"] for a in reviewers(d)]
    txt = "\n".join(m["text"] for m in db.duo_msgs.find({"did": did, "agent": {"$in": rv}}).sort("seq", -1).limit(len(rv) or 1))
    hit = set()
    for f, o in owner.items():
        if o in ag and ag[o]["builds"] and (f in txt or f.rsplit("/", 1)[-1] in txt):
            hit.add(o)
    for a in builders(d):
        if a["name"] in txt:
            hit.add(a["id"])
    out = [a["id"] for a in builders(d) if a["id"] in hit]
    return out or [integrator(d)["id"]]


def pub_agent(a):
    return {k: a[k] for k in ("id", "color", "skill", "icon", "name", "role", "persona", "model", "discuss", "builds", "reviews")}


def pub_duo(d):
    d = norm_duo(d)
    q = queue(d, d["phase"])
    nxt = q[min(d.get("qi", 0), len(q) - 1)] if q else ""
    return {"id": str(d["_id"]), "pid": d["pid"], "title": d["title"], "goal": d["goal"], "agents": [pub_agent(a) for a in d["agents"]], "mode": d["mode"],
            "max_rounds": d["max_rounds"], "build_cycles": d["build_cycles"], "manual": d.get("manual", False), "parallel": d.get("parallel", True),
            "status": d["status"], "phase": d["phase"], "round": d["round"], "turns": d.get("turns", 0), "next": nxt, "cycle": d.get("cycle", 0),
            "decisions": d.get("decisions", []), "flags": d.get("flags", {}), "appr": d.get("appr", {}), "updated": C.iso(d["updated"])}


def pub_msg(m):
    return {"id": str(m["_id"]), "seq": m["seq"], "agent": m["agent"], "kind": m.get("kind", ""), "text": m["text"], "to": m.get("to", ""),
            "round": m.get("round", 0), "phase": m.get("phase", ""), "files": m.get("files", []), "trace": m.get("trace", []),
            "decs": m.get("decs", []), "dur": m.get("dur", 0), "chars": m.get("chars", 0), "agree": m.get("agree", False),
            "approve": m.get("approve", False), "t": C.iso(m["t"])}


def next_seq(did):
    d = db.duos.find_one_and_update({"_id": ObjectId(did)}, {"$inc": {"seqc": 1}}, return_document=ReturnDocument.AFTER)
    return d.get("seqc", 0) if d else 0


def add_msg(did, agent, kind, text, **extra):
    with LK:
        doc = {"did": did, "seq": next_seq(did), "agent": agent, "kind": kind, "text": text, "t": C.now(), **extra}
        doc["_id"] = db.duo_msgs.insert_one(doc).inserted_id
    m = pub_msg(doc)
    emit(did, t="msg", m=m)
    return m


def push(did):
    d = db.duos.find_one({"_id": ObjectId(did)})
    if d:
        emit(did, t="state", duo=pub_duo(d))


def heal(d):
    """اگه دیتابیس می‌گه running ولی ترد مرده (ری‌استارت سرور)، به paused تبدیل می‌شه تا قابل ادامه باشه"""
    if d["status"] == "running" and not alive(str(d["_id"])):
        db.duos.update_one({"_id": d["_id"]}, {"$set": {"status": "paused"}})
        d["status"] = "paused"
    return d


def duo_running(pid):
    return any(alive(str(d["_id"])) for d in db.duos.find({"pid": pid, "status": "running"}, {"_id": 1}))


def drop_project(pid):
    for d in list(db.duos.find({"pid": pid}, {"_id": 1})):
        did = str(d["_id"])
        if did in CTL:
            CTL[did]["stop"] = True
        db.duo_msgs.delete_many({"did": did})
        for m in (FEEDS, LIVE, OWN):
            m.pop(did, None)
    db.duos.delete_many({"pid": pid})


def add_decisions(did, who, texts, rnd):
    if not texts:
        return
    with LK:
        d = db.duos.find_one({"_id": ObjectId(did)})
        cur = d.get("decisions", [])
        seen = {re.sub(r"\W+", "", x["text"]).lower() for x in cur}
        for t in texts:
            k = re.sub(r"\W+", "", t).lower()
            if t and k not in seen and len(cur) < 40:
                seen.add(k)
                cur.append({"id": uuid.uuid4().hex[:8], "text": t, "by": who, "round": rnd, "pinned": False})
        db.duos.update_one({"_id": d["_id"]}, {"$set": {"decisions": cur}})
    push(did)


# ───────────────────────── پرامپت‌ها ─────────────────────────
def phase_text(d, ag, phase, review):
    if phase == "finalize":
        return "\nPHASE: FINALIZE. Turn the discussion into a precise written deliverable.\n" + C.TOOLS_DOC + "\n\n" + C.FILE_RULES
    if phase == "polish":
        return "\nPHASE: FINAL POLISH & DELIVERY. You are the integrator; the product must leave this phase flawless.\n" + C.TOOLS_DOC + "\n\n" + C.FILE_RULES
    if phase == "build":
        if review:
            return ("\nPHASE: BUILD — you are a REVIEWER (read-only: you cannot modify files, only inspect, run and report).\n"
                    "TOOLS: <ls/> <read path=\"a\" from=\"1\" to=\"200\"/> <grep>regex</grep> <run cmd=\"python main.py\"/> (python / pytest / node only). Emit tags, STOP, wait for results; never invent results.")
        return "\nPHASE: BUILD — you are a BUILDER. Plan in <think>…</think> first (<=100 words: files to touch and why), then use the tools.\n" + C.TOOLS_DOC + "\n\n" + C.FILE_RULES
    return "\nPHASE: DISCUSSION. No tools in this phase; think, debate and decide."


def sys_prompt(d, ag, phase, review, health=None):
    sk, a = SKILLS[ag["skill"]], A(d)
    roster = "; ".join(f"{x['name']} ({SKILLS[x['skill']]['en']}{' — you' if x['id'] == ag['id'] else ''})" for x in d["agents"])
    board = "\n".join(f"{i + 1}. {x['text']}" for i, x in enumerate(d.get("decisions", []))) or "(none yet)"
    extra = f"\n\nDIRECTOR'S EXTRA INSTRUCTIONS FOR YOU:\n{ag['persona']}" if ag.get("persona") else ""
    s = DUO_SYS.format(name=ag["name"], title=f"{ag['role']} / {sk['en']}", roster=roster, persona=sk["persona"], extra=extra,
                       goal=d["goal"], board=board, phase=phase_text(d, ag, phase, review))
    tree, body = C.project_context(d["pid"], 9000 if phase == "discuss" else None, d["goal"])
    s += f"\n\nPROJECT FILES (line counts; big files show an outline — read them by line ranges):\n{tree}"
    if body:
        s += f"\n\nFILE CONTENTS (small files, may be partial):\n{body}"
    if health:
        s += "\n\nAUTOMATED CHECKS RIGHT NOW (real problems found by the system — make sure they get fixed):\n- " + "\n- ".join(health)
    return s


def turn_prompt(d, ag, phase, review, blind=False):
    sk, a = SKILLS[ag["skill"]], A(d)
    others = ", ".join(x["name"] for x in d["agents"] if x["id"] != ag["id"])
    r = d["round"] + 1
    if phase == "finalize":
        return sk.get("final") or ("Consolidate everything agreed into SPEC.md with <write> (Goal, Scope, Architecture, Data model / APIs, Key decisions, Task breakdown, "
                                   "Acceptance criteria, Risks). If DESIGN.md exists read it and reference it. Then reply with a 3-line summary. Tag: [PLAN].")
    if phase == "polish":
        return ("FINAL INTEGRATION PASS. 1) <ls/> and read SPEC.md (+ DESIGN.md). 2) Read the files end to end (line ranges for big ones) and run the entrypoint/tests. "
                "3) Fix every remaining defect surgically: spec gaps, broken links/ids, leftover/dead code, missing empty/error/loading states, UI polish (spacing, RTL, dark/light, mobile). "
                "4) Make sure README.md exists (what it is, how to run, structure, env vars). 5) Finish with a [DELIVER] message in Persian: what was delivered, the file list, how to run and use it, and an honest list of known limitations. No tool tags in that final message.")
    if phase == "build":
        if review:
            return sk.get("review") or SKILLS["custom"]["review"]
        if d.get("cycle", 0) == 0:
            return sk.get("build") or SKILLS["custom"]["build"]
        return f"[Fix cycle {d['cycle'] + 1}/{d['build_cycles']}] " + (sk.get("fix") or SKILLS["custom"]["fix"]) + " Read the reviewers' latest messages first."
    task = sk["discuss1"] if r == 1 else sk["discuss2"]
    if blind:
        return task + f"\nYou are writing your independent first take before seeing {others}; do not reference them."
    s = f"Round {r}/{d['max_rounds']}. " + task + f"\nEngage with {others}'s latest messages."
    if r >= d["max_rounds"] - 1:
        s += " We are close to the round limit: converge, record final decisions and use <agree/> if the plan is complete."
    return s


def chat_msgs(d, me, system, prompt, budget=26000):
    did, a = str(d["_id"]), A(d)
    rows = list(db.duo_msgs.find({"did": did, "kind": {"$ne": "system"}}).sort("seq", -1).limit(60))
    keep, used = [], 0
    for i, r in enumerate(rows):                       # جدیدترین‌ها کامل، قدیمی‌ها خلاصه‌شده
        t = r["text"] if len(r["text"]) <= (7000 if i < 6 else 900) else r["text"][:(7000 if i < 6 else 900)] + " …(trimmed)"
        used += len(t)
        if used > budget and keep:
            break
        keep.append((r, t))
    keep.reverse()
    msgs = [{"role": "system", "content": system}]
    for r, t in keep:
        if r["agent"] == me:
            role, c = "assistant", t
        elif r["agent"] == "user":
            tgt = a[r["to"]]["name"] if r.get("to") in a else "everyone"
            role, c = "user", f"[DIRECTOR → {tgt}]: {t}"
        else:
            role, c = "user", f"[{(a.get(r['agent']) or {'name': 'ex-member'})['name']}]: {t}"
        if len(msgs) > 1 and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + c
        else:
            msgs.append({"role": role, "content": c})
    if len(msgs) > 1 and msgs[1]["role"] == "assistant":
        msgs.insert(1, {"role": "user", "content": "(discussion so far)"})
    if len(msgs) > 1 and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n\n" + prompt
    else:
        msgs.append({"role": "user", "content": prompt})
    return msgs


# ───────────────────────── یک نوبت ─────────────────────────
def take_turn(d, who, phase, ctl, blind=False):
    did, pid = str(d["_id"]), d["pid"]
    ag = A(d)[who]
    sk = SKILLS[ag["skill"]]
    review = phase == "build" and ag["reviews"] and not ag["builds"]
    tools_on = phase in ("finalize", "build", "polish")
    readonly = review
    health = None
    if tools_on:
        try:
            health = C.health(pid, None, cap=8)
        except Exception:
            log.exception("health")
        if not readonly:
            try:
                C.snap(pid, f"{ag['name']} · {phase}")
            except Exception:
                log.exception("snap")
    msgs = chat_msgs(d, who, sys_prompt(d, ag, phase, review, health), turn_prompt(d, ag, phase, review, blind))
    rnd = d["round"] + 1
    emit(did, t="start", agent=who, phase=phase, round=rnd)
    with LK:
        LIVE.setdefault(did, {})[who] = {"agent": who, "text": "", "phase": phase, "round": rnd}
    live = LIVE[did][who]
    t0 = time.time()
    steps = 16 if phase in ("build", "polish") else (5 if phase == "finalize" else 1)
    temp = min(sk["temp"], 0.3) if tools_on else sk["temp"]
    mtok = C.AI_MAX_TOKENS if tools_on else min(C.AI_MAX_TOKENS, 2400)
    model = ag["model"] or (DISCUSS_MODEL if phase == "discuss" else "") or None
    shown, raws, trace, changed = [], [], [], set()
    stop = lambda: ctl["stop"]
    try:
        for step in range(steps):
            if step:
                emit(did, t="delta", agent=who, x="\n\n")
                live["text"] += "\n\n"
            C.prune(msgs)
            full = ""
            for piece in C.stream_text(msgs, stop=stop, model=model, temperature=temp, max_tokens=mtok):
                full += piece
                live["text"] += piece
                emit(did, t="delta", agent=who, x=piece)
            if stop():
                return None
            raws.append(full)
            if not tools_on:
                shown.append(C.compact(full))
                break
            res, cut, evs = C.exec_tools(pid, full, changed, readonly=readonly)
            trunc = C.truncated(full)
            if trunc:
                res = (res + "\n\n" if res else "") + f"!! Your output hit the token limit while writing {trunc}; it was NOT saved. Redo it with <edit>/<replace>, or in smaller files (<250 lines each)."
            for e in evs:
                emit(did, t="tool", agent=who, kind=e["t"], **{k: v for k, v in e.items() if k not in ("t", "d")})
                if len(trace) < 24:
                    trace.append({"k": "file", "p": e["path"], "ok": e["ok"]} if e["t"] == "file" else {"k": "run", "p": e["name"], "x": e["x"][:600]} if e["t"] == "result" else {"k": "file", "p": e["n"] + " " + e["a"], "ok": True})
            shown.append(C.compact(full if trunc else (cut if res else full)))
            if res and step < steps - 1:
                msgs += [{"role": "assistant", "content": (full[:6000] if trunc else cut) or "(…)"},
                         {"role": "user", "content": "TOOL RESULTS:\n" + res + "\n\nContinue. When finished, give your final message (no tool tags)."}]
                continue
            break
        raw = "\n".join(raws)
        clean = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
        decs = [re.sub(r"\s+", " ", x).strip()[:300] for x in re.findall(r"<decision>(.*?)</decision>", clean, re.S)][:3]
        agree, approve = "<agree/>" in clean, "<approve/>" in clean
        text = "\n\n".join(s for s in shown if s)
        text = re.sub(r"<decision>.*?</decision>|<agree/>|<approve/>|<done/>", "", text, flags=re.S).strip()
        tags = KIND_ANY.findall(text)
        kind = (tags[-1] if tools_on else tags[0]).lower() if tags else ("review" if readonly else "deliver" if phase == "polish" else "build" if phase == "build" else "plan" if phase == "finalize" else "reply")
        text = re.sub(r"\n{3,}", "\n\n", KIND_LINE.sub("", text)).strip()
        if not text:
            text = "تغییرات اعمال شد." if changed else ""
        if not text and not decs:
            raise RuntimeError("ایجنت پاسخ خالی داد (مدل/کلید API یا محدودیت توکن رو بررسی کن)")
        add_msg(did, who, kind, text, phase=phase, round=rnd, files=sorted(changed), trace=trace, decs=decs,
                dur=round(time.time() - t0, 1), chars=len(raw), agree=agree, approve=approve)
        add_decisions(did, who, decs, rnd)
        return {"agree": agree, "approve": approve, "who": who}
    finally:
        with LK:
            (LIVE.get(did) or {}).pop(who, None)


def parallel_discuss(d, ids, ctl):
    """نظر اولیه‌ی همه‌ی متخصص‌ها هم‌زمان (مستقل از هم)؛ زمان = کندترین نفر، نه جمع همه"""
    out, errs = {}, []

    def work(i):
        try:
            out[i] = take_turn(d, i, "discuss", ctl, blind=True)
        except Exception as e:
            log.exception("parallel turn")
            errs.append(e)
            ctl["stop"] = True
    ts = [threading.Thread(target=work, args=(i,), daemon=True) for i in ids]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    if errs:
        raise errs[0]
    return [out.get(i) for i in ids]


def advance(d, results, phase, forced=False):
    """وضعیت بعدی را از نتیجه‌ی نوبت(ها) می‌سازد؛ (به‌روزرسانی‌ها، یادداشت سیستمی)"""
    s = {"turns": d.get("turns", 0) + len(results), "force": None}
    note = ""
    if forced:
        return s, note
    flags = dict(d.get("flags", {}))
    for r in results:
        flags[r["who"]] = r["agree"]
    s["flags"] = flags
    q = queue(d, phase)
    qi = d.get("qi", 0) + len(results)
    if phase == "discuss":
        s["round"] = d["round"]
        if qi >= len(q):
            qi, s["round"] = 0, d["round"] + 1
            both = all(flags.get(i) for i in q)
            if (both and s["round"] >= 2) or s["round"] >= d["max_rounds"]:
                note = "✅ همه‌ی متخصص‌ها به توافق رسیدن؛ می‌ریم سراغ جمع‌بندی." if both else "⏱ به سقف راندها رسیدیم؛ جمع‌بندی رو شروع می‌کنیم."
                s.update(phase="finalize", qi=0)
                s["next"] = queue({**d, **s}, "finalize")[0]
                return s, note
        s["qi"] = qi
    elif phase == "finalize":
        if qi >= len(q):
            if d["mode"] == "build":
                s.update(phase="build", qi=0, cycle=0, appr={}, fq=[])
                note = "📋 مستندات نهایی نوشته شد؛ مرحله‌ی ساخت و بازبینی شروع می‌شه."
            else:
                s.update(phase="done", qi=0)
                note = "🏁 برنامه‌ریزی تموم شد؛ SPEC.md (و در صورت وجود DESIGN.md) توی فایل‌های پروژه هست."
        else:
            s["qi"] = qi
    elif phase == "build":
        appr = dict(d.get("appr", {}))
        for r in results:
            if A(d)[r["who"]]["reviews"] and not A(d)[r["who"]]["builds"]:
                appr[r["who"]] = r["approve"]
        s["appr"] = appr
        if qi >= len(q):
            rv = [a["id"] for a in reviewers(d)]
            if not rv or all(appr.get(i) for i in rv):
                s.update(phase="polish", qi=0)
                note = "✅ بازبین‌ها تأیید کردن؛ صیقل و تحویل نهایی شروع می‌شه." if rv else "🧹 صیقل و تحویل نهایی شروع می‌شه."
            else:
                cyc = d.get("cycle", 0) + 1
                if cyc >= d["build_cycles"]:
                    s.update(phase="polish", qi=0, cycle=cyc)
                    note = "⏱ به سقف دورهای بازبینی رسیدیم؛ صیقل نهایی ایرادهای باقی‌مانده رو می‌بنده."
                else:
                    nd = {**d, "cycle": cyc}
                    s.update(cycle=cyc, qi=0, appr={}, fq=fix_queue(nd))
                    note = f"🔁 دور {cyc + 1} از {d['build_cycles']}: رفع ایرادهای بازبینی."
        else:
            s["qi"] = qi
    elif phase == "polish":
        s.update(phase="done", qi=0)
        note = "🏁 تحویل نهایی انجام شد."
    nd = {**d, **s}
    q2 = queue(nd, nd["phase"])
    s["next"] = q2[min(nd.get("qi", 0), len(q2) - 1)] if q2 else ""
    return s, note


# ───────────────────────── حلقه‌ی اصلی ─────────────────────────
DISCUSS_MODEL = ""


def notify(d, text):
    try:
        C.tg("sendMessage", chat_id=d["owner"], text=text)
    except Exception:
        pass


def run_loop(did):
    ctl, oid = CTL[did], ObjectId(did)

    def upd(**kw):
        db.duos.update_one({"_id": oid}, {"$set": {**kw, "updated": C.now()}})
        push(did)
    d = None
    try:
        while True:
            d = db.duos.find_one({"_id": oid})
            if not d:
                return
            d = norm_duo(d)
            if ctl["stop"]:
                upd(status="stopped")
                add_msg(did, "sys", "system", "⏹ توقف داده شد. هر وقت خواستی «ادامه» رو بزن.")
                return
            if d["phase"] == "done":
                break
            if ctl["pause"]:
                upd(status="paused")
                t0 = time.time()
                while ctl["pause"] and not ctl["stop"] and time.time() - t0 < 7200:
                    time.sleep(0.25)
                if ctl["pause"] and not ctl["stop"]:
                    return
                continue
            if d["status"] != "running":
                upd(status="running")
                d = norm_duo(db.duos.find_one({"_id": oid}))
            phase = d["phase"]
            q = queue(d, phase)
            forced = d.get("force") if d.get("force") in A(d) and phase != "done" else None
            blind = phase == "discuss" and d.get("parallel", True) and d["round"] == 0 and d.get("qi", 0) == 0 and len(q) >= 3 and not forced
            if blind:
                res = parallel_discuss(d, q, ctl)
                if any(r is None for r in res):
                    continue
                s, note = advance(d, res, phase)
            else:
                who = forced or q[min(d.get("qi", 0), len(q) - 1)]
                r = take_turn(d, who, phase, ctl)
                if r is None:
                    continue
                s, note = advance(d, [r], phase, forced=bool(forced))
            upd(**s)
            if note:
                add_msg(did, "sys", "system", note)
            if ctl["budget"] is not None:
                ctl["budget"] -= 1
                if ctl["budget"] <= 0:
                    ctl["pause"], ctl["budget"] = True, None
            elif d.get("manual"):
                ctl["pause"] = True
        upd(status="done", phase="done")
        last = db.duo_msgs.find_one({"did": did, "kind": "deliver"}, sort=[("seq", -1)])
        notify(d, f"✅ تیم «{d['title']}» کارش رو تحویل داد. {len(d.get('decisions', []))} تصمیم ثبت شد.\n" + ((last or {}).get("text", "")[:900]))
    except Exception as e:
        log.exception("duo loop")
        try:
            add_msg(did, "sys", "system", "⚠️ خطا: " + str(e)[:300])
            upd(status="error")
            if d:
                notify(d, f"⚠️ تیم «{d['title']}» با خطا متوقف شد: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        LIVE.pop(did, None)


def spawn(did):
    t = threading.Thread(target=run_loop, args=(did,), daemon=True, name="duo-" + did[-6:])
    THREADS[did] = t
    t.start()


# ───────────────────────── API ─────────────────────────
def register(app, db_, core):
    global db, C, DISCUSS_MODEL
    db, C = db_, core
    DISCUSS_MODEL = os.environ.get("AI_DISCUSS_MODEL", "").strip()
    for col, key in ((db.duos, "owner"), (db.duos, "pid"), (db.duo_msgs, [("did", 1), ("seq", 1)])):
        try:
            col.create_index(key)
        except Exception as e:
            log.warning("index: %s", e)
    core.BUSY_HOOKS.append(duo_running)
    core.CASCADE.append(drop_project)

    def route(path, methods):
        def deco(fn):
            app.add_url_rule(path, "duo_" + fn.__name__, core.authed(fn), methods=methods)
            return fn
        return deco

    def body():
        return request.get_json(silent=True) or {}

    @route("/api/duo/presets", ["GET"])
    def presets(uid):
        skills = [{"id": k, "fa": v["fa"], "en": v["en"], "icon": v["icon"], "name": v["name"], "short": v["short"], "discuss": v["discuss"],
                   "builds": v["builds"], "reviews": v["reviews"]} for k, v in SKILLS.items()]
        teams = [{"id": k, "label": v["label"], "hint": v["hint"], "mode": v["mode"], "skills": v["skills"]} for k, v in TEAMS.items()]
        return jsonify(skills=skills, teams=teams, max_agents=MAX_AGENTS)

    @route("/api/projects/<pid>/duos", ["GET"])
    def duo_list(uid, pid):
        if not core.proj(pid, uid):
            return jsonify(error="not found"), 404
        out = []
        for d in db.duos.find({"pid": pid, "owner": uid}).sort("updated", -1):
            d = heal(norm_duo(d))
            out.append({"id": str(d["_id"]), "title": d["title"], "goal": d["goal"][:140], "status": d["status"], "phase": d["phase"], "round": d["round"],
                        "max_rounds": d["max_rounds"], "mode": d["mode"], "turns": d.get("turns", 0), "decisions": len(d.get("decisions", [])),
                        "agents": [{"name": x["name"], "icon": x.get("icon", ""), "color": x["color"]} for x in d["agents"]], "updated": core.iso(d["updated"])})
        return jsonify(duos=out)

    @route("/api/projects/<pid>/duos", ["POST"])
    def duo_new(uid, pid):
        if not core.proj(pid, uid):
            return jsonify(error="not found"), 404
        b = body()
        goal = str(b.get("goal", "")).strip()[:4000]
        if len(goal) < 8:
            return jsonify(error="هدف پروژه رو کمی کامل‌تر بنویس"), 400
        if db.duos.count_documents({"owner": uid}) >= MAX_DUOS:
            return jsonify(error=f"حداکثر {MAX_DUOS} تیم"), 400
        agents = clean_agents(b.get("agents")) or clean_agents([{"skill": s} for s in TEAMS["build"]["skills"]])
        if sum(1 for a in agents if a["discuss"]) < 1:
            return jsonify(error="حداقل یک متخصص باید در بحث شرکت کنه"), 400
        mode = "build" if b.get("mode") == "build" else "plan"
        doc = {"owner": uid, "pid": pid, "title": (str(b.get("title", "")).strip() or goal.split("\n")[0])[:60], "goal": goal,
               "agents": agents, "mode": mode, "max_rounds": clamp(b.get("max_rounds"), 1, 24, 3),
               "build_cycles": clamp(b.get("build_cycles"), 1, 6, 3), "manual": bool(b.get("manual")), "parallel": bool(b.get("parallel", True)),
               "status": "idle", "phase": "discuss", "round": 0, "turns": 0, "qi": 0, "cycle": 0, "flags": {}, "appr": {}, "fq": [], "decisions": [],
               "seqc": 0, "created": core.now(), "updated": core.now()}
        return jsonify(id=str(db.duos.insert_one(doc).inserted_id))

    @route("/api/duos/<did>", ["GET"])
    def duo_get(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        OWN[did] = uid
        d = heal(d)
        seq = feed(did).seq()
        rows = list(db.duo_msgs.find({"did": did}).sort("seq", -1).limit(300))[::-1]
        return jsonify(duo=pub_duo(d), msgs=[pub_msg(m) for m in rows], seq=seq, live={k: dict(v) for k, v in (LIVE.get(did) or {}).items()})

    @route("/api/duos/<did>/poll", ["GET"])
    def duo_poll(uid, did):
        if OWN.get(did) != uid:
            if not get_duo(did, uid):
                return jsonify(error="not found"), 404
            OWN[did] = uid
        ev, seq = feed(did).since(clamp(request.args.get("after"), 0, 10 ** 9, 0))
        return jsonify(reset=True, seq=seq) if ev is None else jsonify(ev=ev, seq=seq)

    @route("/api/duos/<did>/ctl", ["POST"])
    def duo_ctl(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        a = body().get("action")
        st = CTL.setdefault(did, {"stop": False, "pause": False, "budget": None})
        if a in ("start", "resume", "step"):
            if d["phase"] == "done":
                return jsonify(error="کار این تیم تمام شده؛ یک پیام برای متخصص‌ها بفرست تا دوباره باز بشه"), 409
            if core.busy(d["pid"]) and not alive(did):
                return jsonify(error="ایجنت دیگه‌ای روی این پروژه مشغوله؛ صبر کن تموم بشه"), 409
            st["stop"], st["pause"], st["budget"] = False, False, (1 if a == "step" else None)
            if not alive(did):
                spawn(did)
            return jsonify(ok=True)
        if a == "pause":
            st["pause"] = True
            return jsonify(ok=True)
        if a == "stop":
            st["stop"], st["pause"] = True, False
            if not alive(did):
                db.duos.update_one({"_id": d["_id"]}, {"$set": {"status": "stopped"}})
                push(did)
            return jsonify(ok=True)
        return jsonify(error="action نامعتبر"), 400

    @route("/api/duos/<did>/say", ["POST"])
    def duo_say(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        b = body()
        text = str(b.get("text", "")).strip()[:2000]
        to = b.get("to") if b.get("to") in A(d) else "all"
        if not text:
            return jsonify(error="پیام خالیه"), 400
        upd = {"flags": {}, "updated": core.now()}
        reopened = d["phase"] == "done"
        if reopened:
            upd.update(phase="discuss", status="idle", qi=0, max_rounds=min(24, d["round"] + 2))
        if to != "all":
            upd["force"] = to                      # اون متخصص نوبت بعدی رو (خارج از نوبت) جواب می‌ده
        add_msg(did, "user", "user", text, to=to, round=d["round"], phase=d["phase"])
        db.duos.update_one({"_id": d["_id"]}, {"$set": upd})
        push(did)
        return jsonify(ok=True, reopened=reopened)

    @route("/api/duos/<did>", ["PATCH"])
    def duo_patch(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        b, s = body(), {"updated": core.now()}
        if "title" in b:
            s["title"] = str(b["title"]).strip()[:60] or d["title"]
        if "agents" in b:
            if alive(did) and d["status"] == "running":
                return jsonify(error="اول تیم رو مکث کن، بعد ترکیب متخصص‌ها رو عوض کن"), 409
            ag = clean_agents(b["agents"])
            if not ag:
                return jsonify(error="حداقل ۲ متخصص لازمه"), 400
            s["agents"], s["qi"], s["fq"], s["flags"], s["appr"] = ag, 0, [], {}, {}
        if "max_rounds" in b:
            s["max_rounds"] = clamp(b["max_rounds"], max(1, d["round"] + 1), 24, d["max_rounds"])
        if "build_cycles" in b:
            s["build_cycles"] = clamp(b["build_cycles"], 1, 6, d["build_cycles"])
        if "manual" in b:
            s["manual"] = bool(b["manual"])
        if "parallel" in b:
            s["parallel"] = bool(b["parallel"])
        db.duos.update_one({"_id": d["_id"]}, {"$set": s})
        push(did)
        return jsonify(ok=True)

    @route("/api/duos/<did>", ["DELETE"])
    def duo_del(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        if did in CTL:
            CTL[did]["stop"] = True
        db.duo_msgs.delete_many({"did": did})
        db.duos.delete_one({"_id": d["_id"]})
        for m in (FEEDS, LIVE, OWN):
            m.pop(did, None)
        return jsonify(ok=True)

    @route("/api/duos/<did>/decisions", ["POST"])
    def duo_decisions(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        b, cur = body(), d.get("decisions", [])
        a, i = b.get("action"), b.get("id")
        if a == "add":
            t = str(b.get("text", "")).strip()[:300]
            if t and len(cur) < 40:
                cur.append({"id": uuid.uuid4().hex[:8], "text": t, "by": "user", "round": d["round"], "pinned": True})
        elif a == "pin":
            for x in cur:
                if x["id"] == i:
                    x["pinned"] = not x.get("pinned")
        elif a == "del":
            cur = [x for x in cur if x["id"] != i]
        else:
            return jsonify(error="action نامعتبر"), 400
        db.duos.update_one({"_id": d["_id"]}, {"$set": {"decisions": cur}})
        push(did)
        return jsonify(ok=True)

    def transcript(d):
        did, ag = str(d["_id"]), A(d)
        L = [f"# {d['title']}", "", f"**Goal:** {d['goal']}", "", "## Decisions", ""]
        L += [f"{i + 1}. {x['text']}" + (" 📌" if x.get("pinned") else "") for i, x in enumerate(d.get("decisions", []))] or ["(none)"]
        L += ["", "## Transcript", ""]
        for m in db.duo_msgs.find({"did": did}).sort("seq", 1):
            if m["agent"] == "sys":
                L += [f"> {m['text']}", ""]
                continue
            a = ag.get(m["agent"])
            who = "Director" if m["agent"] == "user" else (f"{a['name']} ({a['role']})" if a else "ex-member")
            L += [f"### {who} · {m.get('kind', '')} · round {m.get('round', 0)}", "", m["text"], ""]
        return "\n".join(L)

    @route("/api/duos/<did>/export", ["GET"])
    def duo_export(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        return Response(transcript(d), mimetype="text/markdown; charset=utf-8")

    @route("/api/duos/<did>/publish", ["POST"])
    def duo_publish(uid, did):
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        dec = "# Decisions\n\n" + "\n".join(f"{i + 1}. {x['text']}" for i, x in enumerate(d.get("decisions", []))) + "\n"
        errs = [core.put_file(d["pid"], "docs/DECISIONS.md", dec), core.put_file(d["pid"], "docs/DUO_TRANSCRIPT.md", transcript(d))]
        return jsonify(ok=not any(errs), error=next((e for e in errs if e), None), files=["docs/DECISIONS.md", "docs/DUO_TRANSCRIPT.md"])

    @route("/api/duos/<did>/delivery", ["GET"])
    def duo_delivery(uid, did):
        """خلاصه‌ی تحویل: فایل‌های پروژه + سلامت فعلی + پیام تحویل نهایی"""
        d = get_duo(did, uid)
        if not d:
            return jsonify(error="not found"), 404
        last = db.duo_msgs.find_one({"did": did, "kind": "deliver"}, sort=[("seq", -1)])
        return jsonify(files=core.file_list(d["pid"]), issues=core.health(d["pid"], None, cap=12), report=(last or {}).get("text", ""))
