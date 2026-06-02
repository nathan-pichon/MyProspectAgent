"""Self-contained HTML dashboard for MyProspectAgent.

Renders a single static HTML file (no external assets, no CDN) that embeds the
prospect data as JSON and renders interactive ProspectCards client-side:
explainable confidence breakdown, verified-signal evidence, a contact block, an
editable outreach email (copy / mailto / regenerate), a Kanban prospecting
funnel (drag & drop), a why-not section, and a ⚙ Settings panel.

The page talks back to the local 127.0.0.1 server via a token-guarded API.
"""
from __future__ import annotations

import json
from pathlib import Path

from prospect.config import ProspectConfig
from prospect.store import PIPELINE_STATUSES, Store

STATUS_LABELS = {
    "found": "Trouvé",
    "qualified": "Qualifié",
    "contacted": "Contacté",
    "replied": "Réponse",
    "meeting": "RDV",
    "won": "Gagné",
    "lost": "Perdu",
}


def render(store: Store, cfg: ProspectConfig, out: str | Path = ".prospect_dashboard.html") -> Path:
    prospects = store.get_prospects(min_score=0)
    rejections = store.get_rejections(limit=80)
    quality = store.quality_stats()
    ready = store.ready_count()

    data = {
        "goal": cfg.goal,
        "threshold": cfg.scoring.threshold,
        "statuses": list(PIPELINE_STATUSES),
        "status_labels": STATUS_LABELS,
        "prospects": prospects,
        "rejections": rejections,
        "quality": quality,
        "ready": ready,
        "model": f"{cfg.llm.provider}:{cfg.llm.model}"
        + (f"  +  {cfg.llm.strong_provider}:{cfg.llm.strong_model}" if cfg.llm.has_strong_tier else ""),
        "rejection_reasons": {
            "not_a_company": "Pas une entreprise",
            "unverified_signal": "Signal non prouvé",
            "no_need": "Besoin peu probable",
            "off_icp": "Hors profil cible",
            "below_threshold": "Sous le seuil",
            "empty": "Page vide",
            "excluded": "Exclu",
        },
    }
    payload = json.dumps(data, ensure_ascii=False)

    html = (
        _HEAD
        + f"<script>window.__MPA_DATA__={payload};</script>\n"
        + _BODY
        + "<style>" + _CSS + "</style>\n"
        + "<script>" + _JS + "</script>\n</body></html>"
    )
    p = Path(out)
    p.write_text(html, encoding="utf-8")
    return p


_HEAD = """<!doctype html>
<html lang="fr" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyProspectAgent — Tableau de bord</title>
</head>
"""

_BODY = """<body>
<header class="hdr">
  <div class="brand">
    <span class="logo">◎</span>
    <span class="name">MyProspectAgent</span>
    <span class="badge-local">100&nbsp;% local — rien n'est envoyé</span>
  </div>
  <div class="hdr-actions">
    <span id="livedot" class="livedot" title="État"></span>
    <button id="runBtn" class="btn">▶ Lancer une recherche</button>
    <button id="settingsBtn" class="btn ghost">⚙ Réglages</button>
    <button id="themeBtn" class="btn ghost" title="Thème">◐</button>
  </div>
</header>

<section class="goalbar">
  <div class="goal-label">Objectif</div>
  <div id="goalText" class="goal-text"></div>
</section>

<section class="metrics">
  <div class="metric primary"><span id="mReady" class="m-num">0</span><span class="m-lbl">prospects prêts à contacter<br><small>(contact + email rédigé)</small></span></div>
  <div class="metric"><span id="mTotal" class="m-num">0</span><span class="m-lbl">prospects qualifiés</span></div>
  <div class="metric"><span id="mWhyNot" class="m-num">0</span><span class="m-lbl">écartés (why-not)</span></div>
  <div class="metric"><span id="mPhase" class="m-phase">au repos</span><span class="m-lbl">activité de l'agent</span></div>
</section>

<main id="board" class="board"></main>

<section class="whynot">
  <h2>Pourquoi pas ? <small>— ce que l'agent a écarté</small></h2>
  <div id="whynotList" class="whynot-list"></div>
</section>

<!-- Settings drawer -->
<div id="drawer" class="drawer">
  <div class="drawer-inner">
    <div class="drawer-head"><h2>⚙ Réglages</h2><button id="closeDrawer" class="btn ghost">✕</button></div>

    <div class="field">
      <label>Objectif de prospection</label>
      <textarea id="setGoal" rows="3"></textarea>
      <button id="saveGoal" class="btn small">Enregistrer l'objectif</button>
    </div>

    <div class="field">
      <label>Clés API (locales, jamais envoyées)</label>
      <input id="keyLight" type="password" placeholder="PROSPECT_LLM_API_KEY (modèle principal cloud)">
      <input id="keyStrong" type="password" placeholder="PROSPECT_STRONG_LLM_API_KEY (modèle fort)">
      <button id="saveKeys" class="btn small">Enregistrer les clés</button>
      <div id="keysStatus" class="hint"></div>
    </div>

    <div class="field">
      <label>Recherches automatiques</label>
      <div class="row">
        <label class="chk"><input id="schedEnabled" type="checkbox"> Activer</label>
        <input id="schedHours" type="number" min="0.25" step="0.25" value="12" style="width:5rem"> h
        <label class="chk"><input id="schedNotify" type="checkbox" checked> Notifier</label>
      </div>
      <button id="saveSched" class="btn small">Enregistrer la planification</button>
    </div>

    <div class="field">
      <div class="hint">Modèle : <span id="modelInfo"></span></div>
    </div>

    <div class="disclaimer">
      ⚖️ L'agent <b>rédige</b> les emails mais ne les <b>envoie jamais</b> — tu envoies depuis ton
      propre client mail. N'utilise que des contacts publics, respecte le RGPD et les opt-out.
      La source LinkedIn est opt-in (ToS).
    </div>
  </div>
</div>
<div id="toast" class="toast"></div>
"""


_CSS = """
:root{
  --bg:#f5f6f8; --surface:#fff; --surface2:#fafbfc; --text:#1a1d21; --muted:#6b7280;
  --border:#e4e7eb; --accent:#2E6BFF; --accent2:#00C2A8; --good:#16a34a; --warn:#d97706;
  --bad:#dc2626; --chip:#eef2ff; --chip-tx:#3047c0; --shadow:0 1px 3px rgba(0,0,0,.08);
}
html[data-theme=dark]{
  --bg:#0e1116; --surface:#171b22; --surface2:#1d222b; --text:#e6e9ef; --muted:#9aa3b2;
  --border:#2a3039; --chip:#1c2740; --chip-tx:#9db4ff; --shadow:0 1px 3px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
small{color:var(--muted)}
.hdr{position:sticky;top:0;z-index:40;display:flex;justify-content:space-between;align-items:center;
  padding:.6rem 1.1rem;background:var(--surface);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:.6rem}
.logo{font-size:1.4rem;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.name{font-weight:700;font-size:1.05rem}
.badge-local{font-size:.7rem;color:var(--good);border:1px solid var(--good);border-radius:999px;padding:.1rem .55rem;opacity:.85}
.hdr-actions{display:flex;align-items:center;gap:.5rem}
.btn{cursor:pointer;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:8px;padding:.45rem .8rem;font-size:.85rem;font-weight:600}
.btn.ghost{background:transparent;color:var(--text);border-color:var(--border)}
.btn.small{padding:.3rem .6rem;font-size:.78rem;margin-top:.4rem}
.btn:hover{filter:brightness(1.05)}
.livedot{width:.7rem;height:.7rem;border-radius:50%;background:var(--muted);display:inline-block}
.livedot.on{background:var(--good);box-shadow:0 0 0 3px rgba(22,163,74,.2);animation:pulse 1.4s infinite}
@keyframes pulse{50%{opacity:.45}}
.goalbar{display:flex;gap:.8rem;align-items:baseline;padding:.7rem 1.1rem;background:var(--surface2);border-bottom:1px solid var(--border)}
.goal-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:700}
.goal-text{font-size:.95rem}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem;padding:1rem 1.1rem}
.metric{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:.8rem 1rem;display:flex;flex-direction:column;gap:.2rem;box-shadow:var(--shadow)}
.metric.primary{border-color:var(--accent);background:linear-gradient(135deg,rgba(46,107,255,.08),rgba(0,194,168,.06))}
.m-num{font-size:1.9rem;font-weight:800;line-height:1}
.metric.primary .m-num{color:var(--accent)}
.m-phase{font-size:1rem;font-weight:700}
.m-lbl{font-size:.74rem;color:var(--muted)}
.board{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(300px,1fr);gap:.8rem;padding:0 1.1rem 1.5rem;overflow-x:auto}
.col{background:var(--surface2);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;min-height:120px}
.col-head{position:sticky;top:0;padding:.6rem .8rem;font-weight:700;font-size:.85rem;border-bottom:1px solid var(--border);display:flex;justify-content:space-between}
.col-head .cnt{color:var(--muted);font-weight:600}
.col-body{padding:.6rem;display:flex;flex-direction:column;gap:.6rem;min-height:60px}
.col.drag-over{outline:2px dashed var(--accent);outline-offset:-4px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:.7rem .8rem;box-shadow:var(--shadow);cursor:grab}
.card:active{cursor:grabbing}
.card-top{display:flex;justify-content:space-between;gap:.5rem;align-items:flex-start}
.company{font-weight:700;font-size:.98rem}
.meta{font-size:.74rem;color:var(--muted);margin-top:.1rem}
.score{font-weight:800;font-size:1rem;padding:.15rem .5rem;border-radius:8px;white-space:nowrap}
.s-strong{background:rgba(22,163,74,.15);color:var(--good)}
.s-good{background:rgba(46,107,255,.15);color:var(--accent)}
.s-partial{background:rgba(217,119,6,.15);color:var(--warn)}
.s-weak{background:rgba(220,38,38,.12);color:var(--bad)}
.summary{font-size:.84rem;margin:.5rem 0}
.bars{display:flex;flex-direction:column;gap:.25rem;margin:.4rem 0}
.bar{display:grid;grid-template-columns:64px 1fr 38px;align-items:center;gap:.4rem;font-size:.7rem}
.bar .track{display:block;height:7px;background:var(--border);border-radius:4px;overflow:hidden}
.bar .fill{display:block;height:7px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.signals{margin:.4rem 0;display:flex;flex-direction:column;gap:.3rem}
.sig{font-size:.76rem;background:var(--chip);color:var(--chip-tx);border-radius:6px;padding:.25rem .45rem}
.sig .q{font-style:italic}
.contact{display:flex;flex-wrap:wrap;gap:.35rem;margin:.5rem 0;align-items:center}
.pill{font-size:.74rem;border:1px solid var(--border);border-radius:999px;padding:.15rem .5rem;text-decoration:none;color:var(--text);display:inline-flex;gap:.25rem;align-items:center}
.pill:hover{border-color:var(--accent)}
.etype{font-size:.62rem;text-transform:uppercase;font-weight:700;border-radius:4px;padding:0 .3rem}
.etype.named{background:rgba(22,163,74,.18);color:var(--good)}
.etype.role{background:rgba(46,107,255,.15);color:var(--accent)}
.etype.generic{background:rgba(217,119,6,.15);color:var(--warn)}
.mail{margin-top:.5rem;border-top:1px dashed var(--border);padding-top:.5rem}
.mail summary{cursor:pointer;font-size:.8rem;font-weight:600;color:var(--accent)}
.mail input,.mail textarea{width:100%;margin-top:.4rem;background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:.4rem;font:inherit;font-size:.82rem}
.mail textarea{min-height:150px;resize:vertical}
.mail-actions{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.4rem}
.card-foot{display:flex;justify-content:space-between;align-items:center;margin-top:.5rem}
.fb button{background:none;border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:.85rem;padding:.1rem .4rem;color:var(--text)}
.fb button.act-up{border-color:var(--good);color:var(--good)}
.fb button.act-down{border-color:var(--bad);color:var(--bad)}
.movesel{font-size:.74rem;background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:.2rem}
.whynot{padding:0 1.1rem 2rem}
.whynot h2{font-size:1rem}
.whynot-list{display:flex;flex-wrap:wrap;gap:.45rem}
.wn{font-size:.76rem;border:1px solid var(--border);border-radius:8px;padding:.3rem .55rem;background:var(--surface);color:var(--muted)}
.wn b{color:var(--text)}
.drawer{position:fixed;inset:0 0 0 auto;width:min(420px,94vw);background:var(--surface);border-left:1px solid var(--border);transform:translateX(100%);transition:transform .25s;z-index:60;overflow-y:auto;box-shadow:-4px 0 24px rgba(0,0,0,.15)}
.drawer.open{transform:translateX(0)}
.drawer-inner{padding:1.1rem}
.drawer-head{display:flex;justify-content:space-between;align-items:center}
.field{margin:1.1rem 0;display:flex;flex-direction:column;gap:.3rem}
.field>label{font-weight:700;font-size:.82rem}
.field input,.field textarea{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:7px;padding:.45rem;font:inherit}
.row{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.chk{display:flex;align-items:center;gap:.3rem;font-size:.85rem}
.hint{font-size:.74rem;color:var(--muted)}
.disclaimer{margin-top:1.5rem;font-size:.75rem;color:var(--muted);border:1px solid var(--border);border-radius:10px;padding:.7rem;background:var(--surface2)}
.toast{position:fixed;bottom:1.2rem;left:50%;transform:translateX(-50%) translateY(200%);background:#111;color:#fff;padding:.6rem 1rem;border-radius:8px;font-size:.85rem;transition:transform .25s;z-index:80}
.toast.show{transform:translateX(-50%) translateY(0)}
.empty{color:var(--muted);font-size:.8rem;text-align:center;padding:1rem .5rem}
@media(max-width:720px){.metrics{grid-template-columns:repeat(2,1fr)}}
"""


_JS = r"""
const D = window.__MPA_DATA__ || {};
const TOKEN = window.__MPA_TOKEN__ || "";
const $ = (s,r=document)=>r.querySelector(s);
const esc = s => (s==null?"":String(s)).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = D.status_labels||{};

function toast(msg){const t=$("#toast");t.textContent=msg;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1900);}
async function api(path, body){
  const r = await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-MPA-Token":TOKEN},body:JSON.stringify(body||{})});
  if(!r.ok){const e=await r.json().catch(()=>({error:r.status}));throw new Error(e.error||r.status);}
  return r.json();
}
function verdictClass(v){return {strong:"s-strong",good:"s-good",partial:"s-partial",weak:"s-weak"}[v]||"s-weak";}
function verdict(score){return score>=75?"strong":score>=60?"good":score>=50?"partial":"weak";}

const BARS=[["signal","Signal"],["need","Besoin"],["icp","ICP"],["reachability","Contact"]];
function barsHtml(bd){
  bd=bd||{};
  return '<div class="bars">'+BARS.map(([k,lbl])=>{
    const seg=bd[k]||{score:0,max:1};const pct=Math.round(100*(seg.score||0)/(seg.max||1));
    return `<div class="bar"><span>${lbl}</span><span class="track"><span class="fill" style="width:${pct}%"></span></span><span>${seg.score||0}/${seg.max||0}</span></div>`;
  }).join("")+'</div>';
}
function signalsHtml(sigs){
  if(!sigs||!sigs.length) return "";
  return '<div class="signals">'+sigs.slice(0,3).map(s=>{
    const src=s.source_url?` <a href="${esc(s.source_url)}" target="_blank" rel="noopener" title="Vérifier la source">↗</a>`:"";
    return `<div class="sig">✓ <span class="q">«&nbsp;${esc(s.quote)}&nbsp;»</span>${s.signal?' — '+esc(s.signal):''}${src}</div>`;
  }).join("")+'</div>';
}
function contactHtml(p){
  const out=[];
  if(p.email){const bt=p.email_type?`<span class="etype ${esc(p.email_type)}">${esc(p.email_type)}</span>`:"";
    out.push(`<a class="pill" href="mailto:${esc(p.email)}">✉ ${esc(p.email)} ${bt}</a>`);}
  if(p.website) out.push(`<a class="pill" href="${esc(p.website)}" target="_blank" rel="noopener">🌐 site</a>`);
  if(p.linkedin) out.push(`<a class="pill" href="${esc(p.linkedin)}" target="_blank" rel="noopener">in LinkedIn</a>`);
  if(!out.length) out.push('<span class="pill" style="opacity:.6">aucun contact trouvé</span>');
  return '<div class="contact">'+out.join("")+'</div>';
}
function mailtoLink(p){
  const sub=encodeURIComponent(p.outreach_subject||"");
  const body=encodeURIComponent(p.outreach_body||"");
  const to=encodeURIComponent(p.email||"");
  return `mailto:${to}?subject=${sub}&body=${body}`;
}
function moveSel(p){
  return `<select class="movesel" data-url="${esc(p.url)}">`+
    (D.statuses||[]).map(s=>`<option value="${s}" ${s===p.status?"selected":""}>${esc(labels[s]||s)}</option>`).join("")+
    `</select>`;
}
function cardHtml(p){
  const v=p.verdict||verdict(p.score);
  return `<div class="card" draggable="true" data-url="${esc(p.url)}">
    <div class="card-top">
      <div><div class="company">${esc(p.company||"Inconnue")}</div>
        <div class="meta">${esc([p.industry,p.location].filter(Boolean).join(" · "))}${p.source?` · ${esc(p.source)}`:""}</div></div>
      <span class="score ${verdictClass(v)}">${p.score}</span>
    </div>
    ${p.summary?`<div class="summary">${esc(p.summary)}</div>`:""}
    ${barsHtml(p.breakdown)}
    ${signalsHtml(p.signals_found)}
    ${contactHtml(p)}
    <details class="mail">
      <summary>✉ Email de prospection</summary>
      <input class="m-subj" data-url="${esc(p.url)}" value="${esc(p.outreach_subject)}" placeholder="Objet">
      <textarea class="m-body" data-url="${esc(p.url)}">${esc(p.outreach_body)}</textarea>
      <div class="mail-actions">
        <button class="btn small act-copy" data-url="${esc(p.url)}">Copier</button>
        <a class="btn small act-send" href="${mailtoLink(p)}" data-url="${esc(p.url)}">Ouvrir dans mon mail →</a>
        <button class="btn small ghost act-save" data-url="${esc(p.url)}">Sauver</button>
        <button class="btn small ghost act-regen" data-url="${esc(p.url)}">↻ Régénérer</button>
      </div>
    </details>
    <div class="card-foot">
      <span class="fb">
        <button class="act-fb ${p.feedback===1?'act-up':''}" data-url="${esc(p.url)}" data-v="1">👍</button>
        <button class="act-fb ${p.feedback===-1?'act-down':''}" data-url="${esc(p.url)}" data-v="-1">👎</button>
      </span>
      ${moveSel(p)}
    </div>
  </div>`;
}

function renderBoard(){
  const board=$("#board");board.innerHTML="";
  const byStatus={};(D.statuses||[]).forEach(s=>byStatus[s]=[]);
  (D.prospects||[]).forEach(p=>{const s=byStatus[p.status]?p.status:"found";byStatus[s].push(p);});
  (D.statuses||[]).forEach(s=>{
    const col=document.createElement("div");col.className="col";col.dataset.status=s;
    const items=byStatus[s]||[];
    col.innerHTML=`<div class="col-head"><span>${esc(labels[s]||s)}</span><span class="cnt">${items.length}</span></div>
      <div class="col-body">${items.map(cardHtml).join("")|| '<div class="empty">—</div>'}</div>`;
    board.appendChild(col);
  });
  wireCards();
}

function wireCards(){
  document.querySelectorAll(".card").forEach(card=>{
    card.addEventListener("dragstart",e=>{e.dataTransfer.setData("text/plain",card.dataset.url);card.style.opacity=".4";});
    card.addEventListener("dragend",()=>{card.style.opacity="1";});
  });
  document.querySelectorAll(".col").forEach(col=>{
    col.addEventListener("dragover",e=>{e.preventDefault();col.classList.add("drag-over");});
    col.addEventListener("dragleave",()=>col.classList.remove("drag-over"));
    col.addEventListener("drop",async e=>{
      e.preventDefault();col.classList.remove("drag-over");
      const url=e.dataTransfer.getData("text/plain");const status=col.dataset.status;
      await moveProspect(url,status);
    });
  });
  document.querySelectorAll(".movesel").forEach(sel=>sel.addEventListener("change",e=>moveProspect(sel.dataset.url,sel.value)));
  document.querySelectorAll(".act-fb").forEach(b=>b.addEventListener("click",async()=>{
    const cur=b.classList.contains("act-up")||b.classList.contains("act-down");
    const v=cur?0:parseInt(b.dataset.v,10);
    try{await api("/api/feedback",{url:b.dataset.url,value:v});setLocal(b.dataset.url,p=>p.feedback=v);renderBoard();}catch(e){toast("Erreur: "+e.message);}
  }));
  document.querySelectorAll(".act-copy").forEach(b=>b.addEventListener("click",()=>{
    const p=getLocal(b.dataset.url);navigator.clipboard.writeText((p.outreach_subject?"Objet: "+p.outreach_subject+"\n\n":"")+(p.outreach_body||""));toast("Email copié");
  }));
  document.querySelectorAll(".act-save").forEach(b=>b.addEventListener("click",async()=>{
    const url=b.dataset.url;const subj=document.querySelector(`.m-subj[data-url="${cssesc(url)}"]`).value;
    const body=document.querySelector(`.m-body[data-url="${cssesc(url)}"]`).value;
    try{await api("/api/email",{url,subject:subj,body});setLocal(url,p=>{p.outreach_subject=subj;p.outreach_body=body;});toast("Email sauvegardé");renderBoard();}catch(e){toast("Erreur: "+e.message);}
  }));
  document.querySelectorAll(".act-regen").forEach(b=>b.addEventListener("click",async()=>{
    b.textContent="…";b.disabled=true;
    try{const r=await api("/api/email",{url:b.dataset.url,regenerate:true});setLocal(b.dataset.url,p=>{p.outreach_subject=r.subject;p.outreach_body=r.body;});toast("Email régénéré");renderBoard();}
    catch(e){toast("Erreur: "+e.message);b.textContent="↻ Régénérer";b.disabled=false;}
  }));
  document.querySelectorAll(".act-send").forEach(a=>a.addEventListener("click",()=>{
    // Sending from the user's own mail client → advance the funnel to "contacted".
    const url=a.dataset.url;const p=getLocal(url);
    if(p && (p.status==="found"||p.status==="qualified")) moveProspect(url,"contacted",true);
  }));
}
function cssesc(s){return (window.CSS&&CSS.escape)?CSS.escape(s):s.replace(/"/g,'\\"');}
function getLocal(url){return (D.prospects||[]).find(p=>p.url===url)||{};}
function setLocal(url,fn){const p=getLocal(url);if(p)fn(p);}
async function moveProspect(url,status,silent){
  try{await api("/api/move",{url,status});setLocal(url,p=>p.status=status);renderBoard();if(!silent)toast("Déplacé → "+(labels[status]||status));}
  catch(e){toast("Erreur: "+e.message);}
}

function renderWhyNot(){
  const list=$("#whynotList");const rs=D.rejections||[];
  $("#mWhyNot").textContent=rs.length;
  const rn=D.rejection_reasons||{};
  if(!rs.length){list.innerHTML='<div class="empty">Rien d\'écarté pour l\'instant.</div>';return;}
  list.innerHTML=rs.slice(0,60).map(r=>{
    let host=r.url;try{host=new URL(r.url).hostname;}catch(e){}
    return `<span class="wn"><b>${esc(rn[r.reason]||r.reason)}</b> · <a href="${esc(r.url)}" target="_blank" rel="noopener" style="color:inherit">${esc(host)}</a>${r.detail?` — ${esc(r.detail)}`:""}</span>`;
  }).join("");
}

function renderTop(){
  $("#goalText").textContent=D.goal||"(aucun objectif défini — voir ⚙ Réglages)";
  $("#mReady").textContent=D.ready||0;
  $("#mTotal").textContent=(D.prospects||[]).length;
}

/* ---- settings drawer ---- */
const drawer=$("#drawer");
$("#settingsBtn").onclick=async()=>{drawer.classList.add("open");try{await loadSettings();}catch(e){}};
$("#closeDrawer").onclick=()=>drawer.classList.remove("open");
async function loadSettings(){
  const r=await fetch("/api/settings");const s=await r.json();
  $("#setGoal").value=s.goal||"";
  $("#modelInfo").textContent=(s.llm?`${s.llm.provider}:${s.llm.model}`+(s.llm.has_strong?" (+ modèle fort)":""):"");
  $("#schedEnabled").checked=!!(s.schedule&&s.schedule.enabled);
  $("#schedHours").value=(s.schedule&&s.schedule.every_hours)||12;
  $("#schedNotify").checked=!!(s.schedule&&s.schedule.notify);
  const ks=s.secrets||{};
  $("#keysStatus").textContent="Clés enregistrées : "+Object.entries(ks).filter(([k,v])=>v).map(([k])=>k).join(", ")||"aucune";
}
$("#saveGoal").onclick=async()=>{try{await api("/api/goal",{goal:$("#setGoal").value});D.goal=$("#setGoal").value;renderTop();toast("Objectif enregistré");}catch(e){toast("Erreur: "+e.message);}};
$("#saveKeys").onclick=async()=>{
  const updates={};if($("#keyLight").value)updates.PROSPECT_LLM_API_KEY=$("#keyLight").value;
  if($("#keyStrong").value)updates.PROSPECT_STRONG_LLM_API_KEY=$("#keyStrong").value;
  if(!Object.keys(updates).length){toast("Rien à enregistrer");return;}
  try{await api("/api/secrets",{updates});$("#keyLight").value="";$("#keyStrong").value="";toast("Clés enregistrées (locales)");loadSettings();}catch(e){toast("Erreur: "+e.message);}
};
$("#saveSched").onclick=async()=>{
  try{await api("/api/schedule",{enabled:$("#schedEnabled").checked,every_hours:parseFloat($("#schedHours").value),notify:$("#schedNotify").checked});toast("Planification enregistrée");}catch(e){toast("Erreur: "+e.message);}
};

/* ---- run + theme + live ---- */
$("#runBtn").onclick=async()=>{try{await api("/api/run-now",{});toast("Recherche lancée…");}catch(e){toast("Erreur: "+e.message);}};
$("#themeBtn").onclick=()=>{const h=document.documentElement;const d=h.getAttribute("data-theme")==="dark";h.setAttribute("data-theme",d?"light":"dark");localStorage.setItem("mpa-theme",d?"light":"dark");};
if(localStorage.getItem("mpa-theme")==="dark")document.documentElement.setAttribute("data-theme","dark");

let lastAdded=0;
async function poll(){
  try{
    const r=await fetch("/api/state");const s=await r.json();
    const dot=$("#livedot");dot.classList.toggle("on",!!s.running);
    $("#mReady").textContent=s.ready_count??D.ready;
    $("#mTotal").textContent=s.matches_count??(D.prospects||[]).length;
    if(s.running&&s.progress){$("#mPhase").textContent=s.progress.phase||"en cours…";}
    else{$("#mPhase").textContent="au repos";}
    if(s.last_added&&s.last_added!==lastAdded){
      lastAdded=s.last_added;
      if(lastAdded){location.reload();} // new prospects → re-render with fresh server data
    }
  }catch(e){}
}
renderTop();renderBoard();renderWhyNot();
lastAdded=Math.max(0,...(D.prospects||[]).map(p=>p.first_seen||0));
setInterval(poll,4000);poll();
"""
