# Splice the declarative home-view widget engine into gen_frontend.py
p = "tools/gen_frontend.py"
src = open(p, encoding="utf-8").read()

CSS = """
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
"""

anchor_css = "  @media (max-width:920px) {"
assert anchor_css in src
src = src.replace(anchor_css, CSS + anchor_css, 1)
src = src.replace("    .sidenav a { margin-bottom:0; }\n    main { padding:18px; }",
                  "    .sidenav a { margin-bottom:0; }\n    main { padding:18px; }\n"
                  "    .homegrid { grid-template-columns:1fr; }\n    .pair { grid-template-columns:1fr; }", 1)

JS = r"""
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

"""

anchor_js = "// boot: verify the session, else show auth"
assert anchor_js in src
src = src.replace(anchor_js, JS + anchor_js, 1)

assert "async function renderDashboard(){" in src
src = src.replace("async function renderDashboard(){",
                  "function renderDashboard(){ return CFG.home ? renderHome() : renderGenericDashboard(); }\n\n"
                  "async function renderGenericDashboard(){", 1)
src = src.replace('<span class="navdot"></span>Dashboard</a>`);',
                  '<span class="navdot"></span>${esc((CFG.home && CFG.home.nav_label) || "Dashboard")}</a>`);', 1)
open(p, "w", encoding="utf-8").write(src)
print("widget engine spliced OK")
