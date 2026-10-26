# -*- coding: utf-8 -*-
"""
CodeWise v2 — دستیار کدنویس هوشمند + «دوئل ایجنت» (ربات تلگرام + مینی‌اپ)

ساختار پروژه (کنار هم):
    app.py          بک‌اند اصلی + ربات تلگرام
    duo.py          موتور «تیم متخصص‌ها» (۲ تا ۶ ایجنت: ایده‌پرداز، طراح، معمار، برنامه‌نویس، تستر، منتقد، دلخواه)
    index.html      پوسته‌ی مینی‌اپ
    static/         app.css  app.js  duo.js

اجرا: gunicorn app:app --workers 1 --threads 16 --timeout 300
      (حتماً workers=1؛ کارهای ایجنت و دوئل توی حافظه‌ی همین پروسه اجرا می‌شن)  یا  python app.py

Environment الزامی:  MOTHER_TOKEN  BASE_URL  AI_BASE_URL  AI_API_KEY  AI_MODEL  ADMIN_IDS
اختیاری: MONGO_URI SECRET_KEY ADMIN_WEB_KEY ALLOWED_IDS AI_MAX_TOKENS MAX_STEPS RUN_TIMEOUT ALLOW_RUN CTX_CHARS READ_CAP AI_DISCUSS_MODEL

مدل با تگ‌های متنی ابزار صدا می‌زنه (<write> <edit> <replace> <insert> <read from/to> <ls> <grep> <run> <delete> <revert>) نه function-calling؛
پس روی هر API سازگار با OpenAI کار می‌کنه. حلقه: بنویس ← اجرا کن ← خطا رو ببین ← درست کن.
"""
import ast, fnmatch, difflib, uuid, os, re, json, time, hmac, hashlib, logging, threading, subprocess, tempfile, shutil, io, zipfile, shlex, sys, posixpath, functools
from urllib.parse import parse_qsl
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from flask import Flask, Response, g, jsonify, request
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId
from werkzeug.exceptions import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))


# ───────────────────────── تنظیمات و دیتابیس ─────────────────────────
def _int(n, d):
    try:
        return int(os.environ.get(n, d))
    except ValueError:
        return d


BOT_TOKEN = os.environ.get("MOTHER_TOKEN") or os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].rstrip("/")
AI_BASE_URL = re.sub(r"/chat/completions/?$", "", os.environ["AI_BASE_URL"].strip().rstrip("/"))
AI_API_KEY = os.environ["AI_API_KEY"]
AI_MODEL = os.environ["AI_MODEL"]
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
SECRET_KEY = os.environ.get("SECRET_KEY", BOT_TOKEN)
ADMIN_IDS = {int(x) for x in re.findall(r"\d+", os.environ.get("ADMIN_IDS", ""))}
ALLOWED = ADMIN_IDS | {int(x) for x in re.findall(r"\d+", os.environ.get("ALLOWED_IDS", ""))}
ADMIN_WEB_KEY = os.environ.get("ADMIN_WEB_KEY", "").strip()        # ورود از مرورگر برای تست (خالی = خاموش)
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 8000)
MAX_STEPS = _int("MAX_STEPS", 30)
RUN_TIMEOUT = _int("RUN_TIMEOUT", 20)
ALLOW_RUN = os.environ.get("ALLOW_RUN", "1") != "0"
CTX_CHARS = _int("CTX_CHARS", 30000)            # سقف محتوای فایل‌هایی که خودکار به مدل داده می‌شه
MAX_FILE, MAX_FILES, MAX_PROJECTS = 300_000, 200, 30
WEBHOOK_SECRET = hashlib.sha256(("cw" + SECRET_KEY).encode()).hexdigest()[:32]

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("codewise")
app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.json.ensure_ascii = False

# یک Session مشترک: اتصال‌ها دوباره استفاده می‌شن (سریع‌تر از requests.post جدا برای هر فراخوانی)
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=32))
SESSION.mount("http://", HTTPAdapter(pool_connections=8, pool_maxsize=32))

LOCK = threading.RLock()
BUSY_HOOKS, CASCADE = [], []      # duo.py خودش رو اینجا ثبت می‌کنه

if MONGO_URI:
    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000).get_database("codewise")
else:
    import mongomock
    db = mongomock.MongoClient().get_database("codewise")
    log.warning("MONGO_URI تنظیم نشده؛ داده‌ها موقتی‌ان و با ری‌استارت پاک می‌شن")
for col, key, kw in ((db.projects, "owner", {}), (db.files, [("pid", 1), ("path", 1)], {"unique": True}), (db.snaps, [("pid", 1), ("t", -1)], {}),
                     (db.chats, [("pid", 1), ("t", 1)], {})):
    try:
        col.create_index(key, **kw)
    except Exception as e:
        log.warning("index failed: %s", e)

if not ALLOWED:
    log.warning("ADMIN_IDS خالیه؛ هیچ‌کس اجازه‌ی استفاده نداره (برای جلوگیری از مصرف کلید API و اجرای کد)")


# ───────────────────────── احراز هویت مینی‌اپ ─────────────────────────
def verify_init_data(init_data):
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", None)
        if not got:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(key, check.encode(), hashlib.sha256).hexdigest(), got):
            return None
        if time.time() - int(pairs.get("auth_date", 0)) > 86400:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None


def request_user():
    u = verify_init_data(request.headers.get("X-Init-Data", ""))
    if u:
        return u
    k = request.headers.get("X-Admin-Key", "")
    if ADMIN_WEB_KEY and ADMIN_IDS and k and hmac.compare_digest(k.encode(), ADMIN_WEB_KEY.encode()):
        return {"id": min(ADMIN_IDS), "first_name": "Admin"}
    return None


def authed(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        u = request_user()
        if not u:
            return jsonify(error="unauthorized"), 401
        if u["id"] not in ALLOWED:
            return jsonify(error="دسترسی نداری"), 403
        g.user = u
        return fn(u["id"], *a, **k)
    return w


_rl = {}


def rate_ok(key, n, window):
    t = time.time()
    with LOCK:
        if len(_rl) > 2000:                                   # جلوگیری از رشد بی‌نهایت حافظه
            for k in [k for k, v in _rl.items() if not v or t - v[-1] > 300]:
                _rl.pop(k, None)
        q = [x for x in _rl.get(key, []) if t - x < window]
        ok = len(q) < n
        if ok:
            q.append(t)
        _rl[key] = q
        return ok


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO برای کلاینت؛ بدون مشکل tz-aware/naive"""
    return dt.replace(tzinfo=None).isoformat() + "Z"


# ───────────────────────── پروژه و فایل‌ها ─────────────────────────
def norm_path(p):
    p = posixpath.normpath(str(p or "").strip().replace("\\", "/")).lstrip("/")
    if not p or p == "." or p.startswith("..") or "/../" in p or len(p) > 120 or "\x00" in p:
        return None
    return p


def proj(pid, uid):
    try:
        return db.projects.find_one({"_id": ObjectId(pid), "owner": uid})
    except (InvalidId, TypeError):
        return None


def new_project(uid, name):
    if db.projects.count_documents({"owner": uid}) >= MAX_PROJECTS:
        return None
    r = db.projects.insert_one({"owner": uid, "name": (name or "پروژه‌ی جدید").strip()[:60], "created": now(), "updated": now()})
    return str(r.inserted_id)


def put_file(pid, path, content):
    path = norm_path(path)
    if not path:
        return "مسیر نامعتبر"
    content = str(content)
    if len(content) > MAX_FILE:
        return "فایل خیلی بزرگه"
    ex = db.files.find_one({"pid": pid, "path": path}, {"content": 1})
    if ex is None and db.files.count_documents({"pid": pid}) >= MAX_FILES:
        return "سقف تعداد فایل پر شده"
    upd = {"content": content, "updated": now()}
    if ex is not None and ex["content"] != content:
        upd["prev"] = ex["content"]                       # برای <revert> و بازگشت از ویرایش خراب
    db.files.update_one({"pid": pid, "path": path}, {"$set": upd}, upsert=True)
    db.projects.update_one({"_id": ObjectId(pid)}, {"$set": {"updated": now()}})
    return None


def file_list(pid):
    return [{"path": f["path"], "size": len(f["content"]), "lines": f["content"].count("\n") + 1} for f in db.files.find({"pid": pid}).sort("path", 1)]


def zip_bytes(pid):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in db.files.find({"pid": pid}):
            z.writestr(f["path"], f["content"])
    return buf.getvalue()


# ───────────────────────── اجرای کد (سندباکس سبک) ─────────────────────────
def run_cmd(pid, cmd):
    """اجرا در پوشه‌ی موقت، با محدودیت زمان/رم (روی لینوکس) و بدون متغیرهای محیطی حساس.
    توجه: این ایزولاسیون کامل نیست (شبکه بازه). برای ایزولاسیون واقعی داخل Docker اجرا کن."""
    if not ALLOW_RUN:
        return "اجرای کد خاموشه (ALLOW_RUN=0)"
    try:
        a = shlex.split(cmd)
    except ValueError:
        return "دستور نامعتبر"
    if not a or a[0] not in ("python", "python3", "pytest", "node"):
        return "فقط python / pytest / node مجازه"
    if a[0] in ("python", "python3"):
        a[0] = sys.executable
    elif a[0] == "pytest":
        a = [sys.executable, "-m", "pytest", "-x", "-q"] + a[1:]
    elif not shutil.which("node"):
        return "node روی سرور نصب نیست"
    d = tempfile.mkdtemp(prefix="cw_")
    try:
        for f in db.files.find({"pid": pid}):
            p = norm_path(f["path"])
            if p:
                fp = os.path.join(d, *p.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w", encoding="utf-8") as fh:
                    fh.write(f["content"])
        pre = None
        if os.name == "posix":
            import resource

            def pre():
                resource.setrlimit(resource.RLIMIT_CPU, (RUN_TIMEOUT, RUN_TIMEOUT))
                resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
                resource.setrlimit(resource.RLIMIT_FSIZE, (10 << 20, 10 << 20))
                os.setsid()
        env = {"PATH": os.environ.get("PATH", ""), "HOME": d, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run(a, cwd=d, capture_output=True, text=True, timeout=RUN_TIMEOUT, env=env, preexec_fn=pre)
        out = p.stdout + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return f"exit={p.returncode}\n{out[-4000:]}"
    except subprocess.TimeoutExpired:
        return f"زمان اجرا از {RUN_TIMEOUT} ثانیه گذشت (timeout)"
    except Exception as e:
        return f"خطای اجرا: {e}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ───────────────────────── مدل و ایجنت ─────────────────────────
MODES = {
    "write": "Mode: BUILD. Implement what the user asks, end to end, as working files in the project.",
    "debug": "Mode: DEBUG. Find the root cause first (read the code, run it, reproduce), then fix minimally and re-run to verify.",
    "explain": "Mode: EXPLAIN. Explain clearly and concretely with the project's real code; do not modify files unless asked.",
    "review": "Mode: REVIEW. Audit for bugs, security issues, edge cases and design problems; rank findings by severity (P0/P1/P2) with file:line and a concrete fix.",
    "optimize": "Mode: OPTIMIZE. Improve performance/readability without changing behavior; verify by running before and after when possible.",
    "idea": ("Mode: IDEATE. Act as an ideation & scenario strategist. Clarify the real user and job-to-be-done, then give exactly 3 distinct scenarios "
             "(safe / balanced / bold) each with concept, core flow, differentiator, risk and effort, a 1-5 scoring table, a clear recommendation, a signature 'wow' feature and a sharp MVP cut. "
             "Do not write code unless asked."),
    "design": ("Mode: DESIGN. Act as a senior UI/UX & graphic designer. Define or extend the visual system (palette as hex tokens with contrast >= 4.5:1, type scale, 4/8px spacing, radius, shadows, "
               "components with all states, RTL, dark+light, accessibility, motion with prefers-reduced-motion) and implement it precisely in the project's CSS/SVG/markup WITHOUT touching application logic. "
               "Reuse existing class names and ids; check the result against the real markup."),
}

TOOLS_DOC = """TOOLS — emit tags exactly as below, then STOP and wait; results come in the next message. Never invent tool results. You may emit SEVERAL tags in one turn (batch reads/edits to save time).
<ls/>                                       list files (line counts + outline of big files)
<read path="a/b.py"/>                       read a file (numbered lines)
<read path="a/b.py" from="120" to="220"/>   read only a line range (use this for big files)
<grep>regex</grep>   or   <grep in="app.js">regex</grep>      search; prints file:line: text
<edit path="a/b.py">
<old>exact existing snippet, 2-4 lines of context, must match exactly once</old>
<new>replacement</new>
</edit>                                     surgical change; repeat the <old>/<new> pair for several changes (all-or-nothing)
<replace path="a/b.py" lines="120-135">
new text that replaces exactly those lines
</replace>                                  line-range replace (read the range first!)
<insert path="a/b.py" after="120">
new lines
</insert>                                   insert after a line number (0 = top of file)
<write path="a/b.py">
FULL file content, no markdown fences
</write>                                    create a NEW file, or fully rewrite a SMALL one (<150 lines); always the COMPLETE file
<delete path="a/b.py"/>                     delete a file
<revert path="a/b.py"/>                     undo the last change made to that file
<run cmd="python main.py"/>                 run (python / pytest / node only; 20s limit; project files are the cwd)"""

FILE_RULES = """FILE SAFETY PROTOCOL (mandatory — this is what keeps big files from being damaged)
- The "  12| " prefixes in <read> output are display-only: never put them inside <old>, <new>, <replace>, <insert> or <write>.
- Never edit from memory. Before changing an existing file, <read> the exact region (use from/to; the PROJECT FILES outline shows where things are). Old tool outputs are condensed, so re-read when unsure.
- A <read> that ends with "[… continues …]" is PARTIAL: read the rest before judging or changing the file.
- Existing file over ~120 lines: change it ONLY with <edit>/<replace>/<insert> in small targeted steps. Never <write> it whole (such a write is refused when it shrinks the file a lot). Afterwards re-read the changed region to verify.
- Preserve everything you were not asked to change: no reformatting, renaming or removal of unrelated code; keep ids, class names, routes and function signatures that other files rely on.
- Batch independent actions in one turn. Lines starting with "!!" or "CHECK" in tool results are real problems (syntax, missing files, mismatched ids): fix them before anything else.
- Keep each file under ~300 lines; split into modules when it grows beyond that."""

SYSTEM = """You are CodeWise, a senior software engineer working inside the user's project workspace.
Reply in the user's language (Persian by default) but keep code, identifiers and comments in English unless asked otherwise.

{TOOLS}

{RULES}

WORKFLOW
1. Understand the request; if the project has files, read the relevant ones before editing (outline first, then the needed line ranges). Ask ONE short question only if truly blocked.
2. Make surgical changes that respect the existing architecture and style. Never truncate files or leave placeholders like "...rest of code".
3. After writing code, run it (or tests) when possible. If it fails, read the error, fix the root cause, run again.
4. Finish with a short summary: what changed (file names), how to run it, and any caveats. No tool tags in the final message.
5. For non-trivial tasks start with a 2-4 line plan. Python/JSON/JS/HTML/CSS files are checked automatically after each write; fix any reported problem immediately.
6. For web UIs build a self-contained index.html (CSS/JS can be separate files in the project); the user has a live Preview tab.
7. Never stop after announcing a next step ("now I will write X"): do it with a tool call in the same turn. When the task is completely finished, end your final message with <done/>.
8. Older turns are condensed to save context; never copy such placeholders into files — <read> the file again if you need its content.
REPLY FORMAT: clean Markdown. Short paragraphs; bullet lists for steps/options; `##` headings only for long answers; fenced code blocks always with a language tag; **bold** only for key terms; no filler or repetition; in Persian, keep technical terms and file names in English inside `backticks`.
Quality bar: correct, secure (validate input, no secrets in code), handle errors, simple over clever, polished UI (spacing, states, RTL, dark/light) when you build interfaces.""".replace("{TOOLS}", TOOLS_DOC).replace("{RULES}", FILE_RULES)


def _open(payload):
    """درخواست به مدل با retry روی خطاهای گذرا (429/5xx/قطعی شبکه) قبل از شروع استریم"""
    last = None
    for i in range(3):
        try:
            r = SESSION.post(f"{AI_BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {AI_API_KEY}"},
                             json=payload, timeout=(10, 300), stream=True)
        except requests.RequestException as e:
            last = e
        else:
            if r.status_code not in (429, 500, 502, 503, 504) or i == 2:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
            r.close()
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"اتصال به AI ناموفق بود: {last}")


def llm_stream(messages, model=None, temperature=0.2, max_tokens=None):
    r = _open({"model": model or AI_MODEL, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens or AI_MAX_TOKENS, "stream": True})
    try:
        if r.status_code >= 400:
            raise RuntimeError(f"AI HTTP {r.status_code}: {r.text[:300]}")
        if "event-stream" not in (r.headers.get("content-type") or "").lower():
            yield r.json()["choices"][0]["message"]["content"] or ""
            return
        for raw in r.iter_lines():
            line = raw.decode("utf-8", "ignore") if raw else ""
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                piece = (((json.loads(data).get("choices") or [{}])[0].get("delta")) or {}).get("content")
            except Exception:
                continue
            if piece:
                yield piece
    finally:
        r.close()


def stream_text(messages, stop=None, **kw):
    """llm_stream با تکه‌های تجمیع‌شده (حداقل ~۶۰ کاراکتر یا ۰.۱۲ ثانیه)؛ رویداد و ترافیک کمتر، حافظه‌ی کمتر"""
    buf, t0 = "", time.time()
    for piece in llm_stream(messages, **kw):
        buf += piece
        if len(buf) >= 60 or time.time() - t0 > 0.12:
            yield buf
            buf, t0 = "", time.time()
        if stop and stop():
            break
    if buf:
        yield buf


TOOL_RE = re.compile(
    r'<write\s+path="(?P<w>[^"]+)"(?P<wf>\s+force="1")?\s*>\n?(?P<wc>.*?)\n?</write>'
    r'|<edit\s+path="(?P<e>[^"]+)"\s*>(?P<eb>.*?)</edit>'
    r'|<replace\s+path="(?P<r>[^"]+)"\s+lines="(?P<rl>[\d\s,-]+)"\s*>\n?(?P<rc>.*?)\n?</replace>'
    r'|<insert\s+path="(?P<i>[^"]+)"\s+after="(?P<ia>\d+)"\s*>\n?(?P<ic>.*?)\n?</insert>'
    r'|<read\s+path="(?P<rd>[^"]+)"(?:\s+from="(?P<rf>\d+)")?(?:\s+to="(?P<rt>\d+)")?\s*/>'
    r'|<delete\s+path="(?P<d>[^"]+)"\s*/>'
    r'|<revert\s+path="(?P<v>[^"]+)"\s*/>'
    r'|<(?P<ls>ls)\s*/>'
    r'|<run\s+cmd="(?P<run>[^"]+)"\s*/>'
    r'|<grep(?:\s+in="(?P<gi>[^"]*)")?\s*>(?P<g>.*?)</grep>', re.S)
MOD_RE = re.compile(r'<(write|edit|replace|insert)\s+path="([^"]+)"[^>]*>')
READ_CAP = _int("READ_CAP", 24000)      # سقف کاراکتر هر <read>؛ بیشتر از این صفحه‌بندی می‌شه (نه بریده‌ی بی‌صدا)
BIG_FILE = 7000                          # فایل بزرگ‌تر از این به‌جای متن کامل، «نقشه‌ی فایل» می‌گیره


def strip_fence(c):
    m = re.fullmatch(r"\s*```[\w+-]*\n(.*?)\n?```\s*", c, re.S)
    return m.group(1) if m else c


# ───────────────────────── بررسی خودکار کد ─────────────────────────
_NODE = shutil.which("node")


def js_check(code, module=False):
    """syntax-check با node --check (اجرا نمی‌کنه، فقط پارس می‌کنه). (خط، پیام) یا None"""
    if not _NODE or not code.strip():
        return None
    d = tempfile.mkdtemp(prefix="cwj_")
    try:
        fp = os.path.join(d, "x.mjs" if module else "x.js")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(code)
        p = subprocess.run([_NODE, "--check", fp], capture_output=True, text=True, timeout=8)
        if p.returncode == 0:
            return None
        m = re.search(r"x\.m?js:(\d+)", p.stderr)
        msg = next((x for x in p.stderr.splitlines() if "Error" in x), p.stderr.strip()[:160])
        return int(m.group(1)) if m else 0, msg.strip()[:160]
    except Exception:
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _plain_markup(c):
    c = re.sub(r"<!--.*?-->", "", c, flags=re.S)
    return re.sub(r"<(script|style)\b.*?</\1>", "", c, flags=re.S | re.I)


def lint(path, c):
    """چک سریع بعد از هر نوشتن؛ خطا مستقیم به مدل برمی‌گرده تا همون لحظه درستش کنه"""
    low = path.lower()
    try:
        if low.endswith(".py"):
            ast.parse(c)
        elif low.endswith(".json"):
            json.loads(c)
        elif low.endswith((".js", ".mjs")):
            r = js_check(c, low.endswith(".mjs") or bool(re.search(r"^\s*(import|export)\s", c, re.M)))
            if r:
                return f"!! SYNTAX ERROR in {path} line {r[0]}: {r[1]} — fix it now"
        elif low.endswith((".html", ".htm")):
            for m in re.finditer(r"<script(?P<a>[^>]*)>(?P<b>.*?)</script>", c, re.S | re.I):
                a = m.group("a")
                if "src=" in a.lower() or re.search(r'type\s*=\s*["\'](?!module|text/javascript|application/javascript)', a, re.I):
                    continue
                r = js_check(m.group("b"), "module" in a.lower())
                if r:
                    return f"!! SYNTAX ERROR in inline <script> of {path} (html line ≈ {c[:m.start('b')].count(chr(10)) + r[0]}): {r[1]} — fix it now"
            if re.match(r"\s*<!doctype", c, re.I) and "</html>" not in c.lower():
                return f"!! {path} looks TRUNCATED (no </html>) — rewrite/repair the ending now"
            plain = _plain_markup(c)
            for tg in ("div", "section", "ul", "ol", "table", "main", "header", "nav", "form", "button", "select"):
                o, cl = len(re.findall(rf"<{tg}\b", plain, re.I)), len(re.findall(rf"</{tg}>", plain, re.I))
                if o != cl:
                    return f"!! UNBALANCED <{tg}> in {path}: {o} opened vs {cl} closed — fix it now"
        elif low.endswith(".css"):
            s = re.sub(r"/\*.*?\*/", "", c, flags=re.S)
            s = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", s)
            if s.count("{") != s.count("}"):
                return f"!! UNBALANCED braces in {path}: {{={s.count('{')} }}={s.count('}')} — fix it now"
    except SyntaxError as e:
        return f"!! SYNTAX ERROR in {path} line {e.lineno}: {e.msg} — fix it now"
    except ValueError as e:
        return f"!! INVALID JSON in {path}: {e} — fix it now"
    return ""


def health(pid, paths=None, lint_files=True, cap=10):
    """بررسی کل پروژه: سینتکس، فایل‌های لینک‌شده‌ی ناموجود، idهایی که JS دنبالشونه ولی توی HTML نیستن"""
    fs = {f["path"]: f["content"] for f in db.files.find({"pid": pid})}
    issues = []
    if lint_files:
        for p in sorted(paths or fs):
            e = lint(p, fs[p]) if p in fs else ""
            if e:
                issues.append(e.replace("!! ", "").replace(" — fix it now", ""))
    htmls = [p for p in fs if p.lower().endswith((".html", ".htm"))]
    for h in htmls:
        for ref in sorted(set(re.findall(r'(?:src|href)="([^"#?]+)"', re.sub(r"<!--.*?-->", "", fs[h], flags=re.S)))):
            if re.match(r"(?i)(?:[a-z][a-z0-9+.-]*:|//)", ref):
                continue
            cands = {norm_path(posixpath.join(posixpath.dirname(h), ref)), norm_path(ref)}
            if not cands & set(fs):
                issues.append(f"{h}: references '{ref}' but that file does not exist in the project")
    if htmls:
        have = set()
        for p, c in fs.items():
            have |= set(re.findall(r'\bid=\\?["\']([\w-]+)', c)) | set(re.findall(r'\.id\s*=\s*["\']([\w-]+)', c))
        for p, c in sorted(fs.items()):
            if not p.lower().endswith((".js", ".mjs", ".html", ".htm")) or (paths and p not in paths and not any(x.endswith((".html", ".htm")) for x in paths)):
                continue
            want = set(re.findall(r'getElementById\(\s*["\']([\w-]+)["\']', c)) | set(re.findall(r'\$\(\s*["\']([\w-]+)["\']\s*\)', c)) \
                | set(re.findall(r'querySelector\(\s*["\']#([\w-]+)["\']', c))
            miss = sorted(want - have)[:4]
            if miss and not re.search(r"\$\(\s*['\"][#.]", c):
                issues.append(f"{p}: looks up element id(s) {', '.join('#' + x for x in miss)} but no element with that id exists (typo / HTML-JS mismatch?)")
    return issues[:cap]


# ───────────────────────── نقشه‌ی فایل (برای فایل‌های بزرگ) ─────────────────────────
_JS_SYM = [re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)"),
           re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[\w$]+\s*=>)"),
           re.compile(r"^\s*(?:export\s+)?class\s+([\w$]+)")]
_SECTION = re.compile(r"^\s*(?:/\*+|//|#)\s*[-=─━*]{2,}\s*(.+?)\s*[-=─━*]*\s*(?:\*+/)?\s*$")


def outline(path, c, cap=45):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    items = []
    L = c.split("\n")
    if ext == "py":
        try:
            for n in ast.parse(c).body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    items.append((n.lineno, "def " + n.name))
                elif isinstance(n, ast.ClassDef):
                    items.append((n.lineno, "class " + n.name))
                    items += [(k.lineno, "  ." + k.name) for k in n.body if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))][:12]
        except SyntaxError:
            pass
    if ext in ("js", "mjs", "jsx", "ts", "tsx", "html", "htm", "css", "md"):
        for i, l in enumerate(L, 1):
            if len(l) > 300:
                continue
            m = _SECTION.match(l) if ext != "md" else None
            if m:
                items.append((i, "§ " + m.group(1)[:50]))
            elif ext == "md" and re.match(r"#{1,3}\s", l):
                items.append((i, l.strip()[:60]))
            elif ext == "css" and l.lstrip().startswith("@media"):
                items.append((i, l.strip()[:50]))
            elif ext in ("js", "mjs", "jsx", "ts", "tsx", "html", "htm"):
                for rx in _JS_SYM:
                    mm = rx.match(l)
                    if mm:
                        items.append((i, "fn " + mm.group(1) if "class" not in rx.pattern else "class " + mm.group(1)))
                        break
                else:
                    if ext in ("html", "htm"):
                        t = re.match(r'\s*<(header|nav|main|section|footer|aside|form|dialog|script|style)\b([^>]*)', l, re.I)
                        if t:
                            idm = re.search(r'id="([^"]+)"', t.group(2))
                            items.append((i, "<" + t.group(1).lower() + (" #" + idm.group(1) if idm else "") + ">"))
    items = sorted(set(items))
    out = [f"    L{n} {t}" for n, t in items[:cap]]
    if len(items) > cap:
        out.append(f"    …(+{len(items) - cap} more; use <grep> to find others)")
    return "\n".join(out)


def project_context(pid, limit=None, focus=""):
    """(درخت فایل‌ها با نقشه‌ی فایل‌های بزرگ، متن فایل‌های کوچک‌تر). فایل بزرگ هیچ‌وقت بی‌صدا حذف نمی‌شه؛ نقشه‌اش + دستور خوندن تکه‌ای می‌گیره"""
    fs = list(db.files.find({"pid": pid}))
    budget = limit or CTX_CHARS
    kw = set(re.findall(r"[\w\u0600-\u06FF]{3,}", (focus or "").lower()))
    fs.sort(key=lambda f: (-sum(1 for w in kw if w in f["path"].lower() or w in f["content"][:3000].lower()), -f["updated"].timestamp() if f.get("updated") else 0))
    inline = {}
    for f in fs:
        n = len(f["content"])
        if n <= BIG_FILE and n <= budget:
            budget -= n
            inline[f["path"]] = f["content"]
    lines = []
    for f in sorted(fs, key=lambda x: x["path"]):
        c, p = f["content"], f["path"]
        nl = c.count("\n") + 1
        note = "" if p in inline else (" — LARGE: not inlined; use the outline below and <read from/to>" if len(c) > BIG_FILE else " — not inlined (context budget); <read> it if needed")
        lines.append(f"- {p} ({nl} lines, {len(c)} chars){note}")
        if p not in inline and len(c) > BIG_FILE:
            o = outline(p, c)
            if o:
                lines.append(o)
    tree = "\n".join(lines) or "(empty project)"
    return tree, "\n\n".join(f"=== {p} ===\n{c}" for p, c in sorted(inline.items()))


# ───────────────────────── خواندن و ویرایش امن ─────────────────────────
_NUM = re.compile(r"^\s*\d+\s?[|│] ?")


def _strip_nums(s):
    ls = s.split("\n")
    if any(_NUM.match(x) for x in ls) and all(_NUM.match(x) or not x.strip() for x in ls):
        return "\n".join(_NUM.sub("", x, count=1) for x in ls)
    return s


def numbered(lines, a, b, path=None):
    s, n = max(1, a), len(lines)
    e, out, used, i = min(n, b), [], 0, max(1, a)
    while i <= e:
        ln = f"{i:>5}| {lines[i - 1][:3000]}" + (" ⟪line cut⟫" if len(lines[i - 1]) > 3000 else "")
        if used + len(ln) > READ_CAP and out:
            break
        out.append(ln)
        used += len(ln) + 1
        i += 1
    head = f"[lines {s}-{i - 1} of {n}]"
    if path and i <= e:
        head += f"\n(... PARTIAL: continue with <read path=\"{path}\" from=\"{i}\"/> )"
    return head + "\n" + "\n".join(out)


def _apply_pair(content, old, new):
    old = _strip_nums(old)
    if not old.strip():
        return None, "empty <old> snippet"
    n = content.count(old)
    if n == 1:
        return content.replace(old, new, 1), None
    if n > 1:
        where = ", ".join(str(content[:m.start()].count("\n") + 1) for m in list(re.finditer(re.escape(old), content))[:6])
        return None, f"<old> matched {n} times (lines {where}); add more surrounding lines so it matches exactly once"
    lines, ol = content.split("\n"), old.strip("\n").split("\n")
    key = [x.strip() for x in ol]
    hits = [i for i in range(len(lines) - len(ol) + 1) if lines[i].strip() == key[0] and all(lines[i + j].strip() == key[j] for j in range(1, len(ol)))]
    if len(hits) == 1:                                  # تطابق با تفاوت فاصله/ایندنت؛ ایندنت جدید هم هماهنگ می‌شه
        i = hits[0]
        fi, oi = re.match(r"\s*", lines[i]).group(0), re.match(r"\s*", ol[0]).group(0)
        nl = []
        for x in new.strip("\n").split("\n") if new.strip("\n") else []:
            nl.append((fi + x[len(oi):]) if fi != oi and x.startswith(oi) and x.strip() else x)
        lines[i:i + len(ol)] = nl
        return "\n".join(lines), None
    if len(hits) > 1:
        return None, f"<old> matches {len(hits)} places (ignoring whitespace); add more context lines"
    first = next((x for x in key if x), "")
    near = difflib.get_close_matches(first, [x.strip() for x in lines], n=1, cutoff=0.55) if first else []
    if near:
        i = next(k for k, x in enumerate(lines) if x.strip() == near[0])
        a, b = max(0, i - 2), min(len(lines), i + len(ol) + 2)
        return None, "<old> not found. Closest region:\n" + "\n".join(f"{k + 1:>5}| {lines[k][:200]}" for k in range(a, b)) + "\nCopy the snippet exactly from a fresh <read>, or use <replace lines=…>."
    return None, "<old> not found anywhere; <read> the file again (or <grep> for it) and copy the snippet exactly"


def _diff(old, new, cap=70):
    """(تعداد خط اضافه، حذف، متن diff کوتاه) برای نمایش در UI"""
    ol = (old or "").split("\n") if old is not None else []
    add = dele = 0
    out = []
    for l in difflib.unified_diff(ol, new.split("\n"), lineterm="", n=1):
        if l.startswith(("---", "+++")):
            continue
        if l.startswith("+"):
            add += 1
        elif l.startswith("-"):
            dele += 1
        if len(out) < cap:
            out.append(l[:240])
    return add, dele, "\n".join(out)


def _save(pid, path, content, changed, touched):
    p = norm_path(path)
    ex = db.files.find_one({"pid": pid, "path": p or ""}, {"content": 1}) if p else None
    err = put_file(pid, path, content)
    if err:
        return err, "", None
    changed.add(p)
    touched.add(p)
    return None, lint(p, content), _diff(ex["content"] if ex else None, content)


PLACEHOLDER = re.compile(r"(?:#|//|/\*|<!--)\s*(?:\.\.\.|…)|(?:\.\.\.|…)\s*(?:rest|remaining|existing|unchanged)\s+(?:of|code|content)|\brest of (?:the )?(?:file|code|function|class|script)\b|\b(?:existing|previous|unchanged) code (?:here|remains|stays)\b", re.I)


def write_guard(old, new, force):
    """جلوگیری از خراب شدن فایل: بازنویسی ناقص/کوتاه‌شده‌ی فایل موجود رد می‌شه"""
    if old is None or force:
        return ""
    if PLACEHOLDER.search(new) and not PLACEHOLDER.search(old):
        return "REFUSED: content contains a placeholder like '...rest of code'. Write the COMPLETE file, or change only what you need with <edit>/<replace>."
    if len(old) > 1500 and len(new) < len(old) * 0.55:
        return (f"REFUSED: new content is {len(new)} chars but the existing file has {len(old)} — it looks truncated. "
                "Change existing files with <edit>/<replace>/<insert>; add force=\"1\" to <write> only if you really intend to shrink it.")
    return ""


def truncated(full):
    """اگه خروجی وسط نوشتن فایل بریده شده، مسیر اون فایل رو برمی‌گردونه"""
    opened = MOD_RE.findall(full)
    closed = full.count("</write>") + full.count("</edit>") + full.count("</replace>") + full.count("</insert>")
    return opened[-1][1] if len(opened) > closed else None


def exec_tools(pid, text, changed, readonly=False):
    """ابزارهای داخل یک نوبت رو اجرا می‌کنه؛ (متن نتایج، متن بریده‌شده تا آخرین ابزار، لیست رویدادها)"""
    outs, evs, end, touched = [], [], 0, set()

    def ev_file(path, ok, n="edit", df=None):
        e = {"t": "file", "path": norm_path(path) or path, "ok": ok, "n": n}
        if df:
            e.update(add=df[0], dele=df[1], d=df[2])
        evs.append(e)

    for m in TOOL_RE.finditer(text):
        end = m.end()
        g = m.groupdict()
        if readonly and (g["w"] or g["e"] or g["r"] or g["i"] or g["d"] or g["v"]):
            r = "denied: your role is read-only. Describe the change you want in your message instead (file, line, exact fix)."
        elif g["w"]:
            p, body = norm_path(g["w"]), strip_fence(g["wc"])
            old = db.files.find_one({"pid": pid, "path": p or ""}, {"content": 1})
            err, bad, df = (write_guard(old["content"] if old else None, body, bool(g["wf"])) or None), "", None
            if not err:
                err, bad, df = _save(pid, g["w"], body, changed, touched)
            r = f"write {g['w']}: " + (err or f"ok ({len(body)} chars, {body.count(chr(10)) + 1} lines)") + (("\n" + bad) if bad else "")
            ev_file(g["w"], not err and not bad, "write", df)
        elif g["e"]:
            f = db.files.find_one({"pid": pid, "path": norm_path(g["e"]) or ""})
            pairs = re.findall(r"<old>\n?(.*?)\n?</old>\s*<new>\n?(.*?)\n?</new>", g["eb"], re.S)
            err = bad = ""
            df = None
            if not f:
                err = "file not found"
            elif not pairs:
                err = "no <old>…</old><new>…</new> pair found"
            else:
                c = f["content"]
                for k, (o, n) in enumerate(pairs, 1):
                    c2, e2 = _apply_pair(c, o, n)
                    if e2:
                        err = f"pair {k}/{len(pairs)} failed — {e2}\n(nothing was saved)"
                        break
                    c = c2
                if not err:
                    err, bad, df = _save(pid, g["e"], c, changed, touched)
                    err = err or ""
            r = f"edit {g['e']}: " + (err or f"ok ({len(pairs)} change{'s' if len(pairs) > 1 else ''})") + (("\n" + bad) if bad else "")
            ev_file(g["e"], not err and not bad, "edit", df)
        elif g["r"] or g["i"]:
            path, ins = (g["r"] or g["i"]), bool(g["i"])
            f = db.files.find_one({"pid": pid, "path": norm_path(path) or ""})
            err = bad = ""
            df = None
            lines = f["content"].split("\n") if f else []
            n, nums = len(lines), [int(x) for x in re.findall(r"\d+", g["rl"] or "")]
            new = _strip_nums(g["ic"] if ins else g["rc"])
            nl = new.split("\n") if new != "" else []
            if not f:
                err = "file not found"
            elif ins:
                a = int(g["ia"])
                if a > n:
                    err = f"file has only {n} lines"
                else:
                    lines[a:a] = nl
                    start = a + 1
            else:
                s, e = (nums + [None, None])[:2]
                e = e or s
                if not s or s < 1 or e < s or e > n:
                    err = f"invalid range {g['rl']} (file has {n} lines)"
                else:
                    lines[s - 1:e] = nl
                    start = s
            if not err:
                err, bad, df = _save(pid, path, "\n".join(lines), changed, touched)
                err = err or ""
            extra = ""
            if not err:
                a, b = max(1, start - 2), min(len(lines), start + len(nl) + 1)
                extra = f"\nnow ({len(lines)} lines total):\n" + "\n".join(f"{k:>5}| {lines[k - 1][:160]}" for k in range(a, min(b, a + 40) + 1))
            r = f"{'insert' if ins else 'replace'} {path}: " + (err or "ok") + extra + (("\n" + bad) if bad else "")
            ev_file(path, not err and not bad, "edit", df)
        elif g["rd"]:
            f = db.files.find_one({"pid": pid, "path": norm_path(g["rd"]) or ""})
            if not f:
                r = f"read {g['rd']}:\nفایل وجود نداره (file does not exist)"
            else:
                a, b = int(g["rf"] or 1), int(g["rt"] or 10 ** 9)
                r = f"read {g['rd']}:\n" + numbered(f["content"].split("\n"), a, b, g["rd"])
                evs.append({"t": "tool", "n": "read", "a": g["rd"] + (f":{a}-{b}" if g["rf"] or g["rt"] else ""), "ok": True})
        elif g["d"]:
            n = db.files.delete_one({"pid": pid, "path": norm_path(g["d"]) or ""}).deleted_count
            changed.discard(norm_path(g["d"]))
            r = f"delete {g['d']}: " + ("ok" if n else "not found")
            ev_file(g["d"], bool(n), "delete")
        elif g["v"]:
            f = db.files.find_one({"pid": pid, "path": norm_path(g["v"]) or ""})
            if not f or f.get("prev") is None:
                r = f"revert {g['v']}: nothing to revert"
            else:
                db.files.update_one({"_id": f["_id"]}, {"$set": {"content": f["prev"], "prev": f["content"], "updated": now()}})
                changed.add(f["path"])
                touched.add(f["path"])
                r = f"revert {g['v']}: ok (restored the previous version, {len(f['prev'])} chars)"
            ev_file(g["v"], True, "edit")
        elif g["ls"]:
            evs.append({"t": "tool", "n": "list", "a": ".", "ok": True})
            r = "files:\n" + ("\n".join(f"{x['path']} ({x['lines']} lines, {x['size']} chars)" for x in file_list(pid)) or "(empty)")
        elif g["run"]:
            r = f"run {g['run']}:\n" + run_cmd(pid, g["run"])
            evs.append({"t": "result", "name": "run " + g["run"], "x": r.split("\n", 1)[1][:3000]})
        else:
            try:
                rx, gi = re.compile(g["g"].strip()), (g["gi"] or "").strip()
                hits = [f"{f['path']}:{i}: {l.strip()[:160]}" for f in db.files.find({"pid": pid})
                        if not gi or fnmatch.fnmatch(f["path"], gi) or gi in f["path"]
                        for i, l in enumerate(f["content"].split("\n"), 1) if rx.search(l)]
                r = f"grep ({len(hits)} hits):\n" + ("\n".join(hits[:80]) or "no matches")
                evs.append({"t": "tool", "n": "grep", "a": g["g"].strip()[:60], "ok": True})
            except re.error as e:
                r = f"grep error: {e}"
        outs.append(r)
    if touched:                                      # اثر تغییرها روی بقیه‌ی پروژه (لینک شکسته، idهای ناهماهنگ…)
        iss = health(pid, touched, lint_files=False, cap=6)
        if iss:
            outs.append("CHECK (cross-file problems after your changes):\n- " + "\n- ".join(iss))
    return "\n\n".join(outs), text[:end], evs


def compact(text):
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).replace("<done/>", "")

    def chip(m):
        g = m.groupdict()
        if g["w"]:
            return f"\n`📝 {g['w']}`\n"
        if g["e"] or g["r"]:
            return f"\n`✏️ {g['e'] or g['r']}`\n"
        if g["i"]:
            return f"\n`➕ {g['i']}`\n"
        if g["run"]:
            return f"\n`▶ {g['run']}`\n"
        return ""
    t = TOOL_RE.sub(chip, t)
    t = re.sub(r'<(?:write|edit|replace|insert)\s+path="([^"]+)"[^>]*>.*$', lambda m: f"\n`⚠️ {m.group(1)} (ناقص ماند)`\n", t, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def prune(msgs, keep=6):
    """نتایج ابزار و بدنه‌ی فایل‌های نوشته‌شده‌ی نوبت‌های قدیمی رو کوتاه می‌کنه تا context منفجر نشه"""
    for m in msgs[1:-keep]:
        c = m["content"]
        if len(c) < 700:
            continue
        if m["role"] == "user" and c.startswith("TOOL RESULTS:"):
            m["content"] = c[:700] + "\n…(older output truncated — <read> again if you need it)"
        elif m["role"] == "assistant" and "<write" in c:
            c = re.sub(r'(<write\s+path="[^"]+"[^>]*>)(.*?)(</write>)', lambda x: f"{x.group(1)}(content saved earlier; use <read> to view){x.group(3)}", c, flags=re.S)
            m["content"] = c[:3000]


def snap(pid, label):
    fs = [{"p": f["path"], "c": f["content"]} for f in db.files.find({"pid": pid})]
    if sum(len(f["c"]) for f in fs) > 10_000_000:
        return None
    h = hashlib.sha1("\0".join(f"{f['p']}\0{f['c']}" for f in sorted(fs, key=lambda x: x["p"])).encode()).hexdigest()
    last = db.snaps.find_one({"pid": pid}, sort=[("t", -1)])
    if last and last.get("h") == h:        # بدون تغییر نسبت به نسخه‌ی قبل؛ تکراری نگیر
        return str(last["_id"])
    sid = str(db.snaps.insert_one({"pid": pid, "label": str(label)[:60], "files": fs, "h": h, "t": now()}).inserted_id)
    for old in list(db.snaps.find({"pid": pid}, {"_id": 1}).sort("t", -1).skip(25)):
        db.snaps.delete_one({"_id": old["_id"]})
    return sid


def agent(pid, text, mode, job=None):
    """مولد رویدادها: delta | turn | file | tool | result | final | error"""
    sid = snap(pid, text)
    rules = ((db.projects.find_one({"_id": ObjectId(pid)}) or {}).get("rules") or "").strip()
    rules_txt = f"\n\nPROJECT RULES (set by the user, always follow):\n{rules[:3000]}" if rules else ""
    db.chats.insert_one({"pid": pid, "role": "user", "content": text, "t": now()})
    tree, body = project_context(pid, None, text)
    hist = [{"role": h["role"], "content": h["content"][:4000]} for h in db.chats.find({"pid": pid}).sort("t", -1).limit(17)][::-1][:-1]
    msgs = [{"role": "system", "content": SYSTEM + "\n\n" + MODES.get(mode, MODES["write"]) + rules_txt + f"\n\nPROJECT FILES:\n{tree}\n\nFILE CONTENTS (may be partial; use <read> for others):\n{body}"}]
    msgs += hist + [{"role": "user", "content": text}]
    changed, shown = set(), []
    used, nudges = False, 0
    stop = lambda: bool(job and job["stop"])
    try:
        for step in range(MAX_STEPS):
            yield {"t": "turn", "n": step}
            prune(msgs)
            full = ""
            for piece in stream_text(msgs, stop=stop):
                full += piece
                yield {"t": "delta", "x": piece}
            if stop():
                shown += [compact(full), "⏹ متوقف شد"]
                break
            res, cut, evs = exec_tools(pid, full, changed)
            trunc = truncated(full)
            if trunc:    # خروجی به سقف توکن خورده و فایل ناقص مونده؛ به مدل می‌گیم کوچیک‌تر بنویسه
                res = (res + "\n\n" if res else "") + f"!! Your output hit the token limit while writing {trunc}; that file was NOT saved. Write it again in smaller pieces (several files/modules under ~250 lines each), then continue."
            shown.append(compact(full if trunc else (cut if res else full)))
            for e in evs:
                yield e
            if res:
                used = True
                msgs += [{"role": "assistant", "content": (full[:6000] if trunc else cut) or "(…)"},
                         {"role": "user", "content": "TOOL RESULTS:\n" + res + "\n\nContinue. If finished, give the final summary without tool tags and end with <done/>."}]
                continue
            t = full.strip()
            if "<done/>" in full or not used or nudges >= 2:
                break
            if len(t) < 500 or t.endswith((":", "：", "…", "...")):    # وسط کار ایستاده؛ هلش می‌دیم
                nudges += 1
                msgs += [{"role": "assistant", "content": full},
                         {"role": "user", "content": "You stopped without finishing. Do the next step NOW with a tool call; if everything is truly complete, reply with the final summary and <done/>."}]
                continue
            break
        else:
            shown.append("⚠️ به سقف مراحل رسیدم؛ بنویس «ادامه بده» تا ادامه بدم.")
        final = "\n\n".join(s for s in shown if s) or "(پاسخی تولید نشد)"
        db.chats.insert_one({"pid": pid, "role": "assistant", "content": final[:20000], "t": now()})
        yield {"t": "final", "text": final, "changed": sorted(changed), "files": file_list(pid), "snap": sid}
    except Exception as e:
        log.exception("agent error")
        yield {"t": "error", "x": str(e)[:300]}


# ───────────────────────── API مینی‌اپ ─────────────────────────
def asset_ver():
    ts = [os.path.getmtime(os.path.join(HERE, "index.html"))]
    sd = os.path.join(HERE, "static")
    if os.path.isdir(sd):
        ts += [os.path.getmtime(os.path.join(sd, f)) for f in os.listdir(sd)]
    return str(int(max(ts)))


@app.get("/")
def index():
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
        html = fh.read().replace("__V__", asset_ver())
    return html, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"}


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.after_request
def _sec(r):
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-store"
    elif request.path.startswith("/static/"):
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"     # با ?v= نسخه‌بندی می‌شه
    return r


@app.errorhandler(Exception)
def _err(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    log.exception("unhandled")
    return jsonify(error="خطای داخلی سرور"), 500


def pub(p):
    return {"id": str(p["_id"]), "name": p["name"], "updated": iso(p["updated"])}


@app.get("/api/me")
@authed
def api_me(uid):
    ps = [pub(p) for p in db.projects.find({"owner": uid}).sort("updated", -1)]
    if not ps:
        ps = [{"id": new_project(uid, "پروژه‌ی اول"), "name": "پروژه‌ی اول", "updated": iso(now())}]
    return jsonify(name=g.user.get("first_name", ""), projects=ps, modes=list(MODES), run=ALLOW_RUN, model=AI_MODEL)


@app.post("/api/projects")
@authed
def api_new(uid):
    pid = new_project(uid, (request.get_json(silent=True) or {}).get("name"))
    return (jsonify(id=pid), 200) if pid else (jsonify(error=f"حداکثر {MAX_PROJECTS} پروژه"), 400)


@app.patch("/api/projects/<pid>")
@authed
def api_rename(uid, pid):
    p = proj(pid, uid)
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:60]
    if not p or not name:
        return jsonify(error="not found / نام خالیه"), 404
    db.projects.update_one({"_id": p["_id"]}, {"$set": {"name": name}})
    return jsonify(ok=True, name=name)


@app.delete("/api/projects/<pid>")
@authed
def api_del(uid, pid):
    p = proj(pid, uid)
    if not p:
        return jsonify(error="not found"), 404
    for c in (db.files, db.chats, db.snaps):
        c.delete_many({"pid": pid})
    for fn in CASCADE:
        try:
            fn(pid)
        except Exception:
            log.exception("cascade")
    db.projects.delete_one({"_id": p["_id"]})
    return jsonify(ok=True)


@app.get("/api/projects/<pid>")
@authed
def api_get(uid, pid):
    p = proj(pid, uid)
    if not p:
        return jsonify(error="not found"), 404
    chat = [{"role": c["role"], "content": c["content"]} for c in db.chats.find({"pid": pid}).sort("t", -1).limit(40)][::-1]
    return jsonify(name=p["name"], files=file_list(pid), chat=chat, rules=p.get("rules", ""), job=live_job(pid), busy=busy(pid))


@app.route("/api/projects/<pid>/file", methods=["GET", "PUT", "DELETE"])
@authed
def api_file(uid, pid):
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    path = norm_path(request.args.get("path"))
    if not path:
        return jsonify(error="مسیر نامعتبر"), 400
    if request.method == "GET":
        f = db.files.find_one({"pid": pid, "path": path})
        return jsonify(content=f["content"]) if f else (jsonify(error="not found"), 404)
    if request.method == "DELETE":
        db.files.delete_one({"pid": pid, "path": path})
        return jsonify(ok=True)
    err = put_file(pid, path, (request.get_json(silent=True) or {}).get("content", ""))
    return (jsonify(error=err), 400) if err else jsonify(ok=True)


@app.post("/api/projects/<pid>/import")
@authed
def api_import(uid, pid):
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    bad = [f.get("path") for f in (request.get_json(silent=True) or {}).get("files", [])[:MAX_FILES] if put_file(pid, f.get("path"), f.get("content", ""))]
    return jsonify(ok=True, skipped=bad)


@app.post("/api/projects/<pid>/run")
@authed
def api_run(uid, pid):
    if not proj(pid, uid) or not rate_ok(f"run{uid}", 10, 60):
        return jsonify(error="not found / کمی صبر کن"), 404
    return jsonify(out=run_cmd(pid, str((request.get_json(silent=True) or {}).get("cmd", ""))))


@app.post("/api/projects/<pid>/clear")
@authed
def api_clear(uid, pid):
    if proj(pid, uid):
        db.chats.delete_many({"pid": pid})
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/sendzip")
@authed
def api_sendzip(uid, pid):
    p = proj(pid, uid)
    if not p:
        return jsonify(error="not found"), 404
    send_zip(uid, pid, p["name"])
    return jsonify(ok=True)


@app.get("/api/projects/<pid>/zip")
@authed
def api_zip(uid, pid):
    p = proj(pid, uid)
    if not p:
        return jsonify(error="not found"), 404
    return Response(zip_bytes(pid), mimetype="application/zip", headers={"Content-Disposition": "attachment; filename=project.zip"})


@app.put("/api/projects/<pid>/rules")
@authed
def api_rules(uid, pid):
    p = proj(pid, uid)
    if not p:
        return jsonify(error="not found"), 404
    db.projects.update_one({"_id": p["_id"]}, {"$set": {"rules": str((request.get_json(silent=True) or {}).get("rules", ""))[:3000]}})
    return jsonify(ok=True)


@app.get("/api/projects/<pid>/snaps")
@authed
def api_snaps(uid, pid):
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    return jsonify(snaps=[{"id": str(s["_id"]), "label": s["label"], "t": iso(s["t"]), "n": len(s["files"])}
                          for s in db.snaps.find({"pid": pid}).sort("t", -1).limit(25)])


@app.post("/api/projects/<pid>/restore")
@authed
def api_restore(uid, pid):
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    if busy(pid):
        return jsonify(error="ایجنت روی این پروژه مشغوله"), 409
    try:
        s = db.snaps.find_one({"_id": ObjectId((request.get_json(silent=True) or {}).get("id")), "pid": pid})
    except (InvalidId, TypeError):
        s = None
    if not s:
        return jsonify(error="نسخه پیدا نشد"), 404
    snap(pid, "قبل از بازگردانی")
    db.files.delete_many({"pid": pid})
    for f in s["files"]:
        put_file(pid, f["p"], f["c"])
    return jsonify(ok=True, files=file_list(pid))


@app.get("/api/projects/<pid>/preview")
@authed
def api_preview(uid, pid):
    """index.html پروژه با CSS/JS لینک‌شده‌ی داخل پروژه، یکپارچه برای iframe"""
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    fs = {f["path"]: f["content"] for f in db.files.find({"pid": pid})}
    page = fs.get("index.html") or next((v for k, v in sorted(fs.items()) if k.endswith(".html")), None)
    if page is None:
        return jsonify(error="هنوز فایل index.html نداری؛ از ایجنت بخواه یه صفحه بسازه"), 404

    def css(m):
        p = norm_path(m.group(1))
        return "<style>" + fs[p].replace("</", "<\\/") + "</style>" if p in fs else m.group(0)
    page = re.sub(r'<link[^>]*?href="([^"]+\.css)"[^>]*>', css, page)

    def js(m):
        p = norm_path(m.group(2))
        return "<script" + m.group(1) + m.group(3) + ">" + fs[p].replace("</", "<\\/") + "</script>" if p in fs else m.group(0)
    page = re.sub(r'<script([^>]*?)src="([^"]+\.js)"([^>]*)></script>', js, page)
    return jsonify(html=page)


JOBS, ACTIVE = {}, {}


def live_job(pid):
    j = JOBS.get(ACTIVE.get(pid))
    return ACTIVE[pid] if j and not j["done"] else None


def busy(pid):
    """آیا الان چیزی (ایجنت تکی یا دوئل) داره روی فایل‌های این پروژه کار می‌کنه؟"""
    return bool(live_job(pid)) or any(h(pid) for h in BUSY_HOOKS)


@app.post("/api/projects/<pid>/chat")
@authed
def api_chat(uid, pid):
    """کار ایجنت توی ترد پس‌زمینه اجرا می‌شه (مستقل از اتصال مرورگر)؛ کلاینت با /api/jobs/<id> پیشرفت رو می‌گیره"""
    if not proj(pid, uid):
        return jsonify(error="not found"), 404
    b = request.get_json(silent=True) or {}
    text = str(b.get("text") or "").strip()[:12000]
    if not text:
        return jsonify(error="پیام خالیه"), 400
    if busy(pid):
        return jsonify(error="ایجنت (یا دوئل) هنوز روی این پروژه مشغوله", job=live_job(pid)), 409
    if not rate_ok(f"chat{uid}", 20, 60):
        return jsonify(error="کمی صبر کن"), 429
    mode = b.get("mode") if b.get("mode") in MODES else "write"
    with LOCK:
        for k in [k for k, v in JOBS.items() if v["done"] and time.time() - v["t"] > 3600]:
            JOBS.pop(k, None)
        jid = uuid.uuid4().hex
        j = {"uid": uid, "pid": pid, "ev": [], "done": False, "stop": False, "t": time.time()}
        JOBS[jid], ACTIVE[pid] = j, jid

    def run():
        try:
            for ev in agent(pid, text, mode, j):
                j["ev"].append(ev)
        except Exception as e:
            log.exception("job error")
            j["ev"].append({"t": "error", "x": str(e)[:300]})
        finally:
            j["done"], j["t"] = True, time.time()
    threading.Thread(target=run, daemon=True, name="job").start()
    return jsonify(job=jid)


@app.get("/api/jobs/<jid>")
@authed
def api_job(uid, jid):
    j = JOBS.get(jid)
    if not j or j["uid"] != uid:
        return jsonify(error="کار پیدا نشد (شاید سرور ری‌استارت شده)"), 404
    try:
        a = max(0, int(request.args.get("after", 0)))
    except ValueError:
        a = 0
    return jsonify(ev=j["ev"][a:], n=len(j["ev"]), done=j["done"])


@app.post("/api/jobs/<jid>/stop")
@authed
def api_job_stop(uid, jid):
    j = JOBS.get(jid)
    if j and j["uid"] == uid:
        j["stop"] = True
    return jsonify(ok=True)


# ───────────────────────── ربات تلگرام ─────────────────────────
def tg(method, **data):
    try:
        return SESSION.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=data, timeout=20).json()
    except Exception as e:
        log.warning("tg %s: %s", method, e)
        return {"ok": False}


def md2tg(t):
    """مارک‌داون مدل → HTML تلگرام (بولد، کد، بلاک کد، تیتر، لیست، لینک)"""
    esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = []
    for p in re.split(r"(```[^\n]*\n.*?```)", t, flags=re.S):
        m = re.fullmatch(r"```([^\n]*)\n(.*?)```", p, re.S)
        if m:
            lang = re.sub(r"[^\w+#-]", "", m.group(1))
            cls = ' class="language-' + lang + '"' if lang else ""
            out.append("<pre><code" + cls + ">" + esc(m.group(2).rstrip()) + "</code></pre>")
            continue
        p = esc(p)
        p = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", p)
        p = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", p)
        p = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", p, flags=re.M)
        p = re.sub(r"^\s*[-*•]\s+", "• ", p, flags=re.M)
        p = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', p)
        out.append(p)
    return "".join(out)


def tg_chunks(text, n=3300):
    """تکه‌کردن امن: بلوک‌های کد بلند با حفظ فنس تکه می‌شن، پیام وسط تگ نمی‌بُره"""
    pieces = []
    for seg in re.split(r"(```[^\n]*\n.*?```)", text, flags=re.S):
        if not seg.strip():
            continue
        code = seg.startswith("```")
        head = seg.split("\n", 1)[0] if code else ""
        body = seg[len(head) + 1:].rsplit("```", 1)[0] if code else seg
        lines = []
        for ln in body.split("\n"):
            lines += [ln[i:i + 1000] for i in range(0, len(ln), 1000)] or [""]
        buf = ""
        for ln in lines:
            if buf and len(buf) + len(ln) + 1 > n - 10:
                pieces.append((code, head, buf))
                buf = ""
            buf += ln + "\n"
        if buf.strip():
            pieces.append((code, head, buf))
    chunks, cur = [], ""
    for code, head, b in pieces:
        s = (head + "\n" + b.rstrip("\n") + "\n```") if code else b
        if cur and len(cur) + len(s) > n:
            chunks.append(cur)
            cur = ""
        cur += s
    if cur.strip():
        chunks.append(cur)
    return chunks


def send_long(chat, text):
    for ch in tg_chunks(text) or [text]:
        r = tg("sendMessage", chat_id=chat, text=md2tg(ch), parse_mode="HTML", disable_web_page_preview=True)
        if not r.get("ok"):                       # اگه HTML خراب شد، متن ساده بفرست
            tg("sendMessage", chat_id=chat, text=ch[:4000])


def send_zip(chat, pid, name):
    try:
        SESSION.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", data={"chat_id": chat},
                     files={"document": (re.sub(r"\W+", "_", name) + ".zip", zip_bytes(pid))}, timeout=60)
    except Exception as e:
        log.warning("send_zip: %s", e)


def active_pid(uid):
    u = db.users.find_one({"_id": uid}) or {}
    if u.get("active") and proj(u["active"], uid):
        return u["active"]
    pid = new_project(uid, "تلگرام")
    if pid:
        db.users.update_one({"_id": uid}, {"$set": {"active": pid}}, upsert=True)
    return pid


def handle_msg(msg):
    uid, text = msg["from"]["id"], (msg.get("text") or "").strip()
    if uid not in ALLOWED:
        return tg("sendMessage", chat_id=uid, text="دسترسی نداری.")
    if text.startswith("/start"):
        return tg("sendMessage", chat_id=uid, text="سلام! من CodeWise هستم، دستیار کدنویس تو.\nمینی‌اپ رو باز کن (بخش «ایجنت‌ها» = دوئل دو ایجنت)، یا همین‌جا پیام بده تا روی پروژه‌ی فعال کار کنم.\n/new نام — پروژه‌ی جدید\n/zip — دریافت فایل‌ها\n/clear — پاک کردن گفتگو",
                  reply_markup={"inline_keyboard": [[{"text": "باز کردن کدنویس", "web_app": {"url": BASE_URL}}]]})
    pid = active_pid(uid)
    if not pid:
        return tg("sendMessage", chat_id=uid, text=f"حداکثر {MAX_PROJECTS} پروژه داری.")
    if text.startswith("/new"):
        pid = new_project(uid, text[4:].strip() or "پروژه‌ی جدید")
        db.users.update_one({"_id": uid}, {"$set": {"active": pid}}, upsert=True)
        return tg("sendMessage", chat_id=uid, text="پروژه‌ی جدید ساخته شد و فعاله ✅")
    if text.startswith("/zip"):
        return send_zip(uid, pid, (proj(pid, uid) or {}).get("name", "project"))
    if text.startswith("/clear"):
        db.chats.delete_many({"pid": pid})
        return tg("sendMessage", chat_id=uid, text="گفتگو پاک شد.")
    if not text or text.startswith("/") or not rate_ok(f"chat{uid}", 20, 60):
        return
    if busy(pid):
        return tg("sendMessage", chat_id=uid, text="⏳ یه ایجنت (یا دوئل) هنوز روی این پروژه مشغوله؛ کمی بعد دوباره بفرست.")
    st = (tg("sendMessage", chat_id=uid, text="⏳ شروع کردم…").get("result") or {}).get("message_id")
    steps, last = [], 0.0
    for ev in agent(pid, text, "write"):
        if ev["t"] == "file":
            steps.append(("📝 " if ev.get("ok", True) else "⚠️ ") + ev["path"])
        elif ev["t"] == "result":
            steps.append("▶ " + ev["name"][:60])
        if st and steps and time.time() - last > 3:
            tg("editMessageText", chat_id=uid, message_id=st, text="⏳ در حال کار…\n" + "\n".join(steps[-8:]))
            tg("sendChatAction", chat_id=uid, action="typing")
            last = time.time()
        if ev["t"] == "final":
            if st:
                tg("deleteMessage", chat_id=uid, message_id=st)
            send_long(uid, ev["text"] + (("\n\n📁 فایل‌های تغییرکرده: " + "، ".join(ev["changed"])) if ev["changed"] else ""))
        elif ev["t"] == "error":
            tg("sendMessage", chat_id=uid, text="⚠️ خطا: " + ev["x"])


@app.post("/mother")
def hook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return "forbidden", 403
    msg = (request.get_json(silent=True) or {}).get("message")
    if msg and msg.get("chat", {}).get("type") == "private" and (msg.get("from") or {}).get("id"):
        threading.Thread(target=lambda: handle_msg(msg), daemon=True).start()   # تلگرام منتظر جواب طولانی نمی‌مونه
    return "ok"


def setup_bot():
    r = tg("setWebhook", url=f"{BASE_URL}/mother", secret_token=WEBHOOK_SECRET, allowed_updates=["message"])
    tg("setChatMenuButton", menu_button={"type": "web_app", "text": "کدنویس", "web_app": {"url": BASE_URL}})
    tg("setMyCommands", commands=[{"command": "start", "description": "شروع"}, {"command": "new", "description": "پروژه‌ی جدید"},
                                  {"command": "zip", "description": "دریافت فایل‌ها"}, {"command": "clear", "description": "پاک کردن گفتگو"}])
    log.info("webhook: %s", r)


import duo  # noqa: E402  (موتور دو‌ایجنت؛ بعد از تعریف توابع هسته)
duo.register(app, db, sys.modules[__name__])
setup_bot()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
