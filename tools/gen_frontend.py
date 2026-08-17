"""
gen_frontend.py — Generate a real single-page frontend from a domain, wired to the
SAME generated REST contract as the backend (one source of truth).

For each domain entity it emits list / create / edit / delete views that call the
exact routes gen_models.py generates (`GET/POST /{plural}`, `GET/PUT/DELETE
/{plural}/{id_}`), plus a register/login flow against /auth/*. The session token
from /auth/login is sent as the `X-Session` header on every call — the same header
the generated `current_user_id` dependency reads. Owner-scoped entities omit the
`user_id` field from forms because the server forces ownership.

The generated app embeds a machine-readable ENDPOINTS metadata so verification can
assert that every call the frontend makes resolves to a real mounted backend route.

Usage:
    python tools/gen_frontend.py <domain> <out_dir>     # writes <out_dir>/index.html
"""
from __future__ import annotations
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

# field type -> HTML input kind
_INPUT = {"int": "number", "float": "number", "bool": "checkbox",
          "datetime": "datetime-local", "str": "text", "text": "textarea", "json": "textarea"}
_SKIP_WRITE = {"id", "created_at", "updated_at"}


def _plural(name: str) -> str:
    import gen_models as GM
    return GM._plural(name)


def entity_specs(entities, eps) -> list[dict]:
    """Per-entity metadata the frontend renders from (same source as the backend)."""
    specs = []
    for e in entities:
        name = e["name"]
        pol = eps.get(name, {}) or {}
        owner = pol.get("owner_field")
        plural = _plural(name)
        fields = []
        for f in e["fields"]:
            fields.append({"name": f["name"], "type": f["type"], "optional": f["optional"],
                           "input": _INPUT.get(f["type"], "text"),
                           "encrypted": f["name"] in set(pol.get("encrypted_fields") or [])})
        writable = [f for f in fields
                    if f["name"] not in _SKIP_WRITE and not (owner and f["name"] == owner)]
        specs.append({"name": name, "plural": plural, "owner": owner,
                      "requires_auth": bool(pol.get("requires_auth") or owner),
                      "fields": fields, "writable": writable})
    return specs


def frontend_endpoints(specs) -> list[dict]:
    """The exact (method, path_template) set the frontend calls — for contract
    verification against the backend's mounted routes."""
    eps = [
        {"method": "POST", "path": "/auth/register"},
        {"method": "POST", "path": "/auth/login"},
        {"method": "POST", "path": "/auth/logout"},
        {"method": "GET", "path": "/auth/me"},
    ]
    for s in specs:
        p = s["plural"]
        eps += [
            {"method": "GET", "path": f"/{p}"},
            {"method": "POST", "path": f"/{p}"},
            {"method": "GET", "path": f"/{p}/{{id_}}"},
            {"method": "PUT", "path": f"/{p}/{{id_}}"},
            {"method": "DELETE", "path": f"/{p}/{{id_}}"},
        ]
    return eps


# Curated accent pairs that hold up on the dark ground (no reds — red reads as
# destructive in buttons). A domain gets a stable pick by name hash, or declares
# its own: domain.json {"brand": {"accent": "#hex", "accent2": "#hex", "tagline": "..."}}
PALETTES = [
    ("#5b7cfa", "#22d3ee"),   # indigo / cyan
    ("#34d399", "#a3e635"),   # emerald / lime
    ("#f59e0b", "#fb923c"),   # amber / orange
    ("#e879f9", "#a78bfa"),   # fuchsia / violet
    ("#38bdf8", "#60a5fa"),   # sky / blue
    ("#2dd4bf", "#34d399"),   # teal / emerald
    ("#fb7185", "#f472b6"),   # rose / pink
    ("#c084fc", "#818cf8"),   # purple / indigo
]

def _brand(domain_name: str, brand: dict | None) -> dict:
    import hashlib
    brand = brand or {}
    idx = int(hashlib.md5(domain_name.encode()).hexdigest(), 16) % len(PALETTES)
    acc, acc2 = brand.get("accent") or PALETTES[idx][0], brand.get("accent2") or PALETTES[idx][1]
    r, g, b = (int(acc.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    return {"acc": acc, "acc2": acc2, "accrgb": f"{r},{g},{b}",
            "tagline": brand.get("tagline") or "Every record. One dashboard. Status at a glance."}

def gen_index_html(domain_name: str, label: str, specs: list[dict],
                   brand: dict | None = None, home: dict | None = None,
                   artifacts: list | None = None) -> str:
    endpoints = frontend_endpoints(specs)
    cfg = json.dumps({"domain": domain_name, "label": label,
                      "entities": specs, "endpoints": endpoints,
                      "home": home, "artifacts": artifacts or []}, indent=2)
    bb = _brand(domain_name, brand)
    # This is a generated standalone app served by uvicorn; localStorage is the
    # intended place for its session token.
    return (_TEMPLATE.replace("__LABEL__", label).replace("/*__CONFIG__*/ {}", cfg)
            .replace("__ACC2__", bb["acc2"]).replace("__ACCRGB__", bb["accrgb"])
            .replace("__ACC__", bb["acc"]).replace("__TAGLINE__", bb["tagline"]))


def gen_frontend_files(domain_name: str, label: str, specs: list[dict],
                       brand: dict | None = None, home: dict | None = None,
                       artifacts: list | None = None) -> dict:
    """Split the SPA into CSP-compliant files. The backend serves
    `Content-Security-Policy: default-src 'self'`, which forbids inline
    <style>/<script> — a single-file inline SPA renders as a BLANK PAGE in a
    real browser (2026-08-16 campaign finding; every HTTP-level check passed
    because nothing executed JS). External same-origin files are allowed, so:
    index.html links styles.css + app.js. The inline JSON config block stays —
    type="application/json" is data, not an executed script, and CSP permits it.
    """
    html = gen_index_html(domain_name, label, specs, brand, home, artifacts)
    s0 = html.index("<style>")
    s1 = html.index("</style>")
    css = html[s0 + len("<style>"):s1].strip("\n")
    m0 = html.index('<script type="module">')
    m1 = html.rindex("</script>")
    js = html[m0 + len('<script type="module">'):m1].strip("\n")
    index = (html[:s0] + '<link rel="stylesheet" href="styles.css"/>' + html[s1 + len("</style>"):m0]
             + '<script type="module" src="app.js"></script>' + html[m1 + len("</script>"):])
    bb = _brand(domain_name, brand)
    favicon = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
               '<rect width="16" height="16" rx="3" fill="' + bb["acc"] + '"/>'
               '<text x="8" y="12" text-anchor="middle" font-size="10" fill="#fff" '
               'font-family="sans-serif">' + (label[:1].upper() or "A") + "</text></svg>\n")
    return {"index.html": index, "styles.css": css, "app.js": js, "favicon.svg": favicon}


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="icon" href="favicon.svg" type="image/svg+xml"/>
<title>__LABEL__</title>
<style>
  :root {
    --bg:#0b0e14; --panel:#12161f; --elev:#1a2029; --line:#232a38;
    --fg:#e8ecf4; --mut:#93a0b4; --acc:__ACC__; --acc2:__ACC2__; --accrgb:__ACCRGB__;
    --ok:#34d399; --warn:#fbbf24; --bad:#f87171;
    --r-lg:10px; --r-xl:14px;
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body { margin:0; font:15.5px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--fg); -webkit-font-smoothing:antialiased; }
  h1,h2,h3 { margin:0; letter-spacing:-.01em; }
  a { color:var(--acc); text-decoration:none; }

  /* spacing utilities (generous scale) */
  .p-4{padding:16px}.p-6{padding:24px}.p-8{padding:32px}
  .px-4{padding-left:16px;padding-right:16px}.px-6{padding-left:24px;padding-right:24px}
  .py-4{padding-top:16px;padding-bottom:16px}.py-6{padding-top:24px;padding-bottom:24px}
  .mt-4{margin-top:16px}.mt-6{margin-top:24px}.mb-4{margin-bottom:16px}.mb-6{margin-bottom:24px}
  .gap-4{gap:16px}.gap-6{gap:24px}
  .rounded-lg{border-radius:var(--r-lg)}.rounded-xl{border-radius:var(--r-xl)}.rounded-full{border-radius:999px}
  .row{display:flex;align-items:center}.grow{flex:1}
  .muted{color:var(--mut)}.hidden{display:none !important}
  .w-auto{width:auto}.m-0{margin:0}

  /* header */
  .topbar { position:sticky; top:0; z-index:30; display:flex; align-items:center; gap:14px;
            padding:12px 22px; background:rgba(18,22,31,.92); backdrop-filter:blur(8px);
            border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:center; gap:10px; font-weight:700; font-size:16px; }
  .brand-mark { width:26px; height:26px; border-radius:8px; flex:none;
                background:linear-gradient(135deg,var(--acc),var(--acc2)); }
  .userchip { margin-left:auto; display:flex; align-items:center; gap:10px; color:var(--mut); font-size:13.5px; }
  .avatar { width:30px; height:30px; border-radius:999px; background:var(--acc); color:#fff;
            display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }

  /* buttons */
  .btn { font:inherit; font-size:14.5px; font-weight:600; cursor:pointer; border:1px solid var(--line);
         background:var(--elev); color:var(--fg); border-radius:var(--r-lg); padding:9px 16px;
         transition:transform .12s ease, filter .15s ease, border-color .15s ease, box-shadow .15s ease; }
  .btn:hover { filter:brightness(1.12); border-color:#31405a; }
  .btn:active { transform:translateY(1px); }
  .btn:focus-visible { outline:2px solid var(--acc); outline-offset:2px; }
  .btn-primary { background:var(--acc); border-color:var(--acc); color:#fff;
                 box-shadow:0 4px 14px rgba(var(--accrgb),.28); }
  .btn-primary:hover { filter:brightness(1.08); box-shadow:0 6px 20px rgba(var(--accrgb),.38); }
  .btn-ghost { background:transparent; }
  .btn-danger { background:transparent; color:var(--bad); border-color:#3d2a33; }
  .btn-danger:hover { border-color:var(--bad); }
  .btn .spinner { display:inline-block; width:14px; height:14px; margin-right:8px; vertical-align:-2px;
                  border:2px solid rgba(255,255,255,.35); border-top-color:#fff; border-radius:999px;
                  animation:spin .7s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }

  /* auth screen */
  .auth-wrap { display:flex; min-height:calc(100vh - 55px); align-items:stretch; }
  .hero { flex:1.15; display:flex; flex-direction:column; justify-content:center; padding:56px;
          background:linear-gradient(145deg,rgba(var(--accrgb),.16),rgba(var(--accrgb),.05) 55%,transparent);
          border-right:1px solid var(--line); }
  .hero h2 { font-size:34px; line-height:1.15; max-width:440px; }
  .hero p.lead { color:var(--mut); max-width:430px; font-size:16px; }
  .feature { display:flex; align-items:flex-start; gap:12px; color:var(--mut); font-size:14.5px; max-width:430px; }
  .feature .dot { width:8px; height:8px; margin-top:7px; flex:none; border-radius:999px;
                  background:linear-gradient(135deg,var(--acc),var(--acc2)); }
  .auth-side { flex:1; display:flex; align-items:center; justify-content:center; padding:32px; }
  .card { background:var(--panel); border:1px solid var(--line); box-shadow:0 10px 30px rgba(0,0,0,.35); }
  .auth-card { width:100%; max-width:400px; }
  label { display:block; margin:14px 0 6px; color:var(--mut); font-size:13px; font-weight:600;
          text-transform:uppercase; letter-spacing:.05em; }
  input,textarea,select { width:100%; background:var(--bg); color:var(--fg); font:inherit;
          border:1px solid var(--line); border-radius:var(--r-lg); padding:10px 12px;
          transition:border-color .15s ease, box-shadow .15s ease; }
  input:focus,textarea:focus,select:focus { outline:none; border-color:var(--acc);
          box-shadow:0 0 0 3px rgba(var(--accrgb),.18); }
  textarea { min-height:76px; resize:vertical; }
  .error { color:var(--bad); font-size:14px; margin:10px 0 0; }

  /* badges / pills */
  .badge { font-size:12px; font-weight:600; color:var(--mut); border:1px solid var(--line);
           border-radius:999px; padding:3px 10px; white-space:nowrap; }
  .pill { display:inline-block; font-size:12px; font-weight:600; border-radius:999px; padding:3px 10px;
          border:1px solid var(--line); color:var(--mut); white-space:nowrap; }
  .pill.status-ok { color:var(--ok); border-color:rgba(52,211,153,.4); }
  .pill.status-warn { color:var(--warn); border-color:rgba(251,191,36,.4); }
  .pill.status-bad { color:var(--bad); border-color:rgba(248,113,113,.4); }
  .lock { color:var(--ok); font-size:11px; font-weight:600; }

  /* app shell */
  .shell { display:flex; min-height:calc(100vh - 55px); }
  .sidenav { width:224px; flex:none; padding:18px 14px; border-right:1px solid var(--line); }
  .sidenav a { display:flex; align-items:center; gap:10px; padding:9px 12px; margin-bottom:2px;
               border-radius:var(--r-lg); color:var(--mut); font-weight:600; font-size:14.5px;
               cursor:pointer; transition:background .15s ease, color .15s ease; }
  .sidenav a:hover { background:var(--elev); color:var(--fg); }
  .sidenav a.active { background:var(--elev); color:var(--fg); box-shadow:inset 2px 0 0 var(--acc); }
  .sidenav .navdot { width:7px; height:7px; border-radius:999px; background:var(--line); flex:none;
                     transition:background .15s ease; }
  .sidenav a.active .navdot, .sidenav a:hover .navdot { background:var(--acc); }
  main { flex:1; padding:28px; max-width:1120px; }
  .pagehead { display:flex; align-items:center; gap:14px; margin-bottom:24px; flex-wrap:wrap; }
  .pagehead h2 { font-size:24px; }

  /* dashboard */
  .statgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); }
  .stat { position:relative; overflow:hidden; }
  .stat .n { font-size:30px; font-weight:750; letter-spacing:-.02em; }
  .stat .l { color:var(--mut); font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:.06em; }
  .stat .accent { position:absolute; inset:0 auto 0 0; width:3px;
                  background:linear-gradient(180deg,var(--acc),var(--acc2)); }

  /* tables */
  .table-wrap { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; color:var(--mut); font-weight:600; font-size:12.5px; text-transform:uppercase;
       letter-spacing:.05em; padding:10px 12px; border-bottom:1px solid var(--line); }
  td { padding:11px 12px; border-bottom:1px solid var(--line); vertical-align:middle; }
  tbody tr { transition:background .12s ease; }
  tbody tr:hover { background:var(--elev); }

  /* skeleton loading */
  .skeleton { height:14px; border-radius:6px; background:var(--elev); position:relative; overflow:hidden; }
  .skeleton::after { content:""; position:absolute; inset:0;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,.06),transparent);
    animation:shimmer 1.2s infinite; }
  @keyframes shimmer { from { transform:translateX(-100%);} to { transform:translateX(100%);} }

  /* empty state */
  .empty { text-align:center; padding:44px 20px; color:var(--mut); }
  .empty .glyph { width:44px; height:44px; margin:0 auto 14px; border-radius:12px; opacity:.85;
                  background:linear-gradient(135deg,var(--acc),var(--acc2)); }

  /* drawer form */
  .overlay { position:fixed; inset:0; background:rgba(4,6,10,.55); z-index:40;
             opacity:0; pointer-events:none; transition:opacity .2s ease; }
  .overlay.open { opacity:1; pointer-events:auto; }
  .drawer { position:fixed; top:0; right:0; bottom:0; width:min(430px,94vw); z-index:50;
            background:var(--panel); border-left:1px solid var(--line);
            transform:translateX(102%); transition:transform .22s ease; overflow-y:auto; }
  .drawer.open { transform:translateX(0); }

  /* toasts */
  .toasts { position:fixed; right:18px; bottom:18px; z-index:60; display:flex;
            flex-direction:column; gap:10px; }
  .toast { background:var(--elev); border:1px solid var(--line); border-left:3px solid var(--acc);
           border-radius:var(--r-lg); padding:12px 16px; font-size:14px; max-width:340px;
           box-shadow:0 8px 24px rgba(0,0,0,.4); animation:slidein .18s ease; }
  .toast.error { border-left-color:var(--bad); }
  .toast.ok { border-left-color:var(--ok); }
  @keyframes slidein { from { transform:translateY(8px); opacity:0; } to { transform:none; opacity:1; } }


  /* declarative home-view widgets */
  .homegrid { display:grid; grid-template-columns:repeat(2,1fr); }
  .w-wide { grid-column:1/-1; }
  .cd-tiles { display:flex; gap:16px; flex-wrap:wrap; }
  .cd { min-width:132px; padding:14px 18px; border:1px solid var(--line); border-radius:var(--r-lg); }
  .cd .n { font-size:30px; font-weight:750; letter-spacing:-.02em; }
  .cd.ok .n { color:var(--ok); } .cd.warn .n { color:var(--warn); } .cd.bad .n { color:var(--bad); }
  .cd .l { color:var(--mut); font-size:12px; }
  .money-n { font-size:32px; font-weight:750; letter-spacing:-.02em; }
  .kanban { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(150px,1fr); gap:12px; overflow-x:auto; }
  .kcol { background:var(--bg); border:1px solid var(--line); border-radius:var(--r-lg); padding:10px; }
  .kcol h4 { margin:0 0 8px; font-size:11.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); }
  .kcard { background:var(--elev); border:1px solid var(--line); border-radius:8px; padding:8px 10px;
           margin-bottom:8px; font-size:13px; transition:border-color .15s ease; }
  .kcard:hover { border-color:var(--acc); }
  .pair { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px; }
  .pair h4 { grid-column:1/-1; margin:0; font-size:12.5px; text-transform:uppercase;
             letter-spacing:.06em; color:var(--mut); }
  .pcell { background:var(--bg); border:1px solid var(--line); border-radius:var(--r-lg); padding:12px; font-size:13.5px; }
  .pcell .ph { font-size:11px; text-transform:uppercase; color:var(--mut); letter-spacing:.06em; margin-bottom:6px; }
  .pcell .meta { color:var(--mut); font-size:12px; margin-top:6px; }
  .bar-row { margin-bottom:12px; font-size:13px; }
  .bar-head { display:flex; justify-content:space-between; color:var(--mut); margin-bottom:5px; }
  .bar-track { height:10px; background:var(--bg); border-radius:999px; overflow:hidden; border:1px solid var(--line); }
  .bar-fill { height:100%; border-radius:999px; background:var(--acc); transition:width .4s ease; }
  .bar-fill.ok { background:var(--ok); } .bar-fill.warn { background:var(--warn); } .bar-fill.bad { background:var(--bad); }
  .tl-item { display:flex; gap:12px; padding:10px 0; border-bottom:1px solid var(--line); font-size:13.5px; }
  .tl-item:last-child { border-bottom:none; }
  .tl-dot { width:8px; height:8px; margin-top:7px; border-radius:999px; background:var(--acc); flex:none; }
  .tl-when { color:var(--mut); font-size:12px; }
  @media (max-width:920px) {
    .hero { display:none; }
    .shell { flex-direction:column; }
    .sidenav { width:100%; display:flex; flex-wrap:wrap; gap:4px; border-right:none;
               border-bottom:1px solid var(--line); padding:10px 14px; }
    .sidenav a { margin-bottom:0; }
    main { padding:18px; }
    .homegrid { grid-template-columns:1fr; }
    .pair { grid-template-columns:1fr; }
  }
</style>
</head>
<body>
<div id="app"></div>
<div class="toasts" id="toasts"></div>
<script type="application/json" id="cfg">/*__CONFIG__*/ {}</script>
<script type="module">
const CFG = JSON.parse(document.getElementById("cfg").textContent);
const $ = (h) => { const t=document.createElement("template"); t.innerHTML=h.trim(); return t.content.firstChild; };
const esc = (v) => v==null ? "" : String(v).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const Session = {
  get token(){ return localStorage.getItem("sy_session"); },
  set token(v){ v ? localStorage.setItem("sy_session",v) : localStorage.removeItem("sy_session"); },
  get email(){ return localStorage.getItem("sy_email"); },
  set email(v){ v ? localStorage.setItem("sy_email",v) : localStorage.removeItem("sy_email"); },
};

async function api(method, path, body){
  const headers = {"Content-Type":"application/json"};
  if (Session.token) headers["X-Session"] = Session.token;
  const res = await fetch(path, {method, headers, body: body!=null ? JSON.stringify(body) : undefined});
  const text = await res.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw Object.assign(new Error(fmtErr(data) || res.statusText), {status:res.status, data});
  return data;
}
function fmtErr(d){
  if (!d) return "";
  if (typeof d.detail === "string") return d.detail;
  if (Array.isArray(d.detail)) return d.detail.map(e=>`${(e.loc||[]).slice(1).join(".")}: ${e.msg}`).join("; ");
  return "";
}

function toast(msg, kind){
  const t = $(`<div class="toast ${kind||""}">${esc(msg)}</div>`);
  document.getElementById("toasts").appendChild(t);
  setTimeout(()=>t.remove(), 4200);
}

// --- auth ---
async function register(email, pw){ return api("POST","/auth/register",{email,password:pw}); }
async function login(email, pw){
  const r = await api("POST","/auth/login",{email,password:pw});
  Session.token = r.session; Session.email = email; return r;
}
async function logout(){ try{ if(Session.token) await api("POST","/auth/logout?session="+encodeURIComponent(Session.token)); }catch{} Session.token=null; Session.email=null; }

// --- status pill coloring (state-machine values → semantic tone) ---
const OK_STATES = ["active","available","done","succeeded","concluded","approved","completed","returned","open","won","verified","published"];
const BAD_STATES = ["failed","broken","banned","cancelled","denied","expired","abandoned","returned_damaged","lost","rejected","suspended"];
function pillFor(v){
  const s = String(v||"").toLowerCase();
  if (OK_STATES.includes(s)) return "status-ok";
  if (BAD_STATES.includes(s)) return "status-bad";
  return "status-warn";
}
function isStatusField(name){ return name === "status" || name === "state"; }

// --- typed form IO ---
function readForm(spec, form){
  const out = {};
  for (const f of spec.writable){
    const el = form.querySelector(`[name="${f.name}"]`);
    if (!el) continue;
    let v;
    if (f.type==="bool") v = el.checked;
    else if (el.value==="" ) { v = null; }
    else if (f.type==="int") v = parseInt(el.value,10);
    else if (f.type==="float") v = parseFloat(el.value);
    else if (f.type==="json") { try{ v = JSON.parse(el.value); }catch{ throw new Error(`${f.name}: invalid JSON`); } }
    else if (f.type==="datetime") v = new Date(el.value).toISOString();
    else v = el.value;
    if (v!==null && v!==undefined) out[f.name]=v;
  }
  return out;
}
function fillForm(spec, form, row){
  for (const f of spec.writable){
    const el = form.querySelector(`[name="${f.name}"]`);
    if (!el || row[f.name]==null) continue;
    if (f.type==="bool") el.checked = !!row[f.name];
    else if (f.type==="json") el.value = JSON.stringify(row[f.name]);
    else if (f.type==="datetime") el.value = String(row[f.name]).slice(0,16);
    else el.value = row[f.name];
  }
}

// --- chrome ---
function topbar(){
  const authed = !!Session.token;
  const el = $(`<header class="topbar">
    <span class="brand"><span class="brand-mark"></span>${esc(CFG.label)}</span>
    <span class="badge">${CFG.entities.length} record types</span>
    ${authed ? `<span class="userchip"><span class="avatar">${esc((Session.email||"?")[0].toUpperCase())}</span>
      <span>${esc(Session.email||"")}</span><button class="btn btn-ghost" id="out">Sign out</button></span>` : ``}
  </header>`);
  if (authed) el.querySelector("#out").onclick = async () => { await logout(); renderAuth(); };
  return el;
}

// --- views ---
function renderAuth(){
  const app = document.getElementById("app");
  app.innerHTML = "";
  app.appendChild(topbar());
  let mode = "login";
  const names = CFG.entities.map(e=>e.plural.replace(/_/g," "));
  const listed = names.slice(0,3).join(", ") + (names.length>3 ? ` and ${names.length-3} more` : "");
  const wrap = $(`<div class="auth-wrap">
    <section class="hero section-hero">
      <h2 class="mb-4">__TAGLINE__</h2>
      <p class="lead mt-4 mb-4">Manage ${esc(listed)} — with secure accounts, audited changes and
        active session control built in from the first request.</p>
      <div class="feature mt-6 gap-4"><span class="dot"></span><span>Owner-scoped records — every user sees exactly their own data, enforced server-side.</span></div>
      <div class="feature mt-4 gap-4"><span class="dot"></span><span>Live status workflow on every record type, with guarded state transitions.</span></div>
      <div class="feature mt-4 gap-4"><span class="dot"></span><span>Total visibility: counts, recent activity and pending work on the dashboard.</span></div>
      <div class="row gap-4 mt-6"><span class="pill status-ok">Encrypted at rest</span>
        <span class="pill">Audited</span><span class="pill">Session-secured</span></div>
    </section>
    <div class="auth-side p-6">
      <div class="card auth-card rounded-xl p-6">
        <h3 id="formtitle">Welcome back</h3>
        <p class="muted" id="sub">Sign in to your workspace</p>
        <label>Email</label><input id="email" type="email" autocomplete="username"/>
        <label>Password</label><input id="pw" type="password" autocomplete="current-password"/>
        <div class="row gap-4 mt-6">
          <button class="btn btn-primary" id="go"><span class="spinner hidden" id="spin"></span>Sign in</button>
          <button class="btn btn-ghost" id="swap">No account? Get started</button>
        </div>
        <p class="error hidden" id="error"></p>
      </div>
    </div>
  </div>`);
  app.appendChild(wrap);
  const err = wrap.querySelector("#error"), spin = wrap.querySelector("#spin");
  wrap.querySelector("#swap").onclick = () => {
    mode = mode==="login" ? "register" : "login";
    wrap.querySelector("#formtitle").textContent = mode==="login" ? "Welcome back" : "Create your account";
    wrap.querySelector("#sub").textContent = mode==="login" ? "Sign in to your workspace" : "Free to start — takes ten seconds";
    wrap.querySelector("#go").lastChild.textContent = mode==="login" ? "Sign in" : "Create account";
    wrap.querySelector("#swap").textContent = mode==="login" ? "No account? Get started" : "Have an account? Sign in";
  };
  wrap.querySelector("#go").onclick = async () => {
    err.classList.add("hidden"); spin.classList.remove("hidden");
    const email = wrap.querySelector("#email").value, pw = wrap.querySelector("#pw").value;
    try {
      if (mode==="register"){ await register(email,pw); }
      await login(email,pw);
      renderDashboard();
    } catch(e){ err.textContent = e.message || "Sign-in failed — try again"; err.classList.remove("hidden"); }
    finally { spin.classList.add("hidden"); }
  };
}

function shell(active){
  const app = document.getElementById("app");
  app.innerHTML = "";
  app.appendChild(topbar());
  const wrap = $(`<div class="shell"><nav class="sidenav"></nav><main id="main"></main></div>`);
  const nav = wrap.querySelector("nav");
  const dash = $(`<a class="${active==="__dash"?"active":""}"><span class="navdot"></span>${esc((CFG.home && CFG.home.nav_label) || "Dashboard")}</a>`);
  dash.onclick = renderDashboard; nav.appendChild(dash);
  for (const s of CFG.entities){
    const a = $(`<a class="${s.name===active?"active":""}"><span class="navdot"></span>${esc(s.plural.replace(/_/g," "))}</a>`);
    a.onclick = () => renderEntity(s.name); nav.appendChild(a);
  }
  app.appendChild(wrap);
  return wrap.querySelector("#main");
}

function renderDashboard(){ return CFG.home ? renderHome() : renderGenericDashboard(); }

async function renderGenericDashboard(){
  const main = shell("__dash");
  main.appendChild($(`<div class="pagehead"><h2>Dashboard</h2>
    <span class="badge">signed in as ${esc(Session.email||"")}</span></div>`));
  const grid = $(`<div class="statgrid gap-4 mb-6"></div>`);
  main.appendChild(grid);
  for (const s of CFG.entities)
    grid.appendChild($(`<div class="stat card rounded-xl p-6" data-stat="${s.plural}">
      <span class="accent"></span><div class="skeleton mb-4"></div>
      <div class="l">${esc(s.plural.replace(/_/g," "))}</div></div>`));
  const recent = $(`<div class="card rounded-xl p-6"><div class="row gap-4 mb-4">
    <h3>Recent records</h3><span class="badge" id="rlabel"></span></div>
    <div id="rbody"><div class="skeleton mb-4"></div><div class="skeleton mb-4"></div><div class="skeleton"></div></div></div>`);
  main.appendChild(recent);
  const results = await Promise.all(CFG.entities.map(s =>
    api("GET", `/${s.plural}?limit=100`).catch(()=>null)));
  results.forEach((rows, i) => {
    const s = CFG.entities[i];
    const box = grid.querySelector(`[data-stat="${s.plural}"]`);
    const n = rows ? rows.length : "–";
    box.querySelector(".skeleton").replaceWith($(`<div class="n">${n}</div>`));
  });
  const firstIdx = results.findIndex(r => Array.isArray(r) && r.length);
  const rbody = recent.querySelector("#rbody");
  if (firstIdx < 0){
    recent.querySelector("#rlabel").textContent = "empty";
    rbody.innerHTML = `<div class="empty"><div class="glyph"></div>
      No records yet — nothing here. Pick a record type in the sidebar to get started.</div>`;
    return;
  }
  const s = CFG.entities[firstIdx], rows = results[firstIdx].slice(-6).reverse();
  recent.querySelector("#rlabel").textContent = s.plural.replace(/_/g," ");
  const cols = s.fields.slice(0, 5).map(f=>f.name);
  rbody.innerHTML = `<div class="table-wrap"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${cellVal(s,c,r)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function cellVal(s, c, r){
  const f = s.fields.find(x=>x.name===c);
  if (f && f.encrypted && c!=="id") return `<span class="muted">•••</span>`;
  if (isStatusField(c) && r[c]!=null) return `<span class="pill ${pillFor(r[c])}">${esc(r[c])}</span>`;
  const v = r[c];
  if (v!=null && typeof v === "object") return esc(JSON.stringify(v)).slice(0,40);
  return esc(String(v==null?"":v)).slice(0,60);
}

function buildFormFields(s, form){
  for (const f of s.writable){
    const lab = `${f.name}${f.encrypted?' <span class="lock">encrypted</span>':''}${f.optional?'':' *'}`;
    if (f.input==="textarea") form.appendChild($(`<div><label>${lab}</label><textarea name="${f.name}"></textarea></div>`));
    else if (f.input==="checkbox") form.appendChild($(`<div class="row gap-4 mt-4"><input type="checkbox" name="${f.name}" class="w-auto"/><label class="m-0">${f.name}</label></div>`));
    else form.appendChild($(`<div><label>${lab}</label><input type="${f.input}" name="${f.name}"/></div>`));
  }
}

async function renderEntity(name){
  const main = shell(name);
  const s = CFG.entities.find(e=>e.name===name);
  const title = s.plural.replace(/_/g," ");
  main.appendChild($(`<div class="pagehead"><h2>${esc(title)}</h2>
    <span class="badge" id="count">…</span>
    ${s.owner?'<span class="pill status-ok">owner-scoped</span>':''}
    <span class="grow"></span>
    <button class="btn btn-primary" id="new">New ${esc(s.name)}</button></div>`));
  const listCard = $(`<div class="card rounded-xl p-6"><div id="rows">
    <div class="skeleton mb-4"></div><div class="skeleton mb-4"></div><div class="skeleton"></div></div></div>`);
  main.appendChild(listCard);

  // drawer (create/edit)
  const overlay = $(`<div class="overlay"></div>`);
  const drawer = $(`<div class="drawer p-6"><div class="row gap-4 mb-4">
    <h3 id="dtitle">New ${esc(s.name)}</h3><span class="grow"></span>
    <button class="btn btn-ghost" id="close">Close</button></div>
    <form id="dform"></form>
    <div class="row gap-4 mt-6"><button class="btn btn-primary" id="save"><span class="spinner hidden" id="dspin"></span>Save</button></div>
    <p class="error hidden" id="derr"></p></div>`);
  document.getElementById("app").append(overlay, drawer);
  const form = drawer.querySelector("#dform");
  buildFormFields(s, form);
  let editId = null;
  function openDrawer(row){
    editId = row ? row.id : null;
    drawer.querySelector("#dtitle").textContent = row ? `Edit ${s.name} #${row.id}` : `New ${s.name}`;
    form.reset(); if (row) fillForm(s, form, row);
    drawer.querySelector("#derr").classList.add("hidden");
    overlay.classList.add("open"); drawer.classList.add("open");
  }
  function closeDrawer(){ overlay.classList.remove("open"); drawer.classList.remove("open"); }
  overlay.onclick = closeDrawer;
  drawer.querySelector("#close").onclick = closeDrawer;
  main.querySelector("#new").onclick = () => openDrawer(null);

  let cache = [];
  async function load(){
    const rows = listCard.querySelector("#rows");
    try {
      cache = await api("GET", `/${s.plural}?limit=100`);
      main.querySelector("#count").textContent = `${cache.length} total`;
      if (!cache.length){
        rows.innerHTML = `<div class="empty"><div class="glyph"></div>
          <p>No ${esc(title)} yet — nothing here.</p>
          <button class="btn btn-primary mt-4" id="emptynew">Create your first ${esc(s.name)}</button></div>`;
        rows.querySelector("#emptynew").onclick = () => openDrawer(null);
        return;
      }
      const cols = s.fields.map(f=>f.name);
      rows.innerHTML = `<div class="table-wrap"><table>
        <thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join("")}<th></th></tr></thead>
        <tbody>${cache.map(r=>`<tr data-id="${r.id}">${cols.map(c=>`<td>${cellVal(s,c,r)}</td>`).join("")}
          <td class="row gap-4"><button class="btn btn-ghost" data-edit="${r.id}">Edit</button>
          <button class="btn btn-danger" data-del="${r.id}">Delete</button></td></tr>`).join("")}</tbody></table></div>`;
      rows.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{
        try { await api("DELETE", `/${s.plural}/${b.getAttribute("data-del")}`);
              toast(`${s.name} deleted`, "ok"); load(); }
        catch(e){ toast(`Delete failed: ${e.message}`, "error"); }
      });
      rows.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>{
        openDrawer(cache.find(r=>String(r.id)===b.getAttribute("data-edit")));
      });
    } catch(e){
      rows.innerHTML = `<p class="error">Failed to load: ${esc(e.message)} (${e.status||""}) — try again.</p>`;
    }
  }
  drawer.querySelector("#save").onclick = async () => {
    const derr = drawer.querySelector("#derr"), dspin = drawer.querySelector("#dspin");
    derr.classList.add("hidden"); dspin.classList.remove("hidden");
    try {
      const payload = readForm(s, form);
      if (editId){ await api("PUT", `/${s.plural}/${editId}`, payload); toast(`${s.name} #${editId} updated`, "ok"); }
      else { await api("POST", `/${s.plural}`, payload); toast(`${s.name} created`, "ok"); }
      closeDrawer(); load();
    } catch(e){ derr.textContent = e.message || "Save failed"; derr.classList.remove("hidden"); }
    finally { dspin.classList.add("hidden"); }
  };
  load();
}


// ---- declarative home view: widgets from CFG.home (domain-declared) ----
async function fetchAll(names){
  const uniq = [...new Set(names.filter(Boolean))];
  const out = {};
  await Promise.all(uniq.map(async n => {
    const s = CFG.entities.find(e=>e.name===n);
    out[n] = s ? await api("GET", `/${s.plural}?limit=200`).catch(()=>[]) : [];
  }));
  return out;
}
const daysLeft = (v) => Math.ceil((new Date(v).getTime() - Date.now()) / 86400000);
const moneyFmt = (cents) => "$" + ((cents||0)/100).toLocaleString(undefined,{minimumFractionDigits:2});
function wcard(label, wide){
  const el = $(`<div class="card rounded-xl p-6 ${wide?"w-wide":""}"><div class="row gap-4 mb-4"><h3>${esc(label)}</h3></div><div class="wbody"></div></div>`);
  return [el, el.querySelector(".wbody")];
}
function firstText(s, r){
  const f = (s.fields||[]).find(x => (x.type==="str"||x.type==="text") && !x.encrypted && r[x.name]);
  return f ? String(r[f.name]).slice(0,48) : ("#" + r.id);
}
const WIDGETS = {
  countdown(w, data){
    const [el, body] = wcard(w.label || "Deadlines", w.wide);
    const ds = (data[w.entity]||[]).flatMap(r => (w.fields||[]).map(f => ({f, v: r[f]})))
      .filter(d => d.v).map(d => ({...d, days: daysLeft(d.v)}))
      .filter(d => d.days > -400).sort((a,b)=>a.days-b.days).slice(0,4);
    if (!ds.length){ body.innerHTML = `<div class="empty"><div class="glyph"></div>No deadlines on the clock.</div>`; return el; }
    const tiles = $(`<div class="cd-tiles"></div>`);
    for (const d of ds){
      const tone = d.days <= 14 ? "bad" : d.days <= 45 ? "warn" : "ok";
      tiles.appendChild($(`<div class="cd ${tone}"><div class="n">${d.days < 0 ? "past" : d.days + "d"}</div>
        <div class="l">${esc(d.f.replace(/_/g," "))}</div>
        <div class="l">${esc(String(d.v).slice(0,10))}</div></div>`));
    }
    body.appendChild(tiles);
    return el;
  },
  money(w, data){
    const [el, body] = wcard(w.label || "Total", w.wide);
    const rows = (data[w.entity]||[]).filter(r => !w.statuses || w.statuses.includes(r.status));
    const total = rows.reduce((a,r)=>a+(r[w.amount_field]||0), 0);
    body.innerHTML = `<div class="money-n">${moneyFmt(total)}</div>
      <p class="muted">${rows.length} record${rows.length===1?"":"s"}${w.sub?` — ${esc(w.sub)}`:""}</p>`;
    return el;
  },
  board(w, data){
    const [el, body] = wcard(w.label || "Board", true);
    const s = CFG.entities.find(e=>e.name===w.entity);
    const rows = data[w.entity]||[];
    const order = w.statuses || [...new Set(rows.map(r=>r.status))];
    if (!rows.length){ body.innerHTML = `<div class="empty"><div class="glyph"></div>Nothing here yet.</div>`; return el; }
    const kb = $(`<div class="kanban"></div>`);
    for (const st of order){
      const col = $(`<div class="kcol"><h4>${esc(String(st).replace(/_/g," "))}</h4></div>`);
      for (const r of rows.filter(x=>x.status===st))
        col.appendChild($(`<div class="kcard">${esc(firstText(s, r))}</div>`));
      kb.appendChild(col);
    }
    body.appendChild(kb);
    return el;
  },
  pair_grid(w, data){
    const [el, body] = wcard(w.label || "Before / after", true);
    const rows = data[w.entity]||[];
    const groups = {};
    for (const r of rows){ const g = r[w.group_field] || "—"; (groups[g] = groups[g] || []).push(r); }
    if (!rows.length){ body.innerHTML = `<div class="empty"><div class="glyph"></div>No evidence captured yet.</div>`; return el; }
    for (const g of Object.keys(groups)){
      const rs = groups[g];
      const pair = $(`<div class="pair"><h4>${esc(g)}</h4></div>`);
      for (const ph of (w.phases||[])){
        const r = rs.find(x=>x[w.phase_field]===ph);
        pair.appendChild(r
          ? $(`<div class="pcell"><div class="ph">${esc(ph.replace(/_/g," "))}</div>${esc(r[w.note_field]||"")}
               <div class="meta">${esc(String(r[w.time_field]||"").slice(0,10))}${r[w.ref_field]?` · ${esc(r[w.ref_field])}`:""}</div></div>`)
          : $(`<div class="pcell"><div class="ph">${esc(ph.replace(/_/g," "))}</div><span class="muted">not captured</span></div>`));
      }
      body.appendChild(pair);
    }
    return el;
  },
  deficit(w, data){
    const [el, body] = wcard(w.label || "Delivered vs promised", true);
    const target = ((data[w.target_entity]||[])[0]||{})[w.target_field] || 0;
    const rows = data[w.entity]||[];
    if (!rows.length || !target){ body.innerHTML = `<div class="empty"><div class="glyph"></div>No delivery data logged yet.</div>`; return el; }
    const byWeek = {};
    for (const r of rows){
      const wk = String(r[w.time_field]||"").slice(0,10);
      byWeek[wk] = (byWeek[wk]||0) + (r[w.value_field]||0);
    }
    for (const wk of Object.keys(byWeek).sort()){
      const got = byWeek[wk];
      const pct = Math.min(100, Math.round(got/target*100));
      const tone = pct >= 100 ? "ok" : pct >= 60 ? "warn" : "bad";
      const row = $(`<div class="bar-row"><div class="bar-head"><span>week of ${esc(wk)}</span>
        <span>${got} / ${target}</span></div><div class="bar-track"><div class="bar-fill ${tone}"></div></div></div>`);
      row.querySelector(".bar-fill").style.width = pct + "%";
      body.appendChild(row);
    }
    return el;
  },
  timeline(w, data){
    const [el, body] = wcard(w.label || "Activity", w.wide);
    const rows = (data[w.entity]||[]).slice().sort((a,b)=>String(b[w.time_field]).localeCompare(String(a[w.time_field]))).slice(0,6);
    if (!rows.length){ body.innerHTML = `<div class="empty"><div class="glyph"></div>No activity yet.</div>`; return el; }
    for (const r of rows)
      body.appendChild($(`<div class="tl-item"><span class="tl-dot"></span><div>
        <div>${esc(String(r[w.title_field]||"").slice(0,60))}</div>
        <div class="muted">${esc(String(r[w.body_field]||"").slice(0,110))}</div>
        <div class="tl-when">${esc(String(r[w.time_field]||"").slice(0,10))}</div></div></div>`));
    return el;
  },
};
async function renderHome(){
  const main = shell("__dash");
  const H = CFG.home;
  main.appendChild($(`<div class="pagehead"><h2>${esc(H.headline || "Dashboard")}</h2>
    <span class="badge">${esc(Session.email||"")}</span></div>`));
  const grid = $(`<div class="homegrid gap-4"></div>`);
  main.appendChild(grid);
  const data = await fetchAll((H.widgets||[]).flatMap(w=>[w.entity, w.target_entity]));
  for (const w of (H.widgets||[])){
    try { if (WIDGETS[w.type]) grid.appendChild(WIDGETS[w.type](w, data)); }
    catch(e){ grid.appendChild($(`<div class="card rounded-xl p-6"><p class="error">${esc(w.type)} failed: ${esc(e.message)}</p></div>`)); }
  }
}

// boot: verify the session, else show auth
(async () => {
  if (Session.token){
    try { await api("GET","/auth/me?session="+encodeURIComponent(Session.token)); renderDashboard(); return; }
    catch { Session.token=null; }
  }
  renderAuth();
})();
</script>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    domain_name, out = argv[0], argv[1]
    import resolve as R
    import gen_models as GM
    domain = R.load_domain(domain_name)
    if not domain:
        print(f"unknown domain: {domain_name}"); return 1
    entities = [{"name": e["name"], "fields": GM.norm_fields(e)} for e in domain.get("entities", [])]
    eps = GM.effective_policies(entities, domain)
    specs = entity_specs(entities, eps)
    label = domain.get("label") or domain_name.replace("_", " ").title()
    os.makedirs(out, exist_ok=True)
    files = gen_frontend_files(domain_name, label, specs, domain.get("brand"),
                               domain.get("home"), domain.get("artifacts"))
    for fname, content in files.items():
        open(os.path.join(out, fname), "w", encoding="utf-8").write(content)
    html = files["index.html"]
    # machine-readable contract for verification
    open(os.path.join(out, "endpoints.json"), "w", encoding="utf-8").write(
        json.dumps(frontend_endpoints(specs), indent=2))
    open(os.path.join(out, "contract.json"), "w", encoding="utf-8").write(
        json.dumps({"domain": domain_name, "entities": specs,
                    "endpoints": frontend_endpoints(specs)}, indent=2))
    print(f"generated frontend -> {out}/index.html  "
          f"({len(specs)} entities, {len(frontend_endpoints(specs))} endpoints, {len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
