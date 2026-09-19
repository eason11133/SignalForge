import { useMemo, useState } from "react";
import { ArrowUpDown, Binoculars, Clock3, GitCompareArrows, HelpCircle, ShieldAlert, Target } from "lucide-react";
import { useAskSignalForgeDecision, useCompareSignalForgeDecisions, useSignalForgeBenchmarkBatch, useSignalForgeDecisionPortfolio } from "../api/hooks";
import type { SignalForgeBenchmarkHypothesis, SignalForgeDecisionItem, SignalForgeDecisionTrigger } from "../api/client";

const trackClass: Record<string,string> = {
  CASH: "border-success/25 bg-success/10 text-txt-success",
  BOTH: "border-info/25 bg-info/10 text-txt-info",
  ZIP2: "border-purple-400/25 bg-purple-400/10 text-purple-300",
  PARK: "border-border-secondary bg-bg-secondary text-text-tertiary",
};
const stateClass = (s?:string) => s === "SUPPORTED" ? "text-txt-success" : s === "REFUTED" ? "text-txt-danger" : s === "PARTIAL" ? "text-txt-warning" : "text-text-tertiary";
const actionClass: Record<string,string> = {
  ACTION_NOW:"border-success/25 bg-success/10 text-txt-success", VALIDATE_DISTRIBUTION:"border-warning/25 bg-warning/10 text-txt-warning",
  NARROW_WEDGE:"border-info/25 bg-info/10 text-txt-info", INVESTIGATE:"border-warning/25 bg-warning/10 text-txt-warning", WATCH:"border-border-secondary bg-bg-secondary text-text-secondary",
  PARK_OR_PARTNER:"border-danger/20 bg-danger/5 text-txt-danger", PARK:"border-border-secondary bg-bg-secondary text-text-tertiary",
};

function TrackPill({track}:{track?:string}) { return <span title="Market Track" className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${trackClass[track || "PARK"] || trackClass.PARK}`}>Market · {track || "PARK"}</span>; }
function ActionPill({action}:{action?:string}) { return <span title="Founder Actionability" className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${actionClass[action || "PARK"] || actionClass.PARK}`}>Founder · {action || "PARK"}</span>; }

function TriggerWatch({data}:{data?:SignalForgeDecisionTrigger}) {
  if(!data) return null;
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
    <div className="flex items-center gap-2 text-xs font-semibold text-text-primary"><Binoculars size={14}/> Trigger Watch</div>
    <p className="mt-1 text-[10px] text-text-tertiary">不是一直監控新聞，而是「什麼世界變化發生時才值得重新看」。</p>
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <div><div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-txt-success">Promote if</div>{(data.promote_if || []).map((x,i)=><div key={i} className="mt-1 text-[11px] text-text-secondary"><b className="text-text-primary">→ {x.to}</b> {x.if}</div>)}</div>
      <div><div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-txt-warning">Demote if</div>{(data.demote_if || []).map((x,i)=><div key={i} className="mt-1 text-[11px] text-text-secondary"><b className="text-text-primary">→ {x.to}</b> {x.if}</div>)}</div>
      <div className="md:col-span-2"><div className="text-[9px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Watch for</div><div className="mt-1 flex flex-wrap gap-2">{(data.watch_for || []).map((x,i)=><span key={i} className="rounded-xl border border-border-secondary bg-bg-secondary px-2.5 py-1.5 text-[10px] text-text-secondary"><b>{x.trigger}</b> · {x.for}</span>)}</div></div>
    </div>
  </div>;
}

function DecisionCard({item, selected, onToggle}:{item:SignalForgeDecisionItem;selected:boolean;onToggle:()=>void}) {
  const ladder = item.validation_ladder?.stages || item.wedge_ladder?.stages || [];
  return <article className={`rounded-2xl border bg-bg-primary p-4 ${selected ? "border-info/50" : "border-border-secondary"}`}>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><TrackPill track={item.market_track || item.current_track}/><ActionPill action={item.founder_action}/><span className="text-[9px] uppercase tracking-[0.12em] text-text-tertiary">Founder #{item.founder_rank || item.rank || "—"}</span></div><h3 className="mt-2 text-sm font-semibold text-text-primary">{item.title || item.thesis_id}</h3><p className="mt-1 text-[11px] text-text-secondary">{item.problem}</p></div>
      <label className="flex shrink-0 items-center gap-1.5 text-[10px] text-text-tertiary"><input type="checkbox" checked={selected} onChange={onToggle}/>比較</label>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5">
      <Metric k="Revenue" v={item.revenue_wedge_decision}/><Metric k="Spend" v={item.existing_spend}/><Metric k="Paid dissatisfaction" v={String(item.paid_dissatisfaction_count ?? 0)}/><Metric k="Founder fit" v={item.founder_fit?.state}/><Metric k="ZIP2" v={item.zip2_readiness}/>
    </div>
    <div className="mt-3 rounded-xl bg-bg-secondary p-3"><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">Why this rank</div><div className="mt-1 text-[11px] text-text-secondary">{item.rank_explanation?.band} · {item.rank_explanation?.track} · wedge {item.rank_explanation?.revenue_wedge} · spend {item.rank_explanation?.existing_spend} · fit {item.rank_explanation?.founder_fit}</div><div className="mt-1 text-[9px] text-text-tertiary">沒有神秘總分，排序規則可拆解。</div></div>
    <div className="mt-3"><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">Validation Ladder</div><div className="mt-1 flex flex-wrap gap-1.5">{ladder.map((x,i)=><span key={i} className={`rounded-lg border border-border-secondary bg-bg-secondary px-2 py-1 text-[9px] ${stateClass(x.state)}`}>{x.stage} · {x.state}</span>)}</div></div>
    <div className="mt-3 grid gap-3 lg:grid-cols-2">
      <div><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-txt-info">What changes the ranking</div>{(item.what_changes_rank || []).slice(0,4).map((x,i)=><div key={i} className="mt-1 text-[10px] text-text-secondary">• {x}</div>)}</div>
      <div><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">Do Not Research</div>{(item.do_not_research || []).slice(0,4).map((x,i)=><div key={i} className="mt-1 text-[10px] text-text-secondary">• {x.topic}: {x.reason}</div>)}</div>
    </div>
    <div className="mt-3 rounded-xl border border-border-secondary bg-bg-secondary p-3"><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-txt-info">Founder Actionability Gate</div><div className="mt-1 text-[11px] font-semibold text-text-primary">{item.founder_action || "UNKNOWN"}</div>{(item.founder_actionability?.blockers || []).map((x,i)=><div key={i} className="mt-1 text-[10px] text-txt-warning">• {x}</div>)}</div>
    <details className="mt-3"><summary className="cursor-pointer text-[10px] text-text-tertiary">Founder Fit / Structural relationships / Wedge expansion</summary><div className="mt-2 grid gap-3 md:grid-cols-2"><div className="rounded-xl border border-border-secondary p-3"><div className="text-[9px] uppercase text-text-tertiary">Founder Fit</div>{Object.entries(item.founder_fit?.dimensions || {}).map(([k,v])=><div key={k} className="mt-1 flex justify-between gap-3 text-[10px]"><span className="text-text-secondary">{k}</span><span className={stateClass(v.state)}>{v.state}</span></div>)}</div><div className="rounded-xl border border-border-secondary p-3"><div className="text-[9px] uppercase text-text-tertiary">Structural dimensions</div>{(item.structural_mapper?.dimensions || []).map((x,i)=><div key={i} className="mt-1 flex justify-between gap-3 text-[10px]"><span className="text-text-secondary">{x.dimension}</span><span className={stateClass(x.state)}>{x.state}</span></div>)}</div></div>
      <div className="mt-3 rounded-xl border border-border-secondary p-3"><div className="text-[9px] uppercase text-text-tertiary">Problem ↔ Structural Thesis Mapper</div><div className="mt-2 flex flex-wrap gap-1.5">{(item.structural_relationship_mapper?.nodes || []).map((x,i)=><span key={i} className="rounded-lg border border-border-secondary bg-bg-secondary px-2 py-1 text-[9px] text-text-secondary">{x.type} · {String(x.text || x.id || "UNKNOWN")}</span>)}</div></div>
      <div className="mt-3 rounded-xl border border-border-secondary p-3"><div className="text-[9px] uppercase text-text-tertiary">Wedge Expansion Ladder</div><div className="mt-1 text-[10px] text-text-secondary">Current: {item.wedge_expansion_ladder?.current_wedge?.statement || "UNKNOWN"}</div><div className="mt-1 text-[10px] text-text-secondary">Unlock: {item.wedge_expansion_ladder?.unlock_condition || "UNKNOWN"}</div><div className="mt-1 text-[10px] text-text-secondary">Next: {(item.wedge_expansion_ladder?.possible_next_wedges || []).map(x=>x.wedge).join(" · ") || "UNKNOWN"}</div></div>
    </details>
    <div className="mt-3"><TriggerWatch data={item.promotion_demotion_watch}/></div>
  </article>;
}

function Metric({k,v}:{k:string;v?:string}) { return <div className="rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2"><div className="text-[8px] uppercase tracking-[0.1em] text-text-tertiary">{k}</div><div className="mt-1 text-[10px] font-semibold text-text-primary">{v || "UNKNOWN"}</div></div>; }

export default function DecisionSystem(){
  const [hours,setHours]=useState(10);
  const [cash,setCash]=useState("HIGH");
  const [longTerm,setLongTerm]=useState("HIGH");
  const [selected,setSelected]=useState<string[]>([]);
  const [ask,setAsk]=useState("");
  const [batchText,setBatchText]=useState(`[{"title":"Agent Authority","provenance_type":"MODEL_HYPOTHESIS","source_model":"GPT"},{"title":"Agent Authority","provenance_type":"MODEL_HYPOTHESIS","source_model":"Claude"}]`);
  const [batchError,setBatchError]=useState("");
  const portfolio=useSignalForgeDecisionPortfolio({weekly_hours:hours,cash_need:cash,long_term:longTerm,limit:50});
  const compare=useCompareSignalForgeDecisions();
  const askMutation=useAskSignalForgeDecision();
  const batchMutation=useSignalForgeBenchmarkBatch();
  const data=compare.data || portfolio.data;
  const allocations=data?.resource_allocation?.allocations || [];
  const tracks=data?.track_counts || portfolio.data?.track_counts || {};
  const top=data?.top;
  const selectionSet=useMemo(()=>new Set(selected),[selected]);
  const toggle=(id?:string)=>{if(!id)return;setSelected(v=>v.includes(id)?v.filter(x=>x!==id):[...v,id].slice(-5));};
  const runCompare=()=>compare.mutate({thesis_ids:selected,weekly_hours:hours,cash_need:cash,long_term:longTerm});
  const runAsk=()=>{if(ask.trim().length>=2) askMutation.mutate({q:ask,weekly_hours:hours,cash_need:cash,long_term:longTerm});};
  const runBatch=()=>{try{const rows=JSON.parse(batchText) as SignalForgeBenchmarkHypothesis[];if(!Array.isArray(rows)||!rows.length)throw new Error("請輸入 JSON array");setBatchError("");batchMutation.mutate({hypotheses:rows,run_probe:true});}catch(e){setBatchError(String(e));}};

  return <div className="mx-auto max-w-7xl space-y-5 p-5 lg:p-7">
    <header><div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-txt-info"><Target size={13}/> Part 4 · Opportunity Decision System</div><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-text-primary">只能把時間花在少數事情上，現在先做哪個？</h1><p className="mt-1 max-w-3xl text-xs text-text-secondary">CASH / BOTH / ZIP2 / PARK 是 Founder-facing projection；Published Market Truth、Brain strategic track 與 Part 3 truth authority 都不會被這頁改寫。</p></header>

    <section className="grid gap-3 rounded-2xl border border-border-secondary bg-bg-primary p-4 md:grid-cols-4">
      <label className="text-[10px] text-text-tertiary">本週 Founder 時間<input type="number" min={1} max={80} value={hours} onChange={e=>setHours(Math.max(1,Math.min(80,Number(e.target.value)||10)))} className="mt-1 block w-full rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2 text-xs text-text-primary"/></label>
      <label className="text-[10px] text-text-tertiary">現金需求<select value={cash} onChange={e=>setCash(e.target.value)} className="mt-1 block w-full rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2 text-xs text-text-primary"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
      <label className="text-[10px] text-text-tertiary">長期 bet 重要性<select value={longTerm} onChange={e=>setLongTerm(e.target.value)} className="mt-1 block w-full rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2 text-xs text-text-primary"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
      <div className="flex items-end"><button disabled={selected.length<1 || compare.isPending} onClick={runCompare} className="w-full rounded-xl bg-text-primary px-3 py-2.5 text-xs font-semibold text-bg-primary disabled:opacity-40"><GitCompareArrows size={13} className="mr-1 inline"/>比較已選 {selected.length}</button></div>
    </section>

    {portfolio.isLoading ? <div className="text-xs text-text-tertiary">正在組合 Published decision portfolio…</div> : portfolio.error ? <div className="rounded-xl border border-danger/20 bg-danger/5 p-3 text-xs text-txt-danger">Decision portfolio 載入失敗：{String(portfolio.error)}</div> : null}

    {top ? <section className="rounded-2xl border border-info/20 bg-bg-info/25 p-4"><div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-txt-info"><ArrowUpDown size={12}/> Current first priority</div><div className="mt-2 flex flex-wrap items-center gap-2"><TrackPill track={top.market_track || top.current_track}/><ActionPill action={top.founder_action}/><h2 className="text-lg font-semibold text-text-primary">{top.title}</h2></div><p className="mt-1 text-xs text-text-secondary">{top.rank_explanation?.band} · Revenue {top.revenue_wedge_decision} · Spend {top.existing_spend} · Founder Fit {top.founder_fit?.state}</p></section> : null}

    <section className="grid gap-3 md:grid-cols-4">{["CASH","BOTH","ZIP2","PARK"].map(k=><div key={k} className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><TrackPill track={k}/><div className="mt-2 text-2xl font-semibold text-text-primary">{tracks[k] ?? 0}</div></div>)}</section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="flex items-center gap-2 text-sm font-semibold text-text-primary"><Clock3 size={15}/> Founder Resource Allocation</div><p className="mt-1 text-[10px] text-text-tertiary">這是 advisory time blocks，不會自動排程、花錢或執行。</p><div className="mt-3 grid gap-2 lg:grid-cols-3">{allocations.length ? allocations.map((x,i)=><div key={i} className="rounded-xl border border-border-secondary bg-bg-secondary p-3"><div className="text-[9px] uppercase tracking-[0.1em] text-text-tertiary">{x.bucket}</div><div className="mt-1 text-xs font-semibold text-text-primary">{x.hours}h · {x.title}</div><div className="mt-1 text-[10px] text-text-secondary">{x.why}</div></div>) : <div className="text-xs text-text-tertiary">目前沒有足夠 active direction 可配置。</div>}</div></section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="flex items-center gap-2 text-sm font-semibold text-text-primary"><HelpCircle size={15}/> Ask SignalForge</div><div className="mt-2 flex gap-2"><input value={ask} onChange={e=>setAsk(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")runAsk();}} placeholder="例如：哪些方向同時有 existing spend、paid dissatisfaction、reachable buyer？" className="min-w-0 flex-1 rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2.5 text-xs text-text-primary"/><button onClick={runAsk} disabled={ask.trim().length<2 || askMutation.isPending} className="rounded-xl border border-border-secondary px-4 text-xs font-semibold text-text-primary disabled:opacity-40">問</button></div>{askMutation.data ? <div className="mt-3 rounded-xl bg-bg-secondary p-3"><div className="text-[9px] uppercase text-text-tertiary">{askMutation.data.intent}</div><div className="mt-1 text-xs text-text-secondary">{askMutation.data.answer}</div><div className="mt-2 flex flex-wrap gap-2">{(askMutation.data.matches || []).slice(0,8).map(x=><span key={x.thesis_id} className="rounded-lg border border-border-secondary bg-bg-primary px-2 py-1 text-[10px] text-text-primary">{x.current_track} · {x.title}</span>)}</div></div> : null}</section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="text-sm font-semibold text-text-primary">Benchmark Batch · Synthetic provenance</div><p className="mt-1 text-[10px] text-text-tertiary">最多 60 個 raw hypotheses。多模型想到同一題只算 synthetic convergence，independent market recurrence 永遠是 0，直到真實 probe/evidence 另行驗證。</p><textarea value={batchText} onChange={e=>setBatchText(e.target.value)} className="mt-3 min-h-28 w-full rounded-xl border border-border-secondary bg-bg-secondary p-3 font-mono text-[10px] text-text-primary"/><div className="mt-2 flex items-center gap-3"><button onClick={runBatch} disabled={batchMutation.isPending} className="rounded-xl border border-border-secondary px-4 py-2 text-xs font-semibold text-text-primary disabled:opacity-40">Dedupe → Probe → Lineage → Route</button>{batchError?<span className="text-[10px] text-txt-danger">{batchError}</span>:null}</div>{batchMutation.data?<div className="mt-3 text-[10px] text-text-secondary">Input {batchMutation.data.input_count} → deduped {batchMutation.data.deduped_count} · synthetic recurrence = {String(batchMutation.data.synthetic_convergence_counts_as_market_recurrence)}</div>:null}</section>

    <section><div className="mb-2 flex items-center justify-between"><div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Decision Portfolio</div><h2 className="mt-1 text-lg font-semibold text-text-primary">排名、改變排名的條件、不要再研究什麼</h2></div>{compare.data ? <button onClick={()=>compare.reset()} className="text-[10px] text-txt-info">回完整 Portfolio</button> : null}</div><div className="space-y-3">{(data?.items || []).map(item=><DecisionCard key={item.thesis_id || item.title} item={item} selected={selectionSet.has(item.thesis_id || "")} onToggle={()=>toggle(item.thesis_id)}/>)}</div></section>

    <footer className="rounded-2xl border border-warning/20 bg-warning/5 p-4 text-[10px] text-text-secondary"><div className="flex items-center gap-2 font-semibold text-txt-warning"><ShieldAlert size={13}/> Authority boundary</div><p className="mt-1">Part 4 只做 Founder decision support。Promotion/Demotion 是 review trigger，不是自動 Market Truth mutation；Resource Allocation 也不會自行執行。</p></footer>
  </div>;
}
