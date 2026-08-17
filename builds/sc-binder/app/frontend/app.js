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
      <h2 class="mb-4">IEP disputes are decided on documentation. Bring the better binder.</h2>
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