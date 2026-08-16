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


def gen_index_html(domain_name: str, label: str, specs: list[dict]) -> str:
    endpoints = frontend_endpoints(specs)
    cfg = json.dumps({"domain": domain_name, "label": label,
                      "entities": specs, "endpoints": endpoints}, indent=2)
    # This is a generated standalone app served by uvicorn; localStorage is the
    # intended place for its session token.
    return _TEMPLATE.replace("__LABEL__", label).replace("/*__CONFIG__*/ {}", cfg)


def gen_frontend_files(domain_name: str, label: str, specs: list[dict]) -> dict:
    """Split the SPA into CSP-compliant files. The backend serves
    `Content-Security-Policy: default-src 'self'`, which forbids inline
    <style>/<script> — a single-file inline SPA renders as a BLANK PAGE in a
    real browser (2026-08-16 campaign finding; every HTTP-level check passed
    because nothing executed JS). External same-origin files are allowed, so:
    index.html links styles.css + app.js. The inline JSON config block stays —
    type="application/json" is data, not an executed script, and CSP permits it.
    """
    html = gen_index_html(domain_name, label, specs)
    s0 = html.index("<style>")
    s1 = html.index("</style>")
    css = html[s0 + len("<style>"):s1].strip("\n")
    m0 = html.index('<script type="module">')
    m1 = html.rindex("</script>")
    js = html[m0 + len('<script type="module">'):m1].strip("\n")
    index = (html[:s0] + '<link rel="stylesheet" href="styles.css"/>' + html[s1 + len("</style>"):m0]
             + '<script type="module" src="app.js"></script>' + html[m1 + len("</script>"):])
    return {"index.html": index, "styles.css": css, "app.js": js}


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__LABEL__</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --fg:#e6e9ef; --mut:#8b93a3;
          --acc:#4f8cff; --bad:#ff5d5d; --ok:#39d98a; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }
  header { display:flex; align-items:center; gap:12px; padding:12px 18px;
           border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; }
  header h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:.2px; }
  header .who { margin-left:auto; color:var(--mut); font-size:13px; }
  button { font:inherit; cursor:pointer; border:1px solid var(--line); background:#1f2530;
           color:var(--fg); border-radius:7px; padding:7px 11px; }
  button.primary { background:var(--acc); border-color:var(--acc); color:#fff; }
  button.danger { color:var(--bad); border-color:#3a2730; }
  button:hover { filter:brightness(1.08); }
  .wrap { display:flex; min-height:calc(100vh - 49px); }
  nav { width:210px; border-right:1px solid var(--line); padding:12px; background:var(--panel); }
  nav a { display:block; padding:8px 10px; border-radius:7px; color:var(--fg);
          text-decoration:none; cursor:pointer; }
  nav a.active, nav a:hover { background:#1f2530; }
  main { flex:1; padding:22px; max-width:1000px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:11px; padding:18px;
          margin-bottom:18px; }
  .muted { color:var(--mut); }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
          font-size:13px; vertical-align:top; }
  th { color:var(--mut); font-weight:600; }
  .lock { color:var(--ok); font-size:11px; }
  label { display:block; margin:10px 0 4px; color:var(--mut); font-size:12px; }
  input,textarea,select { width:100%; background:#0c0e13; color:var(--fg);
          border:1px solid var(--line); border-radius:7px; padding:8px 10px; font:inherit; }
  textarea { min-height:70px; resize:vertical; }
  .row { display:flex; gap:10px; align-items:center; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:0 16px; }
  .err { color:var(--bad); }
  .center { max-width:380px; margin:9vh auto; }
  .badge { font-size:11px; color:var(--mut); border:1px solid var(--line); border-radius:20px;
           padding:2px 9px; }
  .hidden { display:none; }
</style>
</head>
<body>
<div id="app"></div>
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
  if (!res.ok) throw Object.assign(new Error((data&&data.detail)||res.statusText), {status:res.status, data});
  return data;
}

// --- auth ---
async function register(email, pw){ return api("POST","/auth/register",{email,password:pw}); }
async function login(email, pw){
  const r = await api("POST","/auth/login",{email,password:pw});
  Session.token = r.session; Session.email = email; return r;
}
async function logout(){ try{ if(Session.token) await api("POST","/auth/logout?session="+encodeURIComponent(Session.token)); }catch{} Session.token=null; Session.email=null; }

// --- coerce form values to typed payload ---
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

// --- views ---
function renderAuth(){
  const app = document.getElementById("app");
  app.innerHTML = "";
  let mode = "login";
  const box = $(`<div class="center"><div class="card">
    <h1 style="margin-top:0">${esc(CFG.label)}</h1>
    <p class="muted" id="sub">Sign in to continue</p>
    <label>Email</label><input id="email" type="email" autocomplete="username"/>
    <label>Password</label><input id="pw" type="password" autocomplete="current-password"/>
    <div class="row" style="margin-top:14px"><button class="primary" id="go">Sign in</button>
    <button id="swap">Need an account?</button></div>
    <p class="err hidden" id="err"></p></div></div>`);
  app.appendChild(box);
  const err = box.querySelector("#err");
  const sub = box.querySelector("#sub");
  box.querySelector("#swap").onclick = () => {
    mode = mode==="login" ? "register" : "login";
    box.querySelector("#go").textContent = mode==="login" ? "Sign in" : "Create account";
    sub.textContent = mode==="login" ? "Sign in to continue" : "Create your account";
    box.querySelector("#swap").textContent = mode==="login" ? "Need an account?" : "Have an account?";
  };
  box.querySelector("#go").onclick = async () => {
    err.classList.add("hidden");
    const email = box.querySelector("#email").value, pw = box.querySelector("#pw").value;
    try {
      if (mode==="register"){ await register(email,pw); }
      await login(email,pw);
      renderApp();
    } catch(e){ err.textContent = e.message || "failed"; err.classList.remove("hidden"); }
  };
}

function shell(activeName){
  const app = document.getElementById("app");
  app.innerHTML = "";
  app.appendChild($(`<header><h1>${esc(CFG.label)}</h1>
    <span class="badge">${CFG.entities.length} entities</span>
    <span class="who">${esc(Session.email||"")} · <a id="out" style="cursor:pointer;color:var(--acc)">sign out</a></span></header>`));
  const wrap = $(`<div class="wrap"><nav></nav><main id="main"></main></div>`);
  const nav = wrap.querySelector("nav");
  for (const s of CFG.entities){
    const a = $(`<a class="${s.name===activeName?"active":""}">${esc(s.name)}</a>`);
    a.onclick = () => renderEntity(s.name); nav.appendChild(a);
  }
  app.appendChild(wrap);
  app.querySelector("#out").onclick = async () => { await logout(); renderAuth(); };
}

async function renderEntity(name){
  shell(name);
  const s = CFG.entities.find(e=>e.name===name);
  const main = document.getElementById("main");
  main.appendChild($(`<div class="card"><h2 style="margin:0 0 4px">New ${esc(s.name)}</h2>
    <p class="muted" style="margin-top:0">${s.owner?`Owned by you (server-enforced).`:""}</p>
    <form id="cform"></form>
    <div class="row" style="margin-top:12px"><button class="primary" id="create">Create</button>
    <span class="err" id="cerr"></span></div></div>`));
  const form = main.querySelector("#cform");
  const grid = $(`<div class="grid"></div>`); form.appendChild(grid);
  for (const f of s.writable){
    const lab = `${f.name}${f.encrypted?' <span class="lock">🔒 encrypted at rest</span>':''}${f.optional?'':' *'}`;
    if (f.input==="textarea") grid.appendChild($(`<div style="grid-column:1/-1"><label>${lab}</label><textarea name="${f.name}"></textarea></div>`));
    else if (f.input==="checkbox") grid.appendChild($(`<div class="row" style="margin-top:18px"><input type="checkbox" name="${f.name}" style="width:auto"/><label style="margin:0">${f.name}</label></div>`));
    else grid.appendChild($(`<div><label>${lab}</label><input type="${f.input}" name="${f.name}"/></div>`));
  }
  const list = $(`<div class="card"><div class="row"><h2 style="margin:0">${esc(s.plural)}</h2>
    <button id="refresh" style="margin-left:auto">Refresh</button></div>
    <div id="rows"><p class="muted">loading…</p></div></div>`);
  main.appendChild(list);

  async function load(){
    const rows = list.querySelector("#rows");
    try {
      const data = await api("GET", `/${s.plural}?limit=100`);
      if (!data.length){ rows.innerHTML = `<p class="muted">No ${esc(s.plural)} yet.</p>`; return; }
      const cols = s.fields.map(f=>f.name);
      const head = cols.map(c=>`<th>${esc(c)}</th>`).join("")+"<th></th>";
      const body = data.map(r=>{
        const tds = cols.map(c=>{
          const f = s.fields.find(x=>x.name===c);
          return `<td>${f&&f.encrypted&&c!=="id"?'<span class="muted">•••</span>':esc(r[c])}</td>`;
        }).join("");
        return `<tr data-id="${r.id}">${tds}<td><button class="danger" data-del="${r.id}">delete</button></td></tr>`;
      }).join("");
      rows.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
      rows.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{
        await api("DELETE", `/${s.plural}/${b.getAttribute("data-del")}`); load();
      });
    } catch(e){ rows.innerHTML = `<p class="err">${esc(e.message)} (${e.status||""})</p>`; }
  }
  list.querySelector("#refresh").onclick = load;
  main.querySelector("#create").onclick = async () => {
    const cerr = main.querySelector("#cerr"); cerr.textContent="";
    try { const payload = readForm(s, form); await api("POST", `/${s.plural}`, payload); form.reset(); load(); }
    catch(e){ cerr.textContent = e.message || "create failed"; }
  };
  load();
}

function renderApp(){
  if (CFG.entities.length) renderEntity(CFG.entities[0].name);
  else { shell(); document.getElementById("main").innerHTML = '<p class="muted">No entities in this domain.</p>'; }
}

// boot: verify the session, else show auth
(async () => {
  if (Session.token){
    try { await api("GET","/auth/me?session="+encodeURIComponent(Session.token)); renderApp(); return; }
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
    files = gen_frontend_files(domain_name, label, specs)
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
