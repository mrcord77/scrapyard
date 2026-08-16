const api = (p, opt={}) => fetch('..' + p, {...opt, headers: {
  'Content-Type':'application/json',
  ...(localStorage.rw_tok ? {'Authorization':'Bearer '+localStorage.rw_tok, 'X-Session':localStorage.rw_tok} : {}),
  ...(opt.headers||{})}}).then(r => r.ok ? r.json() : Promise.reject(r.status));

async function login() {
  const em = document.getElementById('em').value, pw = document.getElementById('pw').value;
  try {
    await fetch('../auth/register', {method:'POST', headers:{'Content-Type':'application/json'},
                                     body: JSON.stringify({email:em,password:pw})});
    const r = await fetch('../auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
                                            body: JSON.stringify({email:em,password:pw})});
    if (!r.ok) throw new Error('login failed');
    localStorage.rw_tok = (await r.json()).session;
    boot();
  } catch (e) { document.getElementById('lerr').textContent = String(e.message || e); }
}

function pill(s){ return `<span class="pill ${s}">${s}</span>`; }

async function boot() {
  let me;
  try { me = await api('/auth/me'); }
  catch { document.getElementById('login').hidden = false; return; }
  document.getElementById('login').hidden = true;
  document.getElementById('dash').hidden = false;
  document.getElementById('who').textContent = me.email;
  const [exps, runs, docs] = await Promise.all([api('/experiments'), api('/runs'), api('/research_docs')]);
  const counts = {};
  for (const e of exps) counts[e.status] = (counts[e.status]||0)+1;
  const okRuns = runs.filter(r => r.status === 'succeeded').length;
  document.getElementById('tiles').innerHTML = [
    ['experiments', exps.length], ['running', counts.running||0],
    ['concluded', counts.concluded||0], ['runs total', runs.length],
    ['runs succeeded', okRuns], ['docs', docs.length],
  ].map(([l,n]) => `<div class="tile"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
  const en = Object.fromEntries(exps.map(e => [e.id, e.name]));
  document.querySelector('#exps tbody').innerHTML = exps.map(e =>
    `<tr><td>${e.name}</td><td>${(e.hypothesis||'').slice(0,40)}</td><td>${pill(e.status)}</td></tr>`).join('');
  document.querySelector('#runs tbody').innerHTML = runs.map(r =>
    `<tr><td>${r.id}</td><td>${en[r.experiment_id]||r.experiment_id}</td>` +
    `<td>${JSON.stringify(r.metrics||{}).slice(0,40)}</td><td>${pill(r.status)}</td></tr>`).join('');
}
boot();

document.getElementById("loginbtn").addEventListener("click", login);
