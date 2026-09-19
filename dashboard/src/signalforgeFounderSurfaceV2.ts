// SIGNALFORGE_FOUNDER_SURFACE_V2_FRONTEND_ONLY
// Frontend-only Founder workflow layer.
// Uses existing SignalForge APIs. It does not write market truth.

type Obj = Record<string, any>;

const API = "/api/signalforge";

const css = `
#sfv2-launcher {
  position: fixed; right: 18px; top: 18px; z-index: 2147483646;
  border: 1px solid rgba(148,163,184,.35); background: rgba(15,23,42,.96);
  color: #fff; border-radius: 999px; padding: 9px 13px; cursor: pointer;
  font: 600 12px/1.2 Inter, ui-sans-serif, system-ui, sans-serif;
  box-shadow: 0 8px 28px rgba(0,0,0,.22);
}
#sfv2-shell {
  position: fixed; inset: 0; z-index: 2147483645; pointer-events: none;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
#sfv2-panel {
  pointer-events: auto; position: absolute; right: 18px; top: 58px;
  width: min(560px, calc(100vw - 36px)); max-height: calc(100vh - 76px);
  overflow: auto; border: 1px solid rgba(148,163,184,.32);
  background: rgba(2,6,23,.98); color: #e2e8f0; border-radius: 18px;
  box-shadow: 0 24px 70px rgba(0,0,0,.38); display: none;
}
#sfv2-panel.open { display:block; }
.sfv2-head { position:sticky; top:0; z-index:2; padding:16px; background:rgba(2,6,23,.98);
  border-bottom:1px solid rgba(148,163,184,.16); }
.sfv2-title { font-size:16px; font-weight:800; color:#fff; display:flex; justify-content:space-between; gap:12px; }
.sfv2-sub { font-size:11px; color:#94a3b8; margin-top:4px; }
.sfv2-body { padding:14px; }
.sfv2-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
.sfv2-card { border:1px solid rgba(148,163,184,.18); border-radius:12px; padding:10px; background:rgba(15,23,42,.7); }
.sfv2-k { font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.06em; }
.sfv2-v { font-size:13px; font-weight:700; color:#f8fafc; margin-top:3px; overflow-wrap:anywhere; }
.sfv2-row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.sfv2-btn { border:1px solid rgba(148,163,184,.25); background:#0f172a; color:#e2e8f0;
  border-radius:10px; padding:8px 10px; cursor:pointer; font-size:12px; }
.sfv2-btn:hover { background:#1e293b; }
.sfv2-btn.primary { background:#1d4ed8; border-color:#2563eb; color:white; }
.sfv2-btn.warn { background:#7c2d12; border-color:#9a3412; }
.sfv2-pill { display:inline-flex; align-items:center; border-radius:999px; padding:4px 7px;
  font-size:10px; font-weight:700; border:1px solid rgba(148,163,184,.22); margin:2px; }
.sfv2-good { color:#86efac; } .sfv2-bad { color:#fca5a5; } .sfv2-mid { color:#fde68a; }
.sfv2-section { margin-top:14px; padding-top:12px; border-top:1px solid rgba(148,163,184,.14); }
.sfv2-section h4 { margin:0 0 8px; font-size:12px; color:#f8fafc; }
.sfv2-input { flex:1; min-width:140px; border:1px solid rgba(148,163,184,.25); background:#020617;
  color:white; border-radius:10px; padding:8px 10px; font-size:12px; outline:none; }
.sfv2-list { display:flex; flex-direction:column; gap:7px; }
.sfv2-item { border:1px solid rgba(148,163,184,.17); border-radius:10px; padding:9px; background:rgba(15,23,42,.48); }
.sfv2-small { font-size:11px; color:#94a3b8; line-height:1.45; }
.sfv2-error { color:#fca5a5; white-space:pre-wrap; }
.sfv2-progress { height:6px; border-radius:99px; background:#0f172a; overflow:hidden; margin-top:7px; }
.sfv2-progress > div { height:100%; background:linear-gradient(90deg,#2563eb,#22d3ee); width:0%; transition:width .4s ease; }
@media (max-width:700px){ .sfv2-grid{grid-template-columns:1fr}.sfv2-title{font-size:14px} }
`;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
function h(s: any){ return String(s ?? "—"); }

async function get(path: string): Promise<Obj> {
  const r = await fetch(path, {cache:"no-store"});
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function stateClass(v: string) {
  if (v === "SUPPORTED") return "sfv2-good";
  if (v === "REFUTED" || v === "CONTRADICTED") return "sfv2-bad";
  return "sfv2-mid";
}

function findClickable(patterns: RegExp[]): HTMLElement | null {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button]"));
  return nodes.find(n => patterns.some(p => p.test((n.innerText || n.textContent || "").trim()))) || null;
}
function clickExisting(patterns: RegExp[], fallbackMsg: string) {
  const n = findClickable(patterns);
  if (n) n.click();
  else alert(fallbackMsg);
}

function discoverCandidateIdsFromDOM(): number[] {
  const text = document.body.innerText || "";
  const ids = new Set<number>();
  for (const m of text.matchAll(/Candidate\s*#?\s*(\d{1,6})/gi)) ids.add(Number(m[1]));
  for (const m of text.matchAll(/candidate[:\s-]+(\d{1,6})/gi)) ids.add(Number(m[1]));
  return Array.from(ids).filter(n => Number.isFinite(n)).slice(0,80);
}

class FounderSurface {
  launcher = el("button");
  shell = el("div");
  panel = el("div");
  body = el("div","sfv2-body");
  status: Obj | null = null;
  candidateId: number | null = null;
  pollTimer: number | null = null;
  startedRunningAt: number | null = null;

  constructor(){
    const style = el("style"); style.textContent = css; document.head.appendChild(style);

    this.launcher.id = "sfv2-launcher";
    this.launcher.textContent = "Founder Console";
    this.launcher.onclick = () => this.toggle();

    this.shell.id = "sfv2-shell";
    this.panel.id = "sfv2-panel";
    const head = el("div","sfv2-head");
    const title = el("div","sfv2-title");
    const t = el("span","","SignalForge Founder Console");
    const close = el("button","sfv2-btn","Close");
    close.onclick = ()=>this.close();
    title.append(t,close);
    head.append(title, el("div","sfv2-sub","Candidate → Truth → Evidence → Next Research → Discussion"));
    this.panel.append(head,this.body);
    this.shell.append(this.panel);
    document.body.append(this.launcher,this.shell);

    this.renderHome();
    this.pollTimer = window.setInterval(()=>this.pollStatus(),5000);
    this.pollStatus();
    this.hookCandidateClicks();
    new MutationObserver(()=>this.hookCandidateClicks()).observe(document.body,{childList:true,subtree:true});
  }

  open(){ this.panel.classList.add("open"); }
  close(){ this.panel.classList.remove("open"); }
  toggle(){ this.panel.classList.toggle("open"); }

  async pollStatus(){
    try{
      const s = await get(`${API}/status`);
      const wasRunning = !!this.status?.running;
      this.status = s;
      if (s.running && !wasRunning) this.startedRunningAt = Date.now();
      if (!s.running && wasRunning) this.startedRunningAt = null;

      if (s.running) {
        const sec = this.startedRunningAt ? Math.floor((Date.now()-this.startedRunningAt)/1000) : 0;
        this.launcher.textContent = `Researching · ${Math.floor(sec/60)}m ${String(sec%60).padStart(2,"0")}s`;
      } else {
        this.launcher.textContent = "Founder Console";
      }
      if (this.panel.classList.contains("open") && this.candidateId == null) this.renderHome();
    }catch{}
  }

  hookCandidateClicks(){
    const nodes = Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button],tr,article"));
    for(const n of nodes){
      if (n.dataset.sfv2Hooked) continue;
      const m = (n.innerText||"").match(/Candidate\s*#?\s*(\d{1,6})/i);
      if (!m) continue;
      n.dataset.sfv2Hooked = "1";
      n.addEventListener("dblclick",(e)=>{
        e.preventDefault(); e.stopPropagation();
        this.openCandidate(Number(m[1]));
      });
      n.title = (n.title ? n.title+" · " : "") + "Double-click to inspect in Founder Console";
    }
  }

  renderHome(){
    this.candidateId = null;
    this.body.innerHTML = "";

    const s = this.status || {};
    const grid = el("div","sfv2-grid");
    const c1 = el("div","sfv2-card");
    c1.append(el("div","sfv2-k","Backend"), el("div","sfv2-v", s.running ? "RUNNING" : (s.status || "—")));
    const c2 = el("div","sfv2-card");
    c2.append(el("div","sfv2-k","Published refresh"), el("div","sfv2-v", s.running ? "Researching" : "Idle"));
    const c3 = el("div","sfv2-card");
    c3.append(el("div","sfv2-k","Last finished"), el("div","sfv2-v", h(s.last_finished_at)));
    grid.append(c1,c2,c3);
    this.body.append(grid);

    const nav = el("div","sfv2-section");
    nav.append(el("h4","","Founder Flow"));
    const row = el("div","sfv2-row");
    const overview = el("button","sfv2-btn","Overview");
    overview.onclick=()=>clickExisting([/overview/i,/總覽/], "No existing Overview control found.");
    const candidates = el("button","sfv2-btn primary","Candidates");
    candidates.onclick=()=>clickExisting([/candidate/i,/候選/], "No existing Candidates control found.");
    const research = el("button","sfv2-btn","Research");
    research.onclick=()=>clickExisting([/research center/i,/research/i,/研究中心/], "No existing Research control found.");
    const system = el("button","sfv2-btn","System");
    system.onclick=()=>clickExisting([/^system$/i,/系統/], "No existing System control found.");
    row.append(overview,candidates,research,system);
    nav.append(row);
    this.body.append(nav);

    const quick = el("div","sfv2-section");
    quick.append(el("h4","","Open any Candidate"));
    const qr = el("div","sfv2-row");
    const inp = el("input","sfv2-input") as HTMLInputElement;
    inp.placeholder = "Candidate ID, e.g. 253";
    const open = el("button","sfv2-btn primary","Inspect");
    open.onclick=()=>{ const id=Number(inp.value); if(id>0) this.openCandidate(id); };
    inp.addEventListener("keydown",e=>{ if(e.key==="Enter") open.click(); });
    qr.append(inp,open); quick.append(qr);

    const ids = discoverCandidateIdsFromDOM();
    if(ids.length){
      const d = el("div","sfv2-small",`Visible candidates detected: ${ids.join(", ")}`);
      d.style.marginTop="7px"; quick.append(d);
      const buttons = el("div","sfv2-row");
      buttons.style.marginTop="7px";
      for(const id of ids.slice(0,12)){
        const b=el("button","sfv2-btn",`#${id}`);
        b.onclick=()=>this.openCandidate(id);
        buttons.append(b);
      }
      quick.append(buttons);
    }
    this.body.append(quick);

    if (s.last_cycle?.phase_seconds){
      const sec = s.last_cycle.phase_seconds as Record<string,number>;
      const phases = Object.entries(sec).filter(([k])=>k!=="total_cycle").sort((a,b)=>b[1]-a[1]);
      const total = Number(sec.total_cycle||phases.reduce((a,[,v])=>a+Number(v),0)||1);
      const section = el("div","sfv2-section");
      section.append(el("h4","","Last refresh bottlenecks"));
      const list = el("div","sfv2-list");
      for(const [k,v0] of phases.slice(0,6)){
        const v=Number(v0);
        const item=el("div","sfv2-item");
        item.append(el("div","sfv2-row"));
        const r=item.firstChild as HTMLElement;
        r.append(el("div","sfv2-v",k),el("div","sfv2-small",`${v.toFixed(1)}s · ${(v/total*100).toFixed(0)}%`));
        const p=el("div","sfv2-progress"); const bar=el("div"); bar.style.width=`${Math.min(100,v/total*100)}%`; p.append(bar); item.append(p);
        list.append(item);
      }
      section.append(list); this.body.append(section);
    }
  }

  async openCandidate(id:number){
    this.candidateId=id;
    this.open();
    this.body.innerHTML="";
    const loading=el("div","sfv2-small",`Loading Candidate ${id}…`); this.body.append(loading);
    try{
      const [opp,cand,rs] = await Promise.all([
        get(`${API}/opportunity/${id}`),
        get(`${API}/opportunity/${id}/candidate`),
        get(`${API}/opportunity/${id}/research-state`)
      ]);
      this.renderCandidate(id,opp,cand,rs);
    }catch(err:any){
      this.body.innerHTML="";
      const back=el("button","sfv2-btn","← Back"); back.onclick=()=>this.renderHome();
      this.body.append(back,el("div","sfv2-error",`Candidate ${id} load failed\n${err?.message||err}`));
    }
  }

  renderCandidate(id:number, opp:Obj, cand:Obj, rs:Obj){
    this.body.innerHTML="";
    const top=el("div","sfv2-row");
    const back=el("button","sfv2-btn","← Back"); back.onclick=()=>this.renderHome();
    const refresh=el("button","sfv2-btn","Reload"); refresh.onclick=()=>this.openCandidate(id);
    top.append(back,refresh); this.body.append(top);

    const title=el("div","sfv2-section");
    title.append(el("div","sfv2-k",`Candidate ${id}`),el("div","sfv2-v",cand.title||cand.problem_statement||"Untitled"));
    title.append(el("div","sfv2-small",cand.problem_statement||""));
    this.body.append(title);

    const gates=el("div","sfv2-section"); gates.append(el("h4","","Decision-critical gates"));
    const gr=el("div","sfv2-grid");
    for(const code of ["C05","C07","C11"]){
      const state=h(opp.claim_states?.[code]);
      const c=el("div","sfv2-card");
      c.append(el("div","sfv2-k",code),el("div",`sfv2-v ${stateClass(state)}`,state));
      gr.append(c);
    }
    gates.append(gr);
    if(opp.founder_precision_corrections?.length){
      const note=el("div","sfv2-small","Precision correction applied: "+opp.founder_precision_corrections.map((x:Obj)=>`${x.claim_code} ${x.from}→${x.to}`).join(", "));
      note.style.marginTop="8px"; gates.append(note);
    }
    this.body.append(gates);

    const shape=el("div","sfv2-section"); shape.append(el("h4","","Opportunity shape"));
    const sg=el("div","sfv2-grid");
    for(const [k,v] of [
      ["Stage",cand.stage],["Founder status",cand.founder_status],
      ["Next gate",opp.solo_assessment?.next_gate],["Solo class",opp.solo_assessment?.classification],
      ["Specificity",opp.solo_assessment?.problem_specificity_score],["Solo score",opp.solo_assessment?.solo_score]
    ]){
      const c=el("div","sfv2-card"); c.append(el("div","sfv2-k",k),el("div","sfv2-v",h(v))); sg.append(c);
    }
    shape.append(sg); this.body.append(shape);

    const evidence=el("div","sfv2-section"); evidence.append(el("h4","","Evidence precision"));
    const eg=el("div","sfv2-grid");
    const vals=[
      ["Same-problem community", cand.community_evidence_count],
      ["Raw grouped", cand.community_evidence_count_raw ?? cand.community_evidence_count],
      ["Primary Published", opp.published_evidence?.length ?? 0],
      ["Context-only", opp.published_context_evidence?.length ?? 0],
      ["Community score", cand.community_problem_score],
      ["Raw community score", cand.community_problem_score_raw ?? cand.community_problem_score],
    ];
    for(const [k,v] of vals){ const c=el("div","sfv2-card"); c.append(el("div","sfv2-k",k),el("div","sfv2-v",h(v))); eg.append(c); }
    evidence.append(eg); this.body.append(evidence);

    const next=el("div","sfv2-section"); next.append(el("h4","","Best next evidence"));
    const bnr=rs.best_next_research;
    if(!bnr) next.append(el("div","sfv2-small","No guidance available."));
    else{
      const list=el("div","sfv2-list");
      const ps=bnr.priority||[];
      for(const p of ps){
        const item=el("div","sfv2-item");
        item.append(el("div","sfv2-v",p.claim_code?`${p.claim_code} · ${p.state||""}`:(p.gate||"Next gate")),
                    el("div","sfv2-small",p.action||p.why||""));
        list.append(item);
      }
      next.append(list);
    }
    this.body.append(next);

    const acts=el("div","sfv2-section"); acts.append(el("h4","","Actions"));
    const ar=el("div","sfv2-row");
    const more=el("button","sfv2-btn primary","Research next unknown");
    more.onclick=()=>clickExisting([/研究下一個未知/,/research more/i,/research next/i], "Existing Research More button not found on the current page. Open the Opportunity Detail page first.");
    const chat=el("button","sfv2-btn","Discuss with ChatGPT");
    chat.onclick=()=>clickExisting([/與\s*chatgpt\s*討論/i,/discuss with chatgpt/i,/chatgpt/i], "Existing ChatGPT discussion control not found on the current page.");
    const published=el("button","sfv2-btn warn","Refresh Published");
    published.onclick=()=>clickExisting([/重新分析/,/更新\s*published/i,/重新掃描/i,/refresh published/i], "Existing Published refresh control not found.");
    ar.append(more,chat,published); acts.append(ar);
    acts.append(el("div","sfv2-small","Research More remains Shadow. Founder Console does not promote claims or create market validation."));
    this.body.append(acts);
  }
}

function boot(){
  if(document.getElementById("sfv2-launcher")) return;
  new FounderSurface();
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot);
else boot();
