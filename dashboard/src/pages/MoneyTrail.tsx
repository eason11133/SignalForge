import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, BadgeDollarSign, CheckCircle2, Copy, Search, ShieldCheck, Skull, Target, XCircle } from "lucide-react";
import {
  useProbeSignalForgeFounderIdea,
  useFalsifySignalForge,
  useSignalForgeEvidenceReplay,
  useRegisterSignalForgeMarketAction,
  useCompleteSignalForgeMarketAction,
  useSignalForgeMarketActions,
  useSignalForgeMoneyTrails,
} from "../api/hooks";
import type { SignalForgeFounderIdeaProbe, SignalForgeFounderIdeaSourceHealth, SignalForgeFounderIdeaTrace, SignalForgeMarketActionRecord, SignalForgeMoneyTrail, SignalForgeMoneyTrailEvidence } from "../api/client";
import { CardSkeleton } from "../components/common/Skeleton";

const spendLabels: Record<string, string> = {
  VENDOR_SPEND: "軟體 / Vendor 費",
  LABOR_SPEND: "內部人力成本",
  CONTRACTOR_SPEND: "外包 / 顧問成本",
  REWORK_COST: "返工成本",
  RISK_COST: "風險 / 事故成本",
  LOST_REVENUE: "流失收入 / 延誤成本",
};

function decisionMeta(raw?: string) {
  const v = String(raw || "NOT_NOW").toUpperCase();
  if (v === "TRY_NOW") return { label: "現在就值得測第一筆錢", tone: "border-success/30 bg-bg-success text-txt-success" };
  if (v === "INVESTIGATE") return { label: "值得追這筆錢", tone: "border-info/30 bg-bg-info text-txt-info" };
  if (v === "KILL") return { label: "先砍掉", tone: "border-danger/25 bg-bg-danger text-danger" };
  return { label: "現在先不要做", tone: "border-border-secondary bg-bg-secondary text-text-secondary" };
}

function stateText(raw?: string) {
  const v = String(raw || "UNKNOWN").toUpperCase();
  const map: Record<string, string> = {
    STRONG: "強",
    PARTIAL: "有一些",
    SUPPORTED: "有支持",
    INSUFFICIENT: "還不夠",
    UNKNOWN: "不知道",
    REACHABLE: "可直接接觸",
    BRIDGEABLE: "有機會接觸",
    NO: "目前碰不到",
    REFUTED: "被反證",
    LOW: "低",
    LOW_TO_MEDIUM: "低到中",
    MEDIUM: "中",
    HIGH: "高",
  };
  return map[v] || v.replaceAll("_", " ");
}

function evidenceGrade(raw?: string) {
  const v = String(raw || "UNKNOWN").toUpperCase();
  if (v === "OBSERVED") return "直接觀察到";
  if (v === "SUPPORTED_ESTIMATE") return "有支持的估計";
  if (v === "INFERRED") return "推論";
  return "未知";
}

function shortTitle(trail: SignalForgeMoneyTrail) {
  const segment = trail.buyer_segment?.label;
  const decision = decisionMeta(trail.revenue_wedge?.decision).label;
  if (segment && !segment.includes("尚未")) return `${segment} · ${decision}`;
  return trail.title || trail.problem || "未命名方向";
}

function copy(text?: string) {
  if (!text) return;
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

export function MoneyTrailPanel({ trail, compact = false }: { trail: SignalForgeMoneyTrail; compact?: boolean }) {
  const meta = decisionMeta(trail.revenue_wedge?.decision);
  const buckets = trail.current_spend?.buckets || {};
  const spendRows = Object.entries(buckets)
    .map(([bucket, rows]) => ({ bucket, rows: rows || [] }))
    .filter((x) => x.rows.length > 0);
  const test = trail.cheapest_test;
  const playbook = trail.founder_playbook;

  return (
    <article className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-7">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 max-w-3xl">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Money Trail</div>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-text-primary">{shortTitle(trail)}</h2>
          {trail.problem ? <p className="mt-2 text-sm leading-6 text-text-secondary line-clamp-3">{trail.problem}</p> : null}
        </div>
        <span className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold ${meta.tone}`}>{meta.label}</span>
      </div>

      {trail.status === "NO_RELATED_PUBLISHED_EVIDENCE" ? (
        <div className="mt-5 rounded-2xl border border-warning/25 bg-bg-warning p-4">
          <div className="text-sm font-medium text-text-primary">目前資料庫沒有足夠直接證據</div>
          <p className="mt-1 text-xs leading-5 text-text-secondary">這不是壞答案。SignalForge 不會因為你輸入一個方向就自己補出買家、預算或 WTP。</p>
        </div>
      ) : null}

      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Fact label="最值得打的買家" value={trail.buyer_segment?.label || "還不知道"} />
        <Fact label="既存支出" value={stateText(trail.revenue_wedge?.existing_spend)} />
        <Fact label="買家可達性" value={stateText(trail.revenue_wedge?.buyer_reachability)} />
        <Fact label="付費後仍不滿" value={`${trail.paid_dissatisfaction?.count || 0} 筆高價值訊號`} />
      </div>

      <section className="mt-6">
        <div className="flex items-center gap-2"><BadgeDollarSign size={16} className="text-success" /><h3 className="text-sm font-semibold text-text-primary">錢現在花在哪</h3></div>
        {spendRows.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-border-secondary bg-bg-secondary/30 p-4 text-xs leading-5 text-text-secondary">目前沒有足夠 Published evidence 證明一筆可截取的既存支出。先別做產品。</div>
        ) : (
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {spendRows.map(({ bucket, rows }) => <SpendBucket key={bucket} bucket={bucket} rows={rows} />)}
          </div>
        )}
      </section>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
          <h3 className="text-sm font-semibold text-text-primary">誰今天正在拿這筆錢</h3>
          {(trail.money_recipients_today || []).length ? (
            <div className="mt-3 space-y-2">
              {(trail.money_recipients_today || []).map((x, i) => <div key={`${x.recipient}-${i}`} className="rounded-xl bg-bg-primary px-3 py-2.5 text-xs text-text-secondary"><span className="font-medium text-text-primary">{x.recipient}</span><div className="mt-1 text-[10px] text-text-tertiary">{x.type}</div></div>)}
            </div>
          ) : <p className="mt-3 text-xs leading-5 text-text-secondary">目前還不知道錢實際流向哪個 vendor / 人力 / 外包角色。</p>}
        </section>

        <section className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
          <h3 className="text-sm font-semibold text-text-primary">已經花錢還在不爽什麼</h3>
          {(trail.paid_dissatisfaction?.items || []).length ? (
            <div className="mt-3 space-y-2">
              {(trail.paid_dissatisfaction?.items || []).slice(0, 4).map((x, i) => <EvidenceMini key={`${x.source_family_key}-${i}`} row={x} />)}
            </div>
          ) : <p className="mt-3 text-xs leading-5 text-text-secondary">目前沒有找到「已經付錢 + 仍有未解問題」的 Published evidence。這一格不能硬補。</p>}
        </section>
      </div>

      <section className="mt-6 rounded-2xl border border-info/20 bg-bg-info/20 p-5">
        <div className="flex items-center gap-2"><Target size={16} className="text-info" /><h3 className="text-sm font-semibold text-text-primary">我們可能截哪一筆錢</h3></div>
        <p className="mt-3 text-sm leading-6 text-text-primary">{trail.possible_revenue_wedge?.statement || "目前沒有可辯護的 revenue wedge。"}</p>
        <p className="mt-2 text-[11px] leading-5 text-text-secondary">{trail.revenue_wedge?.rationale}</p>
      </section>

      {test ? (
        <section className="mt-6 rounded-3xl border border-success/25 bg-bg-success/40 p-5 md:p-6">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-txt-success">今天就做這個</div>
          <h3 className="mt-2 text-lg font-semibold text-text-primary">{test.instruction}</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <SignalBox good title="繼續條件" value={test.success_signal || "取得真實支持訊號"} />
            <SignalBox title="停手條件" value={test.failure_signal || "限定樣本後沒有支持訊號"} />
          </div>
        </section>
      ) : null}

      {!compact && playbook ? (
        <section className="mt-6 rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
          <div className="flex items-center justify-between gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Founder Playbook</div><h3 className="mt-1 text-base font-semibold text-text-primary">不用問我，照這個做</h3></div><span className="rounded-full bg-bg-secondary px-2.5 py-1 text-[10px] text-text-secondary">目標 {playbook.sample_target || 10} 人</span></div>
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <PlaybookBlock title="去哪裡找人">
              <ol className="space-y-2 text-xs leading-5 text-text-secondary">{(playbook.channels || []).map((x, i) => <li key={i}>{i + 1}. {x}</li>)}</ol>
            </PlaybookBlock>
            <PlaybookBlock title="第一句怎麼講" action={<button type="button" onClick={() => copy(playbook.outreach_message)} className="inline-flex items-center gap-1 text-[10px] text-info"><Copy size={11} />複製</button>}>
              <p className="text-xs leading-5 text-text-secondary">{playbook.outreach_message}</p>
            </PlaybookBlock>
            <PlaybookBlock title="只問這 5 題">
              <ol className="space-y-2 text-xs leading-5 text-text-secondary">{(playbook.questions || []).map((x, i) => <li key={i}>{i + 1}. {x}</li>)}</ol>
            </PlaybookBlock>
            <PlaybookBlock title="什麼時候才提付費">
              <p className="text-xs leading-5 text-text-secondary">{playbook.offer_rule}</p>
            </PlaybookBlock>
          </div>
        </section>
      ) : null}

      {!compact ? <TrustInspector trail={trail} /> : null}

      {trail.matched_candidates?.length ? (
        <details className="mt-5 rounded-2xl border border-border-secondary bg-bg-secondary/20 px-4 py-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-text-secondary">這次 probe 是從哪些既有案例找到的</summary>
          <div className="mt-3 space-y-2 border-t border-border-secondary pt-3">{trail.matched_candidates.map((x) => <div key={x.candidate_id} className="text-xs text-text-secondary">Candidate {x.candidate_id} · {x.title} · match {x.match_score}</div>)}</div>
        </details>
      ) : null}
    </article>
  );
}


function dispositionMeta(raw?: string) {
  const v = String(raw || "CONTINUE").toUpperCase();
  if (v === "KILL") return { label: "KILL 已觸發", cls: "border-danger/25 bg-bg-danger text-danger" };
  if (v === "ADVANCE") return { label: "ADVANCE 已觸發", cls: "border-success/25 bg-bg-success text-txt-success" };
  if (v === "PARK") return { label: "PARK 已觸發", cls: "border-warning/25 bg-bg-warning text-txt-warning" };
  return { label: "目前繼續查", cls: "border-border-secondary bg-bg-secondary text-text-secondary" };
}

function TrustInspector({ trail }: { trail: SignalForgeMoneyTrail }) {
  const falsify = useFalsifySignalForge();
  const realThesisId = trail.thesis_id && !trail.thesis_id.startsWith("probe:") ? trail.thesis_id : "";
  const replay = useSignalForgeEvidenceReplay(realThesisId, Boolean(realThesisId));
  const result = falsify.data;
  const kill = result?.fresh_counterevidence_search;
  const disposition = result?.published_disposition;
  const dispMeta = dispositionMeta(disposition?.current_disposition);
  const replayData = result?.evidence_replay || replay.data;
  const sourceRuns = kill?.source_runs || [];
  const candidates = kill?.candidates || [];

  return <section className="mt-6 rounded-3xl border border-danger/15 bg-bg-primary p-5 md:p-6">
    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div className="max-w-3xl">
        <div className="flex items-center gap-2"><Skull size={15} className="text-danger" /><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-danger">Try to Kill It</div></div>
        <h3 className="mt-2 text-base font-semibold text-text-primary">先找它為什麼不值得做</h3>
        <p className="mt-1 text-xs leading-5 text-text-secondary">這會專門搜尋「現有方案已夠好、沒預算／不值得付、切換／信任成本太高、失敗市場嘗試」等反方線索。Fresh 結果永遠只是 <span className="font-semibold">UNVALIDATED counterevidence candidate</span>，不會直接把 Published claim 改成反證。</p>
      </div>
      <button type="button" disabled={falsify.isPending} onClick={() => falsify.mutate({ title: trail.title || trail.problem || "SignalForge thesis", description: trail.problem || "", ...(realThesisId ? { thesis_id: realThesisId } : {}) })} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-danger/25 bg-bg-danger px-4 py-3 text-xs font-semibold text-danger disabled:opacity-40">{falsify.isPending ? "正在找反證…" : "Try to Kill It"}<Search size={13} /></button>
    </div>

    {falsify.error ? <div className="mt-4 rounded-2xl border border-danger/25 bg-bg-danger p-4 text-xs text-danger">反證搜尋失敗：{String(falsify.error)}</div> : null}

    {result ? <div className="mt-5 space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] text-text-tertiary">Published disposition</div><div className={`mt-2 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold ${dispMeta.cls}`}>{dispMeta.label}</div><p className="mt-3 text-[10px] leading-5 text-text-secondary">{disposition?.basis || "—"}</p></div>
        <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] text-text-tertiary">Falsification coverage</div><div className="mt-2 text-sm font-semibold text-text-primary">{kill?.coverage || "FAILED"}</div><p className="mt-3 text-[10px] leading-5 text-text-secondary">{kill?.message}</p></div>
        <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] text-text-tertiary">反證候選</div><div className="mt-2 text-2xl font-semibold text-text-primary">{kill?.candidate_count || 0}</div><p className="mt-2 text-[10px] leading-5 text-text-secondary">Fresh traces 不能觸發 KILL / ADVANCE / PARK。只有 Published truth 可以。</p></div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
          <div className="flex items-center gap-2"><AlertTriangle size={13} className="text-txt-warning" /><div className="text-xs font-semibold text-text-primary">Search coverage / failure visibility</div></div>
          <div className="mt-3 max-h-64 space-y-2 overflow-auto">{sourceRuns.length ? sourceRuns.map((row, i) => { const meta = sourceStatusMeta(row.status); return <div key={`${row.theme}-${row.source}-${i}`} className="rounded-xl bg-bg-primary px-3 py-2.5"><div className="flex items-center justify-between gap-3"><div className="min-w-0"><div className="truncate text-[10px] font-semibold text-text-primary">{row.source || "source"}</div><div className="mt-0.5 truncate text-[9px] text-text-tertiary">{row.theme || "counter search"}</div></div><div className={`shrink-0 text-[10px] font-semibold ${meta.cls}`}>{meta.label}</div></div>{row.error ? <div className="mt-1 truncate text-[9px] text-text-tertiary">{row.error}</div> : null}</div>; }) : <div className="text-xs text-text-secondary">沒有 coverage 紀錄。</div>}</div>
          <p className="mt-3 text-[10px] leading-5 text-text-tertiary">No counterevidence found in successful searches ≠ no counterevidence exists.</p>
        </div>

        <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
          <div className="text-xs font-semibold text-text-primary">最值得回頭驗證的反證候選</div>
          <div className="mt-3 max-h-64 space-y-2 overflow-auto">{candidates.length ? candidates.slice(0, 8).map((row, i) => <div key={`${row.url || row.title}-${i}`} className="rounded-xl bg-bg-primary p-3"><div className="flex flex-wrap gap-1.5">{(row.counterevidence_categories || []).map((x) => <span key={x} className="rounded-full bg-bg-danger px-2 py-0.5 text-[8px] font-semibold text-danger">{x.replaceAll("_", " ")}</span>)}<span className="rounded-full bg-bg-warning px-2 py-0.5 text-[8px] font-semibold text-txt-warning">UNVALIDATED</span></div><div className="mt-2 text-[11px] font-medium leading-5 text-text-primary">{row.title}</div>{row.excerpt ? <p className="mt-1 line-clamp-3 text-[10px] leading-5 text-text-secondary">{row.excerpt}</p> : null}{row.url ? <a href={row.url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[9px] text-info hover:underline">看來源</a> : null}</div>) : <div className="text-xs leading-5 text-text-secondary">成功搜尋裡沒有命中反證 cue。這不是「沒有反證」的證明。</div>}</div>
        </div>
      </div>

      {disposition?.conditions ? <div className="grid gap-3 md:grid-cols-3">{(["ADVANCE", "KILL", "PARK"] as const).map((key) => <div key={key} className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold text-text-primary">{key} IF</div><p className="mt-2 text-[10px] leading-5 text-text-secondary">{disposition.conditions?.[key] || "—"}</p></div>)}</div> : null}
    </div> : null}

    {realThesisId ? <details className="mt-5 rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
      <summary className="cursor-pointer list-none"><div className="flex items-center gap-2"><ShieldCheck size={14} className="text-info" /><span className="text-xs font-semibold text-text-primary">Evidence Replay · Why do you believe this?</span></div></summary>
      {replay.isLoading && !replayData ? <div className="mt-3 text-xs text-text-tertiary">重播 Published evidence…</div> : replay.error && !replayData ? <div className="mt-3 text-xs text-danger">Evidence Replay 讀不到。</div> : replayData ? <div className="mt-4 border-t border-border-secondary pt-4">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5"><FastProbeStat label="Validated links" value={replayData.summary?.validated_evidence_links || 0} /><FastProbeStat label="Supporting" value={replayData.summary?.supporting || 0} /><FastProbeStat label="Contradicting" value={replayData.summary?.contradicting || 0} /><FastProbeStat label="Insufficient" value={replayData.summary?.insufficient || 0} /><FastProbeStat label="Unknown claims" value={replayData.summary?.unknown_claims || 0} /></div>
        <div className="mt-4 space-y-2">{(replayData.claims || []).map((claim) => <details key={claim.claim_code} className="rounded-xl bg-bg-primary p-3"><summary className="cursor-pointer list-none"><div className="flex items-center justify-between gap-3"><div className="text-[11px] font-semibold text-text-primary">{claim.claim_code} · {claim.state}</div><div className="text-[9px] text-text-tertiary">+{claim.supporting || 0} / −{claim.contradicting || 0} · independent {claim.independent_source_families || 0}</div></div>{claim.statement ? <div className="mt-1 text-[10px] leading-5 text-text-secondary">{claim.statement}</div> : null}</summary><div className="mt-3 space-y-2 border-t border-border-secondary pt-3">{(claim.evidence || []).length ? (claim.evidence || []).map((ev, i) => <div key={`${ev.source_url || ev.source_title}-${i}`} className="rounded-lg bg-bg-secondary/30 p-2.5"><div className="text-[9px] font-semibold text-text-tertiary">{ev.stance} · {ev.source_type || "source"} · validated</div><div className="mt-1 text-[10px] leading-5 text-text-secondary">{ev.excerpt || ev.source_title || "No excerpt"}</div>{ev.source_url ? <a href={ev.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[9px] text-info">原始來源</a> : null}</div>) : <div className="text-[10px] text-text-tertiary">這個 Published claim 目前沒有 validated evidence link 可 replay。</div>}</div></details>)}</div>
        <div className="mt-3 text-[9px] leading-4 text-text-tertiary">{replayData.search_coverage?.message}</div>
      </div> : null}
    </details> : null}
  </section>;
}


function sourceStatusMeta(raw?: string) {
  const v = String(raw || "FAILED").toUpperCase();
  if (v === "SUCCESS") return { label: "成功", cls: "text-txt-success" };
  if (v === "RATE_LIMITED") return { label: "限流", cls: "text-txt-warning" };
  return { label: "失敗", cls: "text-danger" };
}

function FastProbeStat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] text-text-tertiary">{label}</div><div className="mt-1 text-xl font-semibold text-text-primary">{value}</div></div>;
}

function SourceHealthRow({ row }: { row: SignalForgeFounderIdeaSourceHealth }) {
  const meta = sourceStatusMeta(row.status);
  return <div className="flex items-center justify-between gap-4 rounded-xl bg-bg-primary px-3 py-2.5"><div className="min-w-0"><div className="truncate text-[11px] font-medium text-text-primary">{row.source || "source"}</div>{row.error ? <div className="mt-0.5 truncate text-[10px] text-text-tertiary">{row.error}</div> : null}</div><div className="shrink-0 text-right"><div className={`text-[10px] font-semibold ${meta.cls}`}>{meta.label}</div><div className="mt-0.5 text-[10px] text-text-tertiary">{row.count || 0} results</div></div></div>;
}

function FastTrace({ trace }: { trace: SignalForgeFounderIdeaTrace }) {
  const signals = trace.signals || {};
  const badges = [
    (signals.pain || []).length ? "pain" : "",
    (signals.workaround || []).length ? "workaround" : "",
    (signals.paid || []).length ? "paid" : "",
    (signals.dissatisfaction || []).length ? "dissatisfaction" : "",
  ].filter(Boolean);
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-3.5"><div className="flex flex-wrap items-center gap-2"><span className="text-[10px] font-semibold text-text-tertiary">{trace.source || "source"}</span><span className="rounded-full bg-bg-warning px-2 py-0.5 text-[9px] font-semibold text-txt-warning">未驗證 trace</span>{badges.map((x) => <span key={x} className="rounded-full bg-bg-secondary px-2 py-0.5 text-[9px] text-text-secondary">{x}</span>)}</div><div className="mt-2 text-xs font-medium leading-5 text-text-primary">{trace.title || "Untitled"}</div>{trace.excerpt ? <p className="mt-1 line-clamp-3 text-[10px] leading-5 text-text-secondary">{trace.excerpt}</p> : null}{trace.url ? <a href={trace.url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[10px] text-info hover:underline">看原始來源</a> : null}</div>;
}

function FounderIdeaResult({ result }: { result: SignalForgeFounderIdeaProbe }) {
  const fast = result.fast_probe || {};
  const frontier = result.decision_frontier || {};
  const trail = result.published_money_trail;
  const sourceHealth = fast.source_health || [];
  const traces = fast.top_traces || [];
  const coverage = String(fast.coverage || "FAILED").toUpperCase();
  return <div className="mt-5 space-y-5">
    <section className="rounded-3xl border border-info/25 bg-bg-info/15 p-5 md:p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between"><div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-info">Fast Reality Check · 0 AI API</div><h2 className="mt-1 text-lg font-semibold text-text-primary">先看市場痕跡，不先編市場故事</h2><p className="mt-1 max-w-3xl text-xs leading-5 text-text-secondary">這層是剛剛從公開來源找到的搜尋 trace，全部是 UNVALIDATED。它可以告訴我們下一步查什麼，但不能升格成 Market Truth。</p></div><span className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold ${coverage === "FAILED" ? "border-danger/25 bg-bg-danger text-danger" : coverage === "PARTIAL" ? "border-warning/25 bg-bg-warning text-txt-warning" : "border-success/25 bg-bg-success text-txt-success"}`}>{coverage === "FAILED" ? "搜尋覆蓋失敗" : coverage === "PARTIAL" ? "部分來源成功" : "設定來源皆成功"}</span></div>
      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6"><FastProbeStat label="Problem discussions" value={fast.problem_discussions || 0} /><FastProbeStat label="Firsthand pain" value={fast.firsthand_pain || 0} /><FastProbeStat label="Workarounds" value={fast.workarounds || 0} /><FastProbeStat label="Existing solutions" value={fast.existing_solutions || 0} /><FastProbeStat label="Paid signals" value={fast.paid_signals || 0} /><FastProbeStat label="Post-purchase complaints" value={fast.post_purchase_complaints || 0} /></div>
      <div className="mt-5 grid gap-4 lg:grid-cols-[0.8fr_1.2fr]"><div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-xs font-semibold text-text-primary">Search coverage / failure visibility</div><div className="mt-3 space-y-2">{sourceHealth.length ? sourceHealth.map((row, i) => <SourceHealthRow key={`${row.source}-${i}`} row={row} />) : <div className="text-xs text-text-secondary">沒有 source health。</div>}</div><p className="mt-3 text-[10px] leading-5 text-text-tertiary">搜尋失敗 ≠ 市場不存在。只要 coverage 不完整，SignalForge 就必須把失敗顯示出來。</p></div><div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="flex items-center justify-between gap-3"><div className="text-xs font-semibold text-text-primary">剛找到的可檢查 trace</div><span className="text-[10px] text-text-tertiary">最多顯示 6 筆</span></div><div className="mt-3 grid gap-2 md:grid-cols-2">{traces.length ? traces.slice(0, 6).map((trace, i) => <FastTrace key={`${trace.url || trace.title}-${i}`} trace={trace} />) : <div className="text-xs text-text-secondary">成功來源目前沒有回傳相關 trace；這不是市場不存在的證明。</div>}</div></div></div>
    </section>

    <section className="rounded-3xl border border-success/30 bg-bg-success/30 p-5 md:p-7">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-txt-success">The One Question That Matters Next</div>
      <h2 className="mt-2 text-xl font-semibold leading-8 text-text-primary">{frontier.question || result.today?.one_question || "目前還沒有 decision frontier。"}</h2>
      <div className="mt-5 grid gap-3 lg:grid-cols-3"><Fact label="Today / 下一步" value={frontier.today_action || result.today?.instruction || "—"} /><Fact label="Advance if" value={frontier.advance_if || result.today?.advance_if || "—"} /><Fact label="Kill if" value={frontier.kill_if || result.today?.kill_if || "—"} /></div>
      {(frontier.do_not_research || []).length ? <div className="mt-4 rounded-2xl bg-bg-primary/70 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">Do Not Research</div><ul className="mt-2 space-y-1 text-xs leading-5 text-text-secondary">{(frontier.do_not_research || []).map((x, i) => <li key={i}>• {x}</li>)}</ul></div> : null}
      <div className="mt-3 text-[10px] text-text-tertiary">Next mode: {frontier.next_mode || result.today?.next_mode || "—"} · Market truth writes: {result.market_truth_writes ?? 0} · AI API calls: {result.ai_api_calls ?? 0}</div>
    </section>

    {trail ? <section><div className="mb-3 flex items-end justify-between gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Published Money Trail</div><h2 className="mt-1 text-lg font-semibold text-text-primary">已驗證／Published 的部分另外看</h2><p className="mt-1 text-xs text-text-secondary">Fresh trace 不會偷偷混進這裡。沒有 Published evidence 就明確 UNKNOWN。</p></div></div><MoneyTrailPanel trail={trail} /></section> : null}
  </div>;
}

export default function MoneyTrail() {
  const { data, isLoading, error } = useSignalForgeMoneyTrails();
  const marketActions = useSignalForgeMarketActions();
  const register = useRegisterSignalForgeMarketAction();
  const probe = useProbeSignalForgeFounderIdea();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const top = data?.items?.[0];
  const actionByThesis = useMemo(() => new Map((marketActions.data?.suggested?.items || []).map((x) => [x.thesis_id, x])), [marketActions.data]);

  return (
    <div className="mx-auto max-w-[1180px] pb-14">
      <header className="pb-5 pt-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-success">Money Trail</div>
        <h1 className="mt-2 text-[30px] font-semibold tracking-[-0.025em] text-text-primary">今天哪一筆錢最值得去拿？</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-text-secondary">不看 Opportunity Score。只看誰已經在花錢、錢流去哪、買了還在不爽什麼、你碰不碰得到，以及最便宜怎麼證明。</p>
      </header>

      <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
        <div className="flex items-center gap-2"><Search size={16} /><h2 className="text-base font-semibold text-text-primary">直接調查一個方向</h2></div>
        <p className="mt-1 text-xs leading-5 text-text-secondary">想到什麼就直接丟。SignalForge 會先做 bounded、0 AI API 的 fresh fast probe，再另外讀 Published Money Trail；新搜尋只算未驗證 trace，不會因為你輸入一個 idea 就把 buyer / spend / WTP 補完整。</p>
        <div className="mt-4 grid gap-3 lg:grid-cols-[0.8fr_1.5fr_auto]">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="方向名稱，例如 DoneProof" className="rounded-xl border border-border-secondary bg-bg-primary px-3.5 py-3 text-sm text-text-primary outline-none focus:border-info/50" />
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句話描述它想解的問題" className="rounded-xl border border-border-secondary bg-bg-primary px-3.5 py-3 text-sm text-text-primary outline-none focus:border-info/50" />
          <button type="button" disabled={probe.isPending || title.trim().length < 2} onClick={() => probe.mutate({ title: title.trim(), description: description.trim() })} className="rounded-xl bg-text-primary px-5 py-3 text-xs font-semibold text-bg-primary disabled:opacity-40">{probe.isPending ? "正在查市場" : "Probe 這個 idea"}</button>
        </div>
      </section>

      {probe.data ? <FounderIdeaResult result={probe.data} /> : null}
      {probe.error ? <div className="mt-5 rounded-2xl border border-danger/25 bg-bg-danger p-4 text-sm text-danger">這次 Founder Idea Probe 失敗。系統沒有拿舊結果冒充新答案，也不會把搜尋失敗解讀成市場不存在。</div> : null}

      {(marketActions.data?.registry?.rows || []).some((x) => ["REGISTERED", "RUNNING"].includes(String(x.status || "").toUpperCase())) ? (
        <section className="mt-6 rounded-3xl border border-success/25 bg-bg-success/25 p-5 md:p-6">
          <div><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-txt-success">正在驗證</div><h2 className="mt-1 text-lg font-semibold text-text-primary">做完就直接在這裡記結果</h2><p className="mt-1 text-xs leading-5 text-text-secondary">不用貼給我。結果會進 SignalForge 的 action history；沒有足夠樣本／對象／可追溯紀錄，就不能把 PASS / FAIL 當 calibration evidence。</p></div>
          <div className="mt-4 space-y-3">{(marketActions.data?.registry?.rows || []).filter((x) => ["REGISTERED", "RUNNING"].includes(String(x.status || "").toUpperCase())).map((record) => <SimpleActionResult key={record.action_id} record={record} />)}</div>
        </section>
      ) : null}

      <section className="mt-8">
        <div className="flex items-end justify-between gap-4"><div><h2 className="text-lg font-semibold text-text-primary">SignalForge 目前最接近第一筆收入的方向</h2><p className="mt-1 text-xs text-text-secondary">這是從現有 Brain thesis + Published evidence 重建，不代表已驗證市場。</p></div><span className="text-xs text-text-tertiary">{data?.count || 0} 個方向</span></div>
        {isLoading ? <div className="mt-4"><CardSkeleton /></div> : error ? <div className="mt-4 rounded-2xl border border-danger/25 bg-bg-danger p-4 text-sm text-danger">目前讀不到 Money Trail。</div> : top ? (
          <div className="mt-4">
            <MoneyTrailPanel trail={top} />
            {top.thesis_id && actionByThesis.get(top.thesis_id) ? (
              <div className="mt-3 flex justify-end">
                <button type="button" disabled={Boolean(actionByThesis.get(top.thesis_id)?.registered_action_id) || register.isPending} onClick={() => { const a = actionByThesis.get(top.thesis_id!); if (a) register.mutate({ thesis_id: a.thesis_id, action_type: a.action_type, sample_target: a.template?.default_sample }); }} className="inline-flex items-center gap-2 rounded-xl bg-text-primary px-4 py-3 text-xs font-semibold text-bg-primary disabled:opacity-40">{actionByThesis.get(top.thesis_id)?.registered_action_id ? "驗證已開始" : "開始這個市場測試"}<ArrowRight size={13} /></button>
              </div>
            ) : null}
          </div>
        ) : <div className="mt-4 rounded-2xl border border-border-secondary bg-bg-primary p-6 text-sm text-text-secondary">目前沒有 thesis 可重建 Money Trail。</div>}
      </section>
    </div>
  );
}

function SimpleActionResult({ record }: { record: SignalForgeMarketActionRecord }) {
  const complete = useCompleteSignalForgeMarketAction();
  const [result, setResult] = useState("INCONCLUSIVE");
  const [sample, setSample] = useState(String(record.sample_target || 10));
  const [actors, setActors] = useState("");
  const [refs, setRefs] = useState("");
  const [finding, setFinding] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("TWD");
  const category = String(record.category || record.mode || "").toUpperCase();
  const actionType = String(record.action_type || "").toUpperCase();
  const actorList = actors.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean);
  const refList = refs.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean);
  const sampleN = Number(sample || 0);
  const binary = result === "PASS" || result === "FAIL";
  const paymentPass = result === "PASS" && ["PAY", "PRICE", "WTP", "PREORDER"].some((x) => actionType.includes(x));
  const ready = !binary || (
    sampleN >= Number(record.sample_target || 1) &&
    actorList.length > 0 &&
    refList.length > 0 &&
    finding.trim().length >= 8 &&
    (!paymentPass || (Number(amount || 0) > 0 && currency.trim().length > 0))
  );
  return <details className="rounded-2xl border border-border-secondary bg-bg-primary p-4" open>
    <summary className="cursor-pointer list-none"><div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"><div><div className="text-xs font-semibold text-text-primary">{record.action_type?.replaceAll("_", " ") || "真人驗證"}</div><div className="mt-1 text-[10px] text-text-tertiary">原定樣本 {record.sample_target || "—"} · {record.status}</div></div><div className="text-[10px] text-text-tertiary">{record.action_id}</div></div></summary>
    <div className="mt-4 grid gap-3 border-t border-border-secondary pt-4 lg:grid-cols-2">
      <label className="text-[11px] text-text-secondary">結果<select value={result} onChange={(e) => setResult(e.target.value)} className="mt-1 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary"><option value="INCONCLUSIVE">還不能判斷</option><option value="PASS">有支持訊號</option><option value="FAIL">沒有支持訊號</option></select></label>
      <label className="text-[11px] text-text-secondary">實際接觸幾個人<input inputMode="numeric" value={sample} onChange={(e) => setSample(e.target.value)} className="mt-1 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label>
      <label className="text-[11px] text-text-secondary">對象（每行一個人 / 公司）<textarea value={actors} onChange={(e) => setActors(e.target.value)} placeholder="Agency A — Founder" className="mt-1 min-h-24 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label>
      <label className="text-[11px] text-text-secondary">可追溯紀錄（每行一個）<textarea value={refs} onChange={(e) => setRefs(e.target.value)} placeholder="notion:interview-01\nemail:thread-02" className="mt-1 min-h-24 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label>
      <label className="lg:col-span-2 text-[11px] text-text-secondary">你實際觀察到什麼<textarea value={finding} onChange={(e) => setFinding(e.target.value)} placeholder={category === "FOUNDER_DISCOVERY" ? "例如：3/10 都說 QA 成本主要是 senior review，但沒有固定工具預算。" : "例如：2 個 buyer 願意看報價，但沒有人付訂金。"} className="mt-1 min-h-28 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label>
      {paymentPass ? <><label className="text-[11px] text-text-secondary">實際金額<input value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label><label className="text-[11px] text-text-secondary">幣別<input value={currency} onChange={(e) => setCurrency(e.target.value)} className="mt-1 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" /></label></> : null}
    </div>
    <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><div className={`text-[10px] ${ready ? "text-text-tertiary" : "text-txt-warning"}`}>{binary && !ready ? "要把 PASS / FAIL 當有效結果，至少要達到原定樣本、列出對象、留下可追溯紀錄與實際發現。" : "還不能判斷也可以記錄，不會硬算成功或失敗。"}</div><button type="button" disabled={complete.isPending || !ready} onClick={() => complete.mutate({ actionId: record.action_id, payload: { result, observations: { observed_sample_size: sampleN, actor_labels: actorList, evidence_refs: refList, observed_behavior: category === "MARKET_ACTION" ? finding.trim() : "", decision_relevant_findings: category === "FOUNDER_DISCOVERY" ? finding.trim() : "", ...(paymentPass ? { amount: Number(amount || 0), currency: currency.trim(), actor_label: actorList[0] || "" } : {}) } } })} className="rounded-xl bg-text-primary px-4 py-2.5 text-xs font-semibold text-bg-primary disabled:opacity-40">記錄結果</button></div>
  </details>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-secondary/25 p-4"><div className="text-[10px] text-text-tertiary">{label}</div><div className="mt-2 text-sm font-semibold text-text-primary">{value}</div></div>;
}

function SpendBucket({ bucket, rows }: { bucket: string; rows: SignalForgeMoneyTrailEvidence[] }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="flex items-center justify-between gap-3"><div className="text-sm font-medium text-text-primary">{spendLabels[bucket] || bucket}</div><span className="text-[10px] text-text-tertiary">{rows.length} 筆</span></div><div className="mt-3 space-y-2">{rows.slice(0, 3).map((row, i) => <EvidenceMini key={`${row.source_family_key}-${i}`} row={row} />)}</div></div>;
}

function EvidenceMini({ row }: { row: SignalForgeMoneyTrailEvidence }) {
  return <div className="rounded-xl bg-bg-primary px-3 py-2.5"><div className="flex items-center justify-between gap-3"><span className="text-[10px] font-medium text-text-secondary">{evidenceGrade(row.evidence_grade)} · {row.source_type || "source"}</span>{row.amount_mentions?.length ? <span className="text-[10px] font-semibold text-txt-success">{row.amount_mentions.join(" · ")}</span> : null}</div><p className="mt-1 line-clamp-3 text-[11px] leading-5 text-text-secondary">{row.excerpt || row.source_title || "沒有摘要"}</p>{row.source_url ? <a href={row.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[10px] text-info hover:underline">看來源</a> : null}</div>;
}

function SignalBox({ title, value, good = false }: { title: string; value: string; good?: boolean }) {
  return <div className="rounded-2xl bg-bg-primary/75 p-4"><div className={`flex items-center gap-1.5 text-[10px] font-medium ${good ? "text-txt-success" : "text-danger"}`}>{good ? <CheckCircle2 size={12} /> : <XCircle size={12} />}{title}</div><div className="mt-2 text-xs leading-5 text-text-primary">{value}</div></div>;
}

function PlaybookBlock({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="flex items-center justify-between gap-3"><h4 className="text-xs font-semibold text-text-primary">{title}</h4>{action}</div><div className="mt-3">{children}</div></div>;
}
