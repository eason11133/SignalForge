import { Link } from "react-router-dom";
import { FlaskConical, ShieldCheck, ArrowRight, AlertTriangle, Activity } from "lucide-react";
import { useSignalForgeResearchWorkspace } from "../api/hooks";
import { CardSkeleton } from "../components/common/Skeleton";

function stateTone(state?: string) {
  const s = String(state || "UNKNOWN").toUpperCase();
  if (s === "SUPPORTED") return "text-txt-success border-success/20 bg-bg-success/35";
  if (s === "REFUTED") return "text-danger border-danger/20 bg-bg-danger/35";
  if (s === "PARTIAL" || s === "INSUFFICIENT") return "text-txt-warning border-warning/20 bg-bg-warning/30";
  return "text-text-secondary border-border-secondary bg-bg-secondary";
}

export default function Research() {
  const { data, isLoading, error } = useSignalForgeResearchWorkspace();

  if (isLoading) return <div className="space-y-3"><CardSkeleton /><CardSkeleton /><CardSkeleton /></div>;
  if (error || !data) {
    return <div className="rounded-2xl border border-danger/25 bg-bg-danger px-5 py-4 text-sm text-danger">SignalForge Research Workspace unavailable. Legacy blank research projects are not used as fallback.</div>;
  }

  const rows = data.items || [];
  const marketActions = rows.filter((x) => x.best_next_action?.mode === "MARKET_ACTION").length;
  const founderDiscovery = rows.filter((x) => x.best_next_action?.mode === "FOUNDER_DISCOVERY").length;
  const fatal = rows.filter((x) => x.fatal_gate).length;

  return (
    <div className="max-w-[1480px] mx-auto space-y-5 pb-10">
      <header className="border-b border-border-secondary pb-5">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-text-tertiary"><FlaskConical size={13} /> SignalForge</div>
        <h1 className="mt-2 text-2xl font-semibold text-text-primary">AI 研究進度</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-text-secondary">這裡是 SignalForge 自己在補哪些答案。大部分時間你不用處理；只有研究真的需要真人市場答案時，才會被送回首頁給你。</p>
      </header>

      <section className="grid gap-3 sm:grid-cols-3">
        <Metric label="AI 待研究" value={rows.length} icon={<Activity size={15} />} />
        <Metric label="關鍵阻塞" value={fatal} icon={<AlertTriangle size={15} />} />
        <Metric label="需要真人答案" value={marketActions} icon={<ShieldCheck size={15} />} />
      </section>

      <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">AI 正在查的問題</h2>
            <p className="mt-1 text-xs text-text-secondary">需要 Founder 補答案： {founderDiscovery} · refreshed {data.refreshed_at ? new Date(data.refreshed_at).toLocaleString() : "unknown"}</p>
          </div>
          <div className="rounded-lg border border-border-secondary bg-bg-secondary px-2.5 py-1.5 text-[10px] text-text-tertiary">{data.status || "UNKNOWN"}</div>
        </div>

        {rows.length === 0 ? (
          <div className="py-10 text-center text-sm text-text-secondary">目前沒有 decision-critical research question。0 是合法結果。</div>
        ) : (
          <div className="mt-4 space-y-3">
            {rows.map((row) => {
              const candidateId = undefined;
              const right = row.founder_addressability?.dimensions?.right_to_win?.state || "UNKNOWN";
              const next = row.best_next_action;
              return (
                <article key={row.research_question_id} className="rounded-xl border border-border-secondary bg-bg-secondary/25 p-4">
                  <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full border px-2 py-1 text-[10px] ${stateTone(row.state)}`}>{row.dimension || "UNKNOWN"} · {row.state || "UNKNOWN"}</span>
                        {row.fatal_gate ? <span className="rounded-full border border-danger/20 bg-bg-danger/30 px-2 py-1 text-[10px] text-danger">Fatal gate</span> : null}
                        <span className="text-[10px] text-text-tertiary">VOI {row.voi ?? "—"}</span>
                        <span className="text-[10px] text-text-tertiary">{row.strategic_track || "NEITHER"}</span>
                      </div>
                      <h3 className="mt-2 text-sm font-semibold text-text-primary">{row.representative_title || row.representative_problem || row.thesis_id}</h3>
                      <p className="mt-1 text-xs leading-5 text-text-secondary">{row.action || "No research action"}</p>
                      <div className="mt-3 grid gap-2 sm:grid-cols-3">
                        <Small label="Right-to-win" value={right} />
                        <Small label="Fast validation" value={row.fast_validation?.state || "NOT_READY"} />
                        <Small label="Attempts" value={row.attempts ?? 0} />
                      </div>
                    </div>
                    <div className="xl:w-[280px] rounded-xl border border-border-secondary bg-bg-primary p-3">
                      <div className="text-[9px] uppercase tracking-[0.1em] text-text-tertiary">下一個要補的答案</div>
                      <div className="mt-1 text-xs font-medium text-text-primary">{next?.action || row.action || "HOLD"}</div>
                      <div className="mt-1 text-[10px] leading-4 text-text-tertiary">{next?.reason || "Highest decision-critical open uncertainty."}</div>
                      {row.thesis_id ? <Link to={`/theses/${encodeURIComponent(row.thesis_id)}`} className="mt-3 inline-flex items-center gap-1 text-[11px] text-info hover:underline">看完整判斷 <ArrowRight size={11} /></Link> : null}
                      {candidateId ? <Link to={`/candidates/${candidateId}`} /> : null}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <div className="text-[10px] leading-5 text-text-tertiary">{data.truth_boundary}</div>
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.1em] text-text-tertiary">{icon}{label}</div><div className="mt-2 text-2xl font-semibold text-text-primary">{value}</div></div>;
}

function Small({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border border-border-secondary bg-bg-primary px-3 py-2"><div className="text-[9px] uppercase tracking-[0.08em] text-text-tertiary">{label}</div><div className="mt-1 text-[11px] text-text-primary">{value}</div></div>;
}
