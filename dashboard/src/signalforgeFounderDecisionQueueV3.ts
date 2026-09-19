// SIGNALFORGE_FOUNDER_DECISION_QUEUE_V3_FRONTEND_ONLY
// Homepage integration: Founder-ready + watch + research candidates become a browseable decision queue.
// No market truth writes. Uses existing /api/candidates and opportunity detail APIs.

type Obj = Record<string, any>;

const API_ORIGIN = `${window.location.protocol}//${window.location.hostname}:8000`;
const API = `${API_ORIGIN}/api`;
const SF = `${API_ORIGIN}/api/signalforge`;
const ROOT_ID = "sf-founder-decision-queue-v3";

const css = `
#${ROOT_ID}{margin-top:16px;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#18181b}
.sfq-wrap{border:1px solid #e7e5e4;border-radius:18px;background:#fff;overflow:hidden}
.sfq-head{padding:16px 18px 12px;border-bottom:1px solid #eeeae6}
.sfq-title{font-size:15px;font-weight:750;display:flex;align-items:center;justify-content:space-between;gap:12px}
.sfq-sub{margin-top:5px;font-size:11px;color:#78716c;line-height:1.5}
.sfq-controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}
.sfq-btn,.sfq-select,.sfq-input{border:1px solid #dedad5;background:#fff;border-radius:9px;padding:7px 9px;font-size:11px;color:#292524}
.sfq-btn{cursor:pointer}.sfq-btn.active{background:#1c1917;color:white;border-color:#1c1917}
.sfq-input{min-width:210px;flex:1}
.sfq-stats{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.sfq-stat{font-size:10px;color:#57534e;background:#fafaf9;border:1px solid #ece7e2;border-radius:999px;padding:4px 7px}
.sfq-list{display:flex;flex-direction:column}
.sfq-row{display:grid;grid-template-columns:minmax(0,1fr) 115px 92px 90px 110px;gap:10px;padding:12px 18px;border-top:1px solid #f2efec;align-items:center;cursor:pointer}
.sfq-row:hover{background:#fafaf9}
.sfq-name{font-size:12px;font-weight:650;line-height:1.35;color:#1c1917}
.sfq-meta{font-size:10px;color:#8a817a;margin-top:3px}
.sfq-cell{font-size:10px;color:#57534e}
.sfq-pill{display:inline-flex;border:1px solid #dedad5;border-radius:999px;padding:4px 7px;font-size:9px;font-weight:700}
.sfq-ready{color:#047857;background:#ecfdf5;border-color:#a7f3d0}
.sfq-watch{color:#92400e;background:#fffbeb;border-color:#fde68a}
.sfq-research{color:#1d4ed8;background:#eff6ff;border-color:#bfdbfe}
.sfq-parked{color:#6b7280;background:#f9fafb;border-color:#e5e7eb}
.sfq-empty{padding:28px 18px;text-align:center;color:#78716c;font-size:12px}
.sfq-more{display:block;margin:12px auto 16px}
.sfq-detail{padding:16px 18px;border-top:1px solid #e7e5e4;background:#fcfbfa}
.sfq-detail-title{font-size:14px;font-weight:750;margin-bottom:8px}
.sfq-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.sfq-card{border:1px solid #ece7e2;border-radius:10px;padding:9px;background:#fff}
.sfq-k{font-size:9px;color:#8a817a;text-transform:uppercase}
.sfq-v{font-size:11px;font-weight:700;margin-top:3px;overflow-wrap:anywhere}
.sfq-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.sfq-primary{background:#1c1917;color:#fff;border-color:#1c1917}
.sfq-error{padding:12px 18px;color:#b91c1c;font-size:11px}
@media(max-width:950px){.sfq-row{grid-template-columns:minmax(0,1fr) 90px 80px}.sfq-hide-sm{display:none}.sfq-grid{grid-template-columns:repeat(2,1fr)}}
`;

function el<K extends keyof HTMLElementTagNameMap>(tag:K, cls?:string, text?:string){
  const n=document.createElement(tag); if(cls)n.className=cls; if(text!=null)n.textContent=text; return n;
}
function s(v:any){return String(v??"—")}
function n(v:any){const x=Number(v);return Number.isFinite(x)?x:0}

function normalizeCandidates(raw:any):Obj[]{
  if(Array.isArray(raw)) return raw;
  for(const k of ["candidates","items","rows","results","data"]){
    if(Array.isArray(raw?.[k])) return raw[k];
  }
  return [];
}

function idOf(x:Obj):number|null{
  for(const k of ["id","candidate_id"]){
    const v=Number(x?.[k]); if(Number.isFinite(v)&&v>0)return v;
  }
  return null;
}

function classify(x:Obj){
  const founder=String(x.founder_surface_status||x.solo_status||x.founder_status||"").toUpperCase();
  const stage=String(x.stage||"").toUpperCase();
  if(founder.includes("READY")||stage.includes("SOLO_READY")) return "READY";
  if(founder.includes("PARK")||stage.includes("PARK")) return "PARKED";
  if(founder.includes("RESEARCH")||stage.includes("RESEARCH")) return "RESEARCH";
  return "WATCH";
}
function pillClass(k:string){return k==="READY"?"sfq-ready":k==="RESEARCH"?"sfq-research":k==="PARKED"?"sfq-parked":"sfq-watch"}

async function get(url:string){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);return r.json()}

function findTextNode(re:RegExp):HTMLElement|null{
  const all=Array.from(document.querySelectorAll<HTMLElement>("h1,h2,h3,h4,p,div,span"));
  return all.find(x=>re.test((x.textContent||"").trim()))||null;
}

function hideOldEmptyState(){
  const target=findTextNode(/目前沒有通過\s*Solo Founder Gate\s*的商機/);
  if(!target)return;
  let p:HTMLElement|null=target;
  for(let i=0;i<5&&p?.parentElement;i++,p=p.parentElement){
    const r=p.getBoundingClientRect();
    if(r.width>500 && r.height>90 && r.height<420){
      p.style.display="none";
      p.dataset.sfqHiddenEmpty="1";
      return;
    }
  }
}

function findMount():HTMLElement|null{
  const priority=findTextNode(/^Founder priority$/i);
  if(priority){
    let p:HTMLElement|null=priority.parentElement;
    for(let i=0;i<3&&p?.parentElement;i++,p=p.parentElement){
      if(p.getBoundingClientRect().width>600) return p;
    }
  }
  const title=findTextNode(/今天的\s*Solo Founder\s*商機/);
  return title?.parentElement?.parentElement || document.querySelector("main");
}

function findExistingAction(patterns:RegExp[]){
  const nodes=Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button]"));
  return nodes.find(x=>patterns.some(re=>re.test((x.innerText||x.textContent||"").trim())))||null;
}

class Queue {
  root=el("section"); all:Obj[]=[]; filtered:Obj[]=[]; shown=20; filter="ALL"; query="";
  constructor(){
    this.root.id=ROOT_ID;
    this.load();
  }
  async load(){
    this.root.innerHTML=`<div class="sfq-wrap"><div class="sfq-empty">Loading Founder decision queue…</div></div>`;
    try{
      const raw=await get(`${API}/candidates`);
      this.all=normalizeCandidates(raw).filter(x=>idOf(x)!=null);
      this.apply();
    }catch(e:any){
      this.root.innerHTML=`<div class="sfq-wrap"><div class="sfq-error">Decision queue could not load FastAPI /api/candidates: ${String(e?.message||e)}</div></div>`;
    }
  }
  apply(){
    const q=this.query.trim().toLowerCase();
    this.filtered=this.all.filter(x=>{
      const cls=classify(x);
      if(this.filter!=="ALL"&&cls!==this.filter)return false;
      if(!q)return true;
      return [x.title,x.problem_statement,x.actor,x.task,x.failure_mode,idOf(x)].some(v=>String(v??"").toLowerCase().includes(q));
    });
    this.render();
  }
  render(){
    this.root.innerHTML="";
    const wrap=el("div","sfq-wrap");
    const head=el("div","sfq-head");
    const title=el("div","sfq-title");
    title.append(el("span","","Founder decision queue"),el("span","sfq-meta",`${this.filtered.length} visible / ${this.all.length} candidates`));
    head.append(title,el("div","sfq-sub","不是只有通過 Gate 才能看。READY / WATCH / RESEARCH / PARKED 都可瀏覽；Gate 是決策狀態，不是 UI 入口限制。"));

    const controls=el("div","sfq-controls");
    for(const f of ["ALL","READY","WATCH","RESEARCH","PARKED"]){
      const b=el("button",`sfq-btn ${this.filter===f?"active":""}`,f);
      b.onclick=()=>{this.filter=f;this.shown=20;this.apply()}; controls.append(b);
    }
    const inp=el("input","sfq-input") as HTMLInputElement;
    inp.placeholder="Search Candidate / problem / actor / task…"; inp.value=this.query;
    inp.oninput=()=>{this.query=inp.value;this.shown=20;this.apply()};
    controls.append(inp); head.append(controls);

    const counts:{[k:string]:number}={READY:0,WATCH:0,RESEARCH:0,PARKED:0};
    for(const x of this.all)counts[classify(x)]++;
    const stats=el("div","sfq-stats");
    for(const k of ["READY","WATCH","RESEARCH","PARKED"])stats.append(el("span","sfq-stat",`${k} ${counts[k]}`));
    head.append(stats); wrap.append(head);

    const list=el("div","sfq-list");
    const rows=this.filtered.slice(0,this.shown);
    for(const x of rows) list.append(this.row(x));
    if(!rows.length) list.append(el("div","sfq-empty","No candidates match this filter."));
    wrap.append(list);
    if(this.filtered.length>this.shown){
      const more=el("button","sfq-btn sfq-more","Load 20 more");
      more.onclick=()=>{this.shown+=20;this.render()}; wrap.append(more);
    }
    this.root.append(wrap);
  }
  row(x:Obj){
    const id=idOf(x)!; const cls=classify(x);
    const row=el("div","sfq-row");
    const main=el("div");
    main.append(el("div","sfq-name",x.title||x.problem_statement||`Candidate ${id}`),
                el("div","sfq-meta",`Candidate ${id}${x.actor_category?` · ${x.actor_category}`:""}${x.task?` · ${x.task}`:""}`));
    row.append(main,el("div",`sfq-cell ${pillClass(cls)}`,cls),
      el("div","sfq-cell",`Market ${n(x.market_score).toFixed(1)}`),
      el("div","sfq-cell sfq-hide-sm",`Conf ${n(x.confidence_score).toFixed(1)}`),
      el("div","sfq-cell sfq-hide-sm",s(x.stage||x.founder_status)));
    row.onclick=()=>this.openDetail(id,row);
    return row;
  }
  async openDetail(id:number,row:HTMLElement){
    const old=this.root.querySelector(".sfq-detail"); if(old)old.remove();
    const detail=el("div","sfq-detail"); detail.append(el("div","sfq-meta",`Loading Candidate ${id}…`));
    row.insertAdjacentElement("afterend",detail);
    try{
      const [opp,cand,rs]=await Promise.all([
        get(`${SF}/opportunity/${id}`),
        get(`${SF}/opportunity/${id}/candidate`),
        get(`${SF}/opportunity/${id}/research-state`)
      ]);
      detail.innerHTML="";
      detail.append(el("div","sfq-detail-title",cand.title||cand.problem_statement||`Candidate ${id}`));
      const grid=el("div","sfq-grid");
      const vals=[
        ["C05 Buyer",opp.claim_states?.C05],["C07 Gap",opp.claim_states?.C07],
        ["C11 WTP",opp.claim_states?.C11],["Next gate",opp.solo_assessment?.next_gate],
        ["Solo class",opp.solo_assessment?.classification],["Specificity",opp.solo_assessment?.problem_specificity_score],
        ["Same-problem",cand.community_evidence_count],["Primary evidence",opp.published_evidence?.length]
      ];
      for(const [k,v] of vals){const c=el("div","sfq-card");c.append(el("div","sfq-k",k),el("div","sfq-v",s(v)));grid.append(c)}
      detail.append(grid);
      const next=rs.best_next_research;
      if(next){
        const txt=(next.priority||[]).map((p:Obj)=>p.action||p.why||p.gate).filter(Boolean).slice(0,3).join(" · ");
        detail.append(el("div","sfq-sub",`Best next evidence: ${txt||"available"}`));
      }
      const actions=el("div","sfq-actions");
      const research=el("button","sfq-btn sfq-primary","Research next unknown");
      research.onclick=(e)=>{e.stopPropagation();const b=findExistingAction([/研究下一個未知/,/research more/i,/research next/i]);if(b)b.click();else alert("Open the existing Opportunity Detail route to run Research More; this queue does not fabricate a write endpoint.")};
      const chat=el("button","sfq-btn","Discuss with ChatGPT");
      chat.onclick=(e)=>{e.stopPropagation();const b=findExistingAction([/與\s*chatgpt\s*討論/i,/discuss with chatgpt/i]);if(b)b.click();else alert("ChatGPT handoff control is available on the existing Opportunity Detail surface.")};
      actions.append(research,chat); detail.append(actions);
    }catch(e:any){
      detail.innerHTML=""; detail.append(el("div","sfq-error",`Candidate ${id} detail failed: ${String(e?.message||e)}`));
    }
  }
}

function install(){
  if(document.getElementById(ROOT_ID))return;
  // Remove the temporary v2 floating Founder Console if old bundle/import is still present.
  document.getElementById("sfv2-launcher")?.remove();
  document.getElementById("sfv2-shell")?.remove();

  const style=el("style");style.textContent=css;document.head.append(style);
  hideOldEmptyState();
  const mount=findMount(); if(!mount)return;
  const q=new Queue();
  mount.append(q.root);
}

let attempts=0;
function boot(){
  install();
  if(!document.getElementById(ROOT_ID)&&attempts++<30)setTimeout(boot,500);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
new MutationObserver(()=>{ if(!document.getElementById(ROOT_ID))boot(); }).observe(document.body,{childList:true,subtree:true});
