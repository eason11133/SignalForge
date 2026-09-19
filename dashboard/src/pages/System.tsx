import { Activity, Brain, Database, Gauge, ShieldCheck, AlertTriangle } from "lucide-react";
import { useSignalForgeDaily, useSignalForgeStatus, useSignalForgeBrainStatus, useSignalForgeFounderProfile, useSignalForgeOperatingQueue, useSignalForgeMarketActions, useSpendingStatus } from "../api/hooks";
import { CardSkeleton } from "../components/common/Skeleton";

function truth(value: unknown) {
  if (value == null || value === "") return "UNKNOWN";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function System() {
  const daily = useSignalForgeDaily();
  const liveStatus = useSignalForgeStatus();
  const brain = useSignalForgeBrainStatus();
  const profile = useSignalForgeFounderProfile();
  const operating = useSignalForgeOperatingQueue();
  const marketActions = useSignalForgeMarketActions();
  const spend = useSpendingStatus();

  if (daily.isLoading || brain.isLoading) return <div className="space-y-3"><CardSkeleton /><CardSkeleton /><CardSkeleton /></div>;

  const runtime = ((liveStatus.data as any) || daily.data?.runtime || {}) as any;
  const progress = runtime?.progress || {};
  const dispatch = runtime?.dispatch || {};
  const admission = runtime?.last_cycle?.production_admission || progress?.metrics?.production_admission || {};
  const governor = runtime?.last_cycle?.execution_governor || daily.data?.execution_governor || (operating.data as any)?.execution_governor || {};
  const opQueue = daily.data?.operating_queue || (operating.data as any)?.operating_queue || {};
  const routingCoherence = runtime?.last_cycle?.strategic_routing_coherence || daily.data?.strategic_routing_coherence || (operating.data as any)?.strategic_routing_coherence || {};
  const postBrainRouting = runtime?.last_cycle?.post_brain_routing || {};
  const warmCache = runtime?.last_cycle?.warm_cache_readiness || {};
  const discovery = runtime?.last_cycle?.problem_discovery || {};
  const phaseValue = runtime?.last_cycle?.phase_value || {};
  const brainData = brain.data as any;
  const brainStatus = brainData?.brain || {};
  const brainRuntime = brainData?.runtime || {};
  const dbHealthy = Boolean(runtime?.fresh) && !runtime?.last_error;
  const strategic = brainStatus?.strategic_summary || {};
  const calibrationDomains = brainStatus?.market_calibration?.domains || {};

  return (
    <div className="max-w-[1480px] mx-auto space-y-5 pb-10">
      <header className="border-b border-border-secondary pb-5">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-text-tertiary"><Activity size={13} /> Runtime truth</div>
        <h1 className="mt-2 text-2xl font-semibold text-text-primary">SignalForge System</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-text-secondary">只顯示目前 canonical SignalForge runtime、Brain derived runtime、資料新鮮度與實際成本。舊 Agent「Run all」控制不再是 Founder 主線，也不會在這裡假裝代表 SignalForge 狀態。</p>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={<Database size={15} />} label="Production Radar" value={runtime?.status || "UNKNOWN"} sub={runtime?.fresh ? "Fresh" : `Stale · ${runtime?.data_age_hours ?? "?"}h`} ok={dbHealthy} />
        <Metric icon={<Brain size={15} />} label="Brain v2" value={brainStatus?.status || "UNKNOWN"} sub={brainRuntime?.running ? "Refresh running" : `Runtime ${brainRuntime?.status || "UNKNOWN"}`} ok={brainStatus?.status === "PASS" || brainStatus?.status === "PASS_EMPTY"} />
        <Metric icon={<ShieldCheck size={15} />} label="Market calibration" value={truth(brainStatus?.market_calibration?.market_truth || daily.data?.calibration?.status || "UNVALIDATED")} sub="Engineering PASS ≠ market validation" ok={false} />
        <Metric icon={<Gauge size={15} />} label="Recorded AI spend" value={spend.data ? `$${Number((spend.data as any).total_spent_usd || 0).toFixed(4)}` : "UNKNOWN"} sub="Project-local ledger" ok={true} />
      </section>

      {!dbHealthy ? <section className="rounded-2xl border border-warning/25 bg-bg-warning/25 p-4"><div className="flex items-start gap-3"><AlertTriangle size={17} className="mt-0.5 text-txt-warning" /><div><div className="text-sm font-semibold text-text-primary">Production runtime is not healthy/fresh</div><div className="mt-1 text-xs leading-5 text-text-secondary">{runtime?.last_error || "No fresh successful production cycle is available."} Founder surfaces must not infer that API/server-up means DB/data truth is healthy.</div></div></div></section> : null}

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="Production Radar runtime">
          <Row k="status" v={runtime?.status} />
          <Row k="running" v={runtime?.running} />
          <Row k="dispatch status" v={dispatch?.status} />
          <Row k="dispatch persisted status" v={dispatch?.persisted_status} />
          <Row k="dispatch effective reason" v={dispatch?.effective_status_reason} />
          <Row k="dispatch worker alive" v={dispatch?.worker_alive} />
          <Row k="dispatch pid" v={dispatch?.pid} />
          <Row k="dispatch age seconds" v={dispatch?.age_seconds} />
          <Row k="current phase" v={progress?.phase} />
          <Row k="phase started" v={progress?.phase_started_at} />
          <Row k="last heartbeat" v={progress?.last_heartbeat_at} />
          <Row k="heartbeat state" v={progress?.heartbeat_state} danger={progress?.heartbeat_state === "QUIET_OR_STALE" && Boolean(runtime?.running)} />
          <Row k="heartbeat source" v={progress?.heartbeat_source} />
          <Row k="heartbeat age seconds" v={progress?.heartbeat_age_seconds} />
          <Row k="progress state" v={progress?.progress_state} />
          <Row k="observability health" v={progress?.observability_health} danger={progress?.observability_health === "DEGRADED"} />
          <Row k="telemetry error" v={progress?.last_telemetry_error?.error} danger={Boolean(progress?.last_telemetry_error)} />
          <Row k="progress age seconds" v={progress?.progress_age_seconds} />
          <Row k="cycle elapsed seconds" v={progress?.cycle_elapsed_seconds} />
          <Row k="phase elapsed seconds" v={progress?.phase_elapsed_seconds} />
          <Row k="last completed phase" v={progress?.last_completed_phase} />
          <Row k="detail" v={progress?.detail} />
          <Row k="progress" v={progress?.progress} />
          <Row k="last attempt status" v={runtime?.last_attempt_status} danger={runtime?.last_attempt_status === "FAIL"} />
          <Row k="last attempt finished" v={runtime?.last_attempt_finished_at} />
          <Row k="last attempt error" v={runtime?.last_attempt_error} danger={Boolean(runtime?.last_attempt_error)} />
          <Row k="last success" v={runtime?.last_success_at} />
          <Row k="data age hours" v={runtime?.data_age_hours} />
          <Row k="fresh" v={runtime?.fresh} />
          <Row k="next due" v={runtime?.next_due_at} />
          <Row k="last error" v={runtime?.last_error} danger={Boolean(runtime?.last_error)} />
          <Row k="last cycle LLM calls" v={runtime?.last_cycle?.llm_calls} />
          <Row k="last cycle cost TWD" v={runtime?.last_cycle?.llm_cost_twd} />
          <Row k="warm cache readiness" v={warmCache?.status || "UNKNOWN"} />
          <Row k="C02 exact cache hit" v={warmCache?.c02_exact_matrix_hit ?? false} />
          <Row k="shared exact cache hits" v={warmCache?.shared_exact_retrieval_hits ?? 0} />
        </Panel>

        <Panel title="Brain v2 derived authority">
          <Row k="status" v={brainStatus?.status} />
          <Row k="engine" v={brainStatus?.engine_version} />
          <Row k="refreshed" v={brainStatus?.refreshed_at} />
          <Row k="BOTH" v={strategic?.strategic_track_counts?.BOTH ?? 0} />
          <Row k="ZIP2 structural" v={strategic?.strategic_track_counts?.ZIP2_STRUCTURAL ?? 0} />
          <Row k="Fast validation" v={strategic?.strategic_track_counts?.FAST_VALIDATION ?? 0} />
          <Row k="Neither" v={strategic?.strategic_track_counts?.NEITHER ?? 0} />
          <Row k="atomic truth owner" v={brainStatus?.authority?.radar_atomic_claim_truth || "SOLE_OWNER"} />
          <Row k="FrameGraph authority" v={brainStatus?.authority?.framegraph_shadow || "ZERO_PRODUCTION_AUTHORITY"} />
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="Production workload admission">
          <Row k="machine eligible total" v={governor?.machine_eligible_total ?? admission?.active_machine_research ?? "UNKNOWN"} />
          <Row k="bounded machine execution" v={governor?.bounded_machine_workload ?? "UNKNOWN"} />
          <Row k="bounded machine limit" v={governor?.bounded_machine_limit ?? "UNKNOWN"} />
          <Row k="market / Founder actions" v={governor?.market_or_founder_actions ?? 0} />
          <Row k="waiting / parked" v={governor?.waiting_or_parked ?? 0} />
          <Row k="machine case ids" v={governor?.bounded_machine_case_ids ?? []} />
          <Row k="recurrence eligible" v={admission?.recurrence_eligible ?? "UNKNOWN"} />
          <Row k="THESIS_ACTIVE" v={admission?.states?.THESIS_ACTIVE ?? 0} />
          <Row k="RESEARCH_ACTIVE" v={admission?.states?.RESEARCH_ACTIVE ?? 0} />
          <Row k="MONITOR_CONTEXT" v={admission?.states?.MONITOR_CONTEXT ?? 0} />
          <Row k="DEFER_EPHEMERAL" v={admission?.states?.DEFER_EPHEMERAL ?? 0} />
          <Row k="pre-enrichment transient deferred" v={discovery?.pre_enrichment_deferred ?? 0} />
          <Row k="pre-enrichment reasons" v={discovery?.pre_enrichment_deferred_reasons ?? {}} />
          <Row k="zero active legal" v={admission?.zero_active_is_legal ?? true} />
        </Panel>
        <Panel title="Strategic routing coherence">
          <Row k="status" v={routingCoherence?.status || "UNKNOWN"} danger={routingCoherence?.status === "DEGRADED"} />
          <Row k="advisory source" v={postBrainRouting?.brain_advisory_source || "UNKNOWN"} />
          <Row k="advisory status" v={postBrainRouting?.brain_advisory_status || "UNKNOWN"} />
          <Row k="advisory error" v={postBrainRouting?.brain_advisory_error} danger={Boolean(postBrainRouting?.brain_advisory_error)} />
          <Row k="candidate actions" v={routingCoherence?.candidate_actions_total ?? 0} />
          <Row k="actionable checked" v={routingCoherence?.radar_candidates_checked ?? 0} />
          <Row k="matched" v={routingCoherence?.matched ?? 0} />
          <Row k="mismatches" v={routingCoherence?.mismatch_count ?? 0} danger={Number(routingCoherence?.mismatch_count || 0) > 0} />
          <Row k="thesis-only / no Radar row" v={routingCoherence?.thesis_only_or_no_radar_row ?? 0} />
          <Row k="meaning" v="Brain strategy → execution route consistency only; no market-truth authority." />
        </Panel>
        <Panel title="Runtime observability boundary">
          <Row k="progress status" v={progress?.status} />
          <Row k="progress engine" v={progress?.engine_version} />
          <Row k="truth authority" v={progress?.truth_boundary || "RUNTIME_OBSERVABILITY_ONLY"} />
          <Row k="meaning" v="Heartbeat/progress reports execution liveness only; it cannot create or promote market evidence." />
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <Panel title="Operating queue">
          <Row k="machine selected" v={opQueue?.counts?.machine_research ?? opQueue?.machine_research?.length ?? 0} />
          <Row k="machine capacity backlog" v={opQueue?.counts?.machine_research_backlog ?? opQueue?.machine_research_backlog?.length ?? 0} />
          <Row k="machine eligible total" v={opQueue?.counts?.machine_research_eligible_total ?? 0} />
          <Row k="market action" v={opQueue?.market_action?.length ?? 0} />
          <Row k="Founder discovery" v={opQueue?.founder_discovery?.length ?? 0} />
          <Row k="waiting" v={opQueue?.waiting?.length ?? 0} />
          <Row k="parked" v={opQueue?.parked?.length ?? 0} />
          <Row k="monitor" v={opQueue?.monitor?.length ?? 0} />
        </Panel>
        <Panel title="Founder / market action registry">
          <Row k="suggested" v={(marketActions.data as any)?.suggested?.count ?? 0} />
          <Row k="registered" v={(marketActions.data as any)?.registry?.registered ?? 0} />
          <Row k="running" v={(marketActions.data as any)?.registry?.running ?? 0} />
          <Row k="completed" v={(marketActions.data as any)?.registry?.completed ?? 0} />
          <Row k="truth authority" v="ZERO_DIRECT_C01_C14_WRITE" />
        </Panel>
        <Panel title="Phase value telemetry">
          <Row k="phases observed" v={Object.keys(phaseValue || {}).length} />
          <Row k="telemetry" v={phaseValue || {}} />
          <Row k="meaning" v="Time/cost/yield diagnostics only; zero yield never lowers evidence thresholds." />
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <Panel title="Fast Validation calibration">
          <Row k="status" v={calibrationDomains?.fast_validation?.status || "UNVALIDATED"} />
          <Row k="completed outcomes" v={calibrationDomains?.fast_validation?.completed_outcomes ?? 0} />
          <Row k="completed cases" v={calibrationDomains?.fast_validation?.completed_cases ?? 0} />
          <Row k="positive rate" v={calibrationDomains?.fast_validation?.positive_rate ?? "UNVALIDATED"} />
        </Panel>
        <Panel title="Structural / Zip2 calibration">
          <Row k="status" v={calibrationDomains?.structural_opportunity?.status || "UNVALIDATED"} />
          <Row k="structural outcomes" v={calibrationDomains?.structural_opportunity?.completed_structural_outcomes ?? 0} />
          <Row k="readiness" v={calibrationDomains?.structural_opportunity?.readiness || "STRUCTURAL_CHECKPOINT_REGISTRY_REQUIRED"} />
        </Panel>
        <Panel title="Founder addressability calibration">
          <Row k="status" v={calibrationDomains?.founder_addressability?.status || "UNVALIDATED"} />
          <Row k="completed outcomes" v={calibrationDomains?.founder_addressability?.completed_outcomes ?? 0} />
          <Row k="completed cases" v={calibrationDomains?.founder_addressability?.completed_cases ?? 0} />
        </Panel>
      </section>

      <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
        <h2 className="text-sm font-semibold text-text-primary">Founder capability / addressability policy</h2>
        <p className="mt-1 text-xs text-text-secondary">這是 Company Truth input，不是 market truth。AI 只能補 execution throughput；不能補 domain knowledge、buyer access、legitimacy、trust 或 regulation。</p>
        <pre className="mt-3 max-h-[420px] overflow-auto rounded-xl border border-border-secondary bg-bg-secondary/35 p-3 text-[10px] leading-5 text-text-secondary">{JSON.stringify((profile.data as any)?.profile || {}, null, 2)}</pre>
      </section>
    </div>
  );
}

function Metric({ icon, label, value, sub, ok }: { icon: React.ReactNode; label: string; value: string; sub: string; ok: boolean }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.1em] text-text-tertiary">{icon}{label}</div><div className={`mt-2 text-lg font-semibold ${ok ? "text-text-primary" : "text-txt-warning"}`}>{value}</div><div className="mt-1 text-[10px] text-text-tertiary">{sub}</div></div>;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><h2 className="text-sm font-semibold text-text-primary">{title}</h2><div className="mt-3 divide-y divide-border-secondary">{children}</div></div>;
}

function Row({ k, v, danger = false }: { k: string; v: unknown; danger?: boolean }) {
  return <div className="flex items-start justify-between gap-4 py-2 text-xs"><span className="text-text-tertiary">{k}</span><span className={`max-w-[65%] break-words text-right ${danger ? "text-danger" : "text-text-primary"}`}>{truth(v)}</span></div>;
}
