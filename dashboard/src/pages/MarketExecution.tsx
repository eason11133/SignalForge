import { useMemo, useState, type ReactNode } from "react";
import {
  useCaptureSignalForgeMarketOutcome,
  useDesignSignalForgeMarketTest,
  usePreregisterSignalForgeClaimForAction,
  usePreregisterSignalForgeMarketTest,
  usePromoteSignalForgeMarketOutcome,
  useSignalForgeClaimPreregistrationOptions,
  useSignalForgeMarketExecution,
  useSignalForgeMarketLearningCalibration,
  useSignalForgePromotionOptions,
} from "../api/hooks";
import type { SignalForgeMarketActionRecord, SignalForgeMarketTestDesign } from "../api/client";

const arr = (v: unknown) => Array.isArray(v) ? v : [];
const txt = (v: unknown) => typeof v === "string" ? v : v == null ? "—" : String(v);
const num = (v: string) => v.trim() === "" ? undefined : Number(v);

export default function MarketExecution() {
  const execution = useSignalForgeMarketExecution();
  const calibration = useSignalForgeMarketLearningCalibration();
  const designer = useDesignSignalForgeMarketTest();
  const prereg = usePreregisterSignalForgeMarketTest();
  const [design, setDesign] = useState<SignalForgeMarketTestDesign | null>(null);
  const [selectedThesis, setSelectedThesis] = useState("");
  const [maxSample, setMaxSample] = useState("");
  const [maxCost, setMaxCost] = useState("");
  const [currency, setCurrency] = useState("TWD");
  const [successMin, setSuccessMin] = useState("");

  const candidates = execution.data?.candidates || [];
  const rows = execution.data?.registry?.rows || [];
  const open = rows.filter((x) => ["REGISTERED", "RUNNING"].includes(String(x.status || "").toUpperCase()));
  const completed = rows.filter((x) => String(x.status || "").toUpperCase() === "COMPLETED").slice().reverse();

  const runDesign = async (thesisId: string) => {
    setSelectedThesis(thesisId);
    const result = await designer.mutateAsync({ thesis_id: thesisId, max_sample: num(maxSample), max_cost: num(maxCost), cost_currency: currency || undefined });
    setDesign(result);
    setSuccessMin(String(result.success?.decision_rule?.success_min ?? ""));
  };

  const doPreregister = async () => {
    if (!selectedThesis || !design) return;
    await prereg.mutateAsync({
      thesis_id: selectedThesis,
      max_sample: design.max_sample,
      max_cost: design.max_cost ?? undefined,
      cost_currency: design.max_cost_currency || undefined,
      decision_rule: {
        metric: design.success?.decision_rule?.metric,
        success_min: Number(successMin || design.success?.decision_rule?.success_min || 1),
      },
    });
    setDesign(null);
    setSelectedThesis("");
    await execution.refetch();
  };

  return <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 lg:px-7">
    <header className="rounded-2xl border border-border-secondary bg-bg-secondary/40 p-5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Part 6 · Market Execution & Learning</div>
      <h1 className="mt-1 text-2xl font-semibold text-text-primary">讓市場真的回答，而不是再多分析一輪</h1>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-text-secondary">Test → Pre-register → Buyer action → Outcome → explicit Evidence Promotion → Calibration。工程 PASS 不會把 Market Calibration 變成 validated。</p>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        <Pill>Outcome 不能事後改 PASS / FAIL</Pill><Pill>Market Truth promotion 必須明確操作</Pill><Pill>FAIL 不會自動變成市場不存在</Pill>
      </div>
    </header>

    <section className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
      <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
        <div className="flex items-end justify-between gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">1 · Market Test Designer</div><h2 className="mt-1 text-lg font-semibold text-text-primary">從目前值得驗的 thesis 開始</h2></div><span className="text-xs text-text-tertiary">{candidates.length} candidates</span></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <Field label="Max sample（留空用 template）" value={maxSample} onChange={setMaxSample} />
          <Field label="Max cost（不填就 UNKNOWN）" value={maxCost} onChange={setMaxCost} />
          <Field label="Currency" value={currency} onChange={setCurrency} />
        </div>
        <div className="mt-4 space-y-2">
          {candidates.slice(0, 12).map((x) => <button key={x.thesis_id} type="button" onClick={() => runDesign(String(x.thesis_id || ""))} disabled={designer.isPending} className="flex w-full items-center justify-between rounded-xl border border-border-secondary bg-bg-secondary/25 px-3 py-3 text-left hover:bg-bg-secondary/55 disabled:opacity-50">
            <div><div className="text-sm font-medium text-text-primary">{x.title || x.thesis_id}</div><div className="mt-1 text-[10px] text-text-tertiary">Market Track {x.market_track || "—"} · Founder Action {x.founder_action || "—"}</div></div><span className="text-xs text-text-secondary">設計最小測試 →</span>
          </button>)}
          {!candidates.length ? <Empty>目前沒有 Decision System 認為值得進 Founder execution 的方向。</Empty> : null}
        </div>
      </div>

      <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
        <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">6 · Calibration</div>
        <h2 className="mt-1 text-lg font-semibold text-text-primary">系統目前到底學到了多少</h2>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Metric label="Part 6 status" value={calibration.data?.part6_signal_calibration?.status || execution.data?.learning_calibration?.status || "UNVALIDATED"} />
          <Metric label="Eligible outcomes" value={String(calibration.data?.part6_signal_calibration?.eligible_outcomes ?? execution.data?.learning_calibration?.eligible_outcomes ?? 0)} />
          <Metric label="Distinct theses" value={String(calibration.data?.part6_signal_calibration?.distinct_entities ?? execution.data?.learning_calibration?.distinct_entities ?? 0)} />
          <Metric label="General accuracy" value={calibration.data?.general_predictive_accuracy || "UNVALIDATED"} />
        </div>
        <div className="mt-3 rounded-xl border border-warning/20 bg-bg-warning/20 p-3 text-[11px] leading-5 text-text-secondary">只有 prospective、preregistered、quality-eligible 的真 outcome 達到最低樣本與 thesis diversity，且 95% Wilson interval 能把某 feature 與 complement 分開，才允許成為透明 ranking tie-breaker。否則排名不動。</div>
        {(calibration.data?.part6_signal_calibration?.actionable_adjustments || []).slice(0, 5).map((x, i) => <div key={i} className="mt-2 rounded-lg border border-border-secondary p-2 text-[10px] text-text-secondary">{txt(x.feature)}={txt(x.bucket)} → <b>{txt(x.ranking_adjustment)}</b> · n={txt(x.outcomes)}</div>)}
      </div>
    </section>

    {design ? <DesignPreview design={design} successMin={successMin} setSuccessMin={setSuccessMin} onPreregister={doPreregister} pending={prereg.isPending} /> : null}

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">2–5 · Execute → Capture → Promote</div>
      <h2 className="mt-1 text-lg font-semibold text-text-primary">已 Pre-register 的市場測試</h2>
      <div className="mt-4 space-y-4">{open.map((r) => <ExecutionCard key={r.action_id} record={r} />)}{!open.length ? <Empty>目前沒有進行中的 pre-registered test。</Empty> : null}</div>
    </section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <h2 className="text-lg font-semibold text-text-primary">已完成 Outcomes</h2>
      <p className="mt-1 text-xs text-text-tertiary">Outcome history ≠ Market Truth。只有下面明確符合 pre-outcome claim experiment 的項目才可 Promote。</p>
      <div className="mt-4 space-y-3">{completed.slice(0, 20).map((r) => <CompletedCard key={r.action_id} record={r} />)}{!completed.length ? <Empty>還沒有市場 outcome；Calibration 維持 UNVALIDATED 是正確狀態。</Empty> : null}</div>
    </section>
  </div>;
}

function DesignPreview({ design, successMin, setSuccessMin, onPreregister, pending }:{design:SignalForgeMarketTestDesign;successMin:string;setSuccessMin:(v:string)=>void;onPreregister:()=>void;pending:boolean}) {
  const rule=design.success?.decision_rule;
  return <section className="rounded-2xl border border-success/20 bg-bg-success/20 p-4">
    <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-txt-success">Pre-registration preview</div>
    <h2 className="mt-1 text-lg font-semibold text-text-primary">{design.title}</h2>
    <div className="mt-3 grid gap-3 lg:grid-cols-3"><Box title="HYPOTHESIS">{design.hypothesis}</Box><Box title="TARGET">{design.target}</Box><Box title="TEST">{design.test?.instruction}</Box></div>
    <div className="mt-3 grid gap-3 lg:grid-cols-3"><Box title="SUCCESS">{design.success?.criterion}<div className="mt-2 text-[10px] text-text-tertiary">Metric: {rule?.metric}</div><input value={successMin} onChange={(e)=>setSuccessMin(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2 py-1.5 text-xs" aria-label="success threshold" /></Box><Box title="FAILURE">{design.failure?.criterion}</Box><Box title="INCONCLUSIVE">{design.inconclusive?.criterion}</Box></div>
    <div className="mt-3 grid gap-3 md:grid-cols-2"><Box title="BUYER / OUTREACH"><div>WHO · {design.buyer_outreach_pack?.who}</div><div className="mt-1">WHERE · {(design.buyer_outreach_pack?.where || []).join(" · ")}</div><div className="mt-2 text-[10px] text-text-tertiary">Do not say</div>{(design.buyer_outreach_pack?.what_not_to_say || []).slice(0,3).map((x)=><div key={x} className="mt-1">• {x}</div>)}</Box><Box title="BOUNDARY"><div>Max sample · {design.max_sample}</div><div>Max cost · {design.max_cost == null ? "NOT SET" : `${design.max_cost} ${design.max_cost_currency || ""}`}</div><div className="mt-2">Atomic claims · {(design.atomic_promotion_hint?.claims || []).join(", ") || "none"}</div><div className="mt-2 text-[10px] text-txt-warning">要進 Market Truth 必須在 outcome 前另做 claim-specific preregistration。</div></Box></div>
    <button type="button" disabled={pending} onClick={onPreregister} className="mt-4 rounded-xl bg-text-primary px-4 py-2.5 text-xs font-semibold text-bg-primary disabled:opacity-50">確認並 Pre-register</button>
  </section>;
}

function ExecutionCard({ record }:{record:SignalForgeMarketActionRecord}) {
  const capture=useCaptureSignalForgeMarketOutcome();
  const claimOptions=useSignalForgeClaimPreregistrationOptions(record.action_id);
  const claimPrereg=usePreregisterSignalForgeClaimForAction();
  const rule=record.decision_rule || (record.part6_test_design as SignalForgeMarketTestDesign | undefined)?.success?.decision_rule;
  const metric=rule?.metric || "target_behavior_count";
  const [contacted,setContacted]=useState(""); const [metricValue,setMetricValue]=useState("");
  const [actors,setActors]=useState(""); const [refs,setRefs]=useState(""); const [behavior,setBehavior]=useState(""); const [findings,setFindings]=useState(""); const [amount,setAmount]=useState(""); const [currency,setCurrency]=useState("TWD"); const [actualCost,setActualCost]=useState(""); const [actualCostCurrency,setActualCostCurrency]=useState(String(record.max_cost_currency || "TWD"));
  const options=arr((claimOptions.data as {items?:unknown[]}|undefined)?.items) as Array<{case_id?:number;claim_code?:string;already_pending?:boolean}>;
  const paid=["PAID_PILOT","PAID_PILOT_OR_PREORDER_TEST","PREORDER"].includes(String(record.action_type||"").toUpperCase());
  const submit=()=>capture.mutate({actionId:record.action_id,payload:{outcome_counts:{contacted:Number(contacted||0),[metric]:Number(metricValue||0)},actor_labels:actors.split("\n").map(x=>x.trim()).filter(Boolean),evidence_refs:refs.split("\n").map(x=>x.trim()).filter(Boolean),observed_behavior:behavior,decision_relevant_findings:findings,...(paid?{amount:Number(amount||0),currency}: {}),...(record.max_cost != null ? {actual_cost:Number(actualCost||0),actual_cost_currency:actualCostCurrency}: {})}});
  return <div className="rounded-xl border border-border-secondary bg-bg-secondary/20 p-3">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="text-sm font-semibold text-text-primary">{record.part6_test_design && typeof record.part6_test_design === "object" ? (record.part6_test_design as SignalForgeMarketTestDesign).title : record.thesis_id}</div><div className="mt-1 text-[10px] text-text-tertiary">{record.action_type} · sample {record.sample_target} · frozen metric {metric} ≥ {rule?.success_min ?? "?"}</div></div><Pill>PREREGISTERED</Pill></div>
    {options.length ? <div className="mt-3 rounded-lg border border-info/20 p-2"><div className="text-[10px] font-medium text-text-secondary">Atomic claim preregistration（一定要在 outcome 前）</div><div className="mt-2 flex flex-wrap gap-2">{options.map((x)=><button type="button" disabled={claimPrereg.isPending || x.already_pending} key={`${x.case_id}-${x.claim_code}`} onClick={()=>claimPrereg.mutate({actionId:record.action_id,payload:{case_id:Number(x.case_id),claim_code:String(x.claim_code)}})} className="rounded-lg border border-border-secondary px-2 py-1 text-[10px] disabled:opacity-50">Case {x.case_id} · {x.claim_code} {x.already_pending?"✓":"Pre-register"}</button>)}</div></div> : null}
    <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4"><Field label="Observed / contacted" value={contacted} onChange={setContacted}/><Field label={`${metric}`} value={metricValue} onChange={setMetricValue}/><Field label="Actors（每行一個）" value={actors} onChange={setActors}/><Field label="Evidence refs（每行一個）" value={refs} onChange={setRefs}/></div>
    <div className="mt-2 grid gap-2 md:grid-cols-2"><TextArea label="Observed behavior" value={behavior} onChange={setBehavior}/><TextArea label="Decision-relevant findings" value={findings} onChange={setFindings}/></div>
    {paid?<div className="mt-2 grid gap-2 sm:grid-cols-2"><Field label="Actual paid amount" value={amount} onChange={setAmount}/><Field label="Currency" value={currency} onChange={setCurrency}/></div>:null}
    {record.max_cost != null?<div className="mt-2 grid gap-2 sm:grid-cols-2"><Field label={`Actual test cost (max ${record.max_cost})`} value={actualCost} onChange={setActualCost}/><Field label="Actual cost currency" value={actualCostCurrency} onChange={setActualCostCurrency}/></div>:null}
    <div className="mt-3 flex items-center justify-between gap-3"><div className="text-[10px] text-text-tertiary">SignalForge 會照 frozen rule 算 PASS / FAIL / INCONCLUSIVE；這裡沒有 result dropdown。</div><button type="button" onClick={submit} disabled={capture.isPending} className="rounded-lg bg-text-primary px-3 py-2 text-[11px] font-medium text-bg-primary disabled:opacity-50">記錄 Outcome</button></div>
  </div>;
}

function CompletedCard({record}:{record:SignalForgeMarketActionRecord}) {
  const promotion=useSignalForgePromotionOptions(record.action_id);
  const promote=usePromoteSignalForgeMarketOutcome();
  const opts=promotion.data?.items || [];
  const counts=useMemo(()=>record.observations && typeof record.observations==="object" ? (record.observations.outcome_counts as Record<string,unknown>|undefined) : undefined,[record.observations]);
  return <div className="rounded-xl border border-border-secondary p-3"><div className="flex items-center justify-between gap-2"><div><div className="text-sm font-medium text-text-primary">{record.action_type} · {record.result}</div><div className="mt-1 text-[10px] text-text-tertiary">{record.action_id} · {record.completed_at}</div></div><Pill>{record.outcome_quality?.eligible?"CALIBRATION ELIGIBLE":"RECORDED ONLY"}</Pill></div><div className="mt-2 text-[11px] text-text-secondary">Counts · {counts?JSON.stringify(counts):"—"}</div>{opts.length?<div className="mt-3 rounded-lg border border-warning/20 bg-bg-warning/15 p-2"><div className="text-[10px] font-medium text-txt-warning">Eligible Evidence Promotion · Founder explicit action required</div><div className="mt-2 flex flex-wrap gap-2">{opts.map((x)=><button type="button" key={x.experiment_id} disabled={promote.isPending} onClick={()=>promote.mutate({actionId:record.action_id,payload:{experiment_id:String(x.experiment_id)}})} className="rounded-lg border border-warning/30 px-2 py-1.5 text-[10px] text-text-primary">Promote {x.claim_code} via {x.experiment_id}</button>)}</div></div>:<div className="mt-2 text-[10px] text-text-tertiary">{promotion.data?.status || "No matching pre-outcome claim experiment — outcome stays calibration/history only."}</div>}</div>;
}

function Field({label,value,onChange}:{label:string;value:string;onChange:(v:string)=>void}){return <label className="text-[10px] text-text-tertiary">{label}<input value={value} onChange={(e)=>onChange(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary"/></label>}
function TextArea({label,value,onChange}:{label:string;value:string;onChange:(v:string)=>void}){return <label className="text-[10px] text-text-tertiary">{label}<textarea value={value} onChange={(e)=>onChange(e.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary"/></label>}
function Metric({label,value}:{label:string;value:string}){return <div className="rounded-xl border border-border-secondary bg-bg-secondary/25 p-3"><div className="text-[9px] uppercase tracking-[0.1em] text-text-tertiary">{label}</div><div className="mt-1 break-words text-sm font-semibold text-text-primary">{value}</div></div>}
function Box({title,children}:{title:string;children:ReactNode}){return <div className="rounded-xl border border-border-secondary bg-bg-primary/70 p-3"><div className="text-[9px] font-semibold tracking-[0.12em] text-text-tertiary">{title}</div><div className="mt-2 text-xs leading-5 text-text-secondary">{children}</div></div>}
function Pill({children}:{children:ReactNode}){return <span className="rounded-full border border-border-secondary bg-bg-secondary/50 px-2 py-1 text-[9px] font-medium text-text-secondary">{children}</span>}
function Empty({children}:{children:ReactNode}){return <div className="rounded-xl border border-dashed border-border-secondary p-4 text-xs text-text-tertiary">{children}</div>}
