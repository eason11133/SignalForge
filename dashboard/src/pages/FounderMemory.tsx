import { useEffect, useMemo, useState, type FormEvent } from "react";
import { BookOpenCheck, Brain, Clock3, Plus, ShieldCheck } from "lucide-react";
import {
  useCheckpointSignalForgeFounderMemory,
  useRecordSignalForgeFounderMemory,
  useSignalForgeFounderMemory,
  useSignalForgeFounderMemoryBrief,
  useSignalForgeFounderMemoryDelta,
  useSignalForgeFounderMemorySubjects,
  useSignalForgeMoneyTrails,
} from "../api/hooks";
import type { SignalForgeFounderMemoryEntry, SignalForgeFounderMemoryEntryType, SignalForgeFounderMarketClaimState } from "../api/client";

const entryTypes: Array<{ value: SignalForgeFounderMemoryEntryType; label: string; help: string }> = [
  { value: "HYPOTHESIS", label: "假設", help: "我們懷疑可能成立，但市場還沒證明" },
  { value: "QUESTION", label: "問題", help: "現在仍值得回答的問題" },
  { value: "ASSUMPTION", label: "前提", help: "目前決策暫時依賴的假設" },
  { value: "DECISION", label: "決定", help: "Founder 已經做出的選擇，必須記原因" },
  { value: "REJECTED_DIRECTION", label: "否決方向", help: "不要隔幾天又重新討論，必須記原因" },
  { value: "CONSTRAINT", label: "限制", help: "時間、成本、能力或產品邊界" },
  { value: "REASON", label: "理由", help: "補充一個已存在決策／脈絡的原因" },
];

const typeLabel: Record<string, string> = Object.fromEntries(entryTypes.map((x) => [x.value, x.label]));

function readableState(raw?: string) {
  const state = String(raw || "UNKNOWN").toUpperCase();
  const labels: Record<string, string> = {
    SUPPORTED: "有 Published 支持",
    KNOWN: "已知",
    REFUTED: "被反證",
    CONTRADICTED: "矛盾",
    UNKNOWN: "未知",
    INSUFFICIENT: "證據不足",
  };
  return labels[state] || state.replaceAll("_", " ");
}

function ClaimList({ title, rows, empty }: { title: string; rows?: SignalForgeFounderMarketClaimState[]; empty: string }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
    <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">{title}</div>
    <div className="mt-3 space-y-2">
      {(rows || []).length ? (rows || []).map((row) => <div key={row.claim_code} className="rounded-xl bg-bg-primary px-3 py-2.5">
        <div className="text-[10px] font-semibold text-text-primary">{row.claim_code} · {row.label}</div>
        <div className="mt-1 text-[10px] text-text-secondary">{readableState(row.state)}</div>
      </div>) : <div className="text-xs leading-5 text-text-tertiary">{empty}</div>}
    </div>
  </div>;
}

function MemoryList({ rows, empty = "目前沒有記錄。" }: { rows?: SignalForgeFounderMemoryEntry[]; empty?: string }) {
  if (!(rows || []).length) return <div className="text-xs leading-5 text-text-tertiary">{empty}</div>;
  return <div className="space-y-2">{(rows || []).slice().reverse().map((row) => <div key={row.entry_id} className="rounded-xl border border-border-secondary bg-bg-primary px-3 py-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-[10px] font-semibold text-text-secondary">{typeLabel[String(row.entry_type || "")] || row.entry_type}</span>
      <span className="text-[9px] text-text-tertiary">{row.created_at ? new Date(row.created_at).toLocaleString() : ""}</span>
    </div>
    <div className="mt-1.5 text-xs leading-5 text-text-primary">{row.statement}</div>
    {row.reason ? <div className="mt-2 rounded-lg bg-bg-secondary/60 px-2.5 py-2 text-[10px] leading-4 text-text-secondary"><span className="font-semibold">WHY</span> · {row.reason}</div> : null}
  </div>)}</div>;
}

export default function FounderMemory() {
  const subjects = useSignalForgeFounderMemorySubjects();
  const moneyTrails = useSignalForgeMoneyTrails();
  const [subject, setSubject] = useState("");
  const [thesisId, setThesisId] = useState("");
  const [entryType, setEntryType] = useState<SignalForgeFounderMemoryEntryType>("DECISION");
  const [statement, setStatement] = useState("");
  const [reason, setReason] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [checkpointNote, setCheckpointNote] = useState("");

  useEffect(() => {
    if (!subject && (subjects.data?.items || []).length) {
      const first = subjects.data!.items[0];
      setSubject(first.subject_label || first.subject_key || "");
      setThesisId(first.thesis_id || "");
    }
  }, [subject, subjects.data]);

  const activeSubject = subject.trim();
  const activeThesis = thesisId.trim() || undefined;
  const ledger = useSignalForgeFounderMemory(activeSubject, activeThesis);
  const brief = useSignalForgeFounderMemoryBrief(activeSubject, activeThesis);
  const delta = useSignalForgeFounderMemoryDelta(activeSubject, activeThesis);
  const record = useRecordSignalForgeFounderMemory();
  const checkpoint = useCheckpointSignalForgeFounderMemory();
  const selectedType = useMemo(() => entryTypes.find((x) => x.value === entryType), [entryType]);
  const reasonRequired = entryType === "DECISION" || entryType === "REJECTED_DIRECTION";
  const canSave = activeSubject.length >= 2 && statement.trim().length >= 3 && (!reasonRequired || reason.trim().length >= 3) && !record.isPending;

  function chooseSubject(key: string, label?: string, tid?: string | null) {
    setSubject(label || key);
    setThesisId(tid || "");
  }

  function submitEntry(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    record.mutate({
      subject_key: activeSubject,
      subject_label: activeSubject,
      thesis_id: activeThesis,
      entry_type: entryType,
      statement: statement.trim(),
      reason: reason.trim() || undefined,
      source_ref: sourceRef.trim() || undefined,
    }, {
      onSuccess: () => {
        setStatement("");
        setReason("");
        setSourceRef("");
      },
    });
  }

  const fr = brief.data?.founder_reasoning;
  const suspects = [...(fr?.hypotheses || []), ...(fr?.assumptions || [])].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
  const newMemory = delta.data?.new_founder_reasoning || [];
  const marketChanges = delta.data?.market_delta?.changed_claims || [];

  return <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6 md:py-8">
    <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 shadow-sm md:p-7">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-tertiary"><Brain size={14} /> Part 2 · Founder Memory</div>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em] text-text-primary">我們談過什麼，不要再靠人腦記</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-text-secondary">記錄假設、問題、決定、否決方向、限制與原因；下次直接看 Brief 和 Since Last Discussion，不重新從零聊。</p>
        </div>
        <div className="rounded-2xl border border-info/25 bg-bg-info px-4 py-3 text-xs leading-5 text-txt-info">
          <div className="flex items-center gap-2 font-semibold"><ShieldCheck size={14} /> Founder Reasoning ≠ Market Truth</div>
          <div className="mt-1 text-[10px]">MARKET AUTHORITY: NONE · MARKET TRUTH IMPACT: NONE</div>
        </div>
      </div>

      <div className="mt-6">
        <label className="text-[11px] text-text-secondary">現在在談什麼
          <input value={subject} onChange={(e) => { setSubject(e.target.value); setThesisId(""); }} placeholder="例如 DoneProof、AI agent memory、Agency QA" className="mt-1.5 w-full rounded-xl border border-border-secondary bg-bg-secondary/35 px-3.5 py-3 text-sm text-text-primary outline-none focus:border-info/50" />
        </label>
      </div>

      {(moneyTrails.data?.items || []).length ? <div className="mt-3"><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">從目前 Published 方向帶入</div><div className="mt-2 flex flex-wrap gap-2">{moneyTrails.data!.items.slice(0, 10).map((x) => <button key={x.thesis_id || x.title} type="button" onClick={() => chooseSubject(x.thesis_id || x.title || "", x.title || x.problem || x.thesis_id, x.thesis_id)} className="rounded-full border border-info/20 bg-bg-info/35 px-3 py-1.5 text-[10px] text-txt-info hover:border-info/40">{x.title || x.problem || x.thesis_id}</button>)}</div></div> : null}
      {(subjects.data?.items || []).length ? <div className="mt-3"><div className="text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">最近談過</div><div className="mt-2 flex flex-wrap gap-2">{subjects.data!.items.slice(0, 12).map((x) => <button key={x.subject_key} type="button" onClick={() => chooseSubject(x.subject_key, x.subject_label, x.thesis_id)} className="rounded-full border border-border-secondary bg-bg-secondary/40 px-3 py-1.5 text-[10px] text-text-secondary hover:text-text-primary">{x.subject_label || x.subject_key} <span className="text-text-tertiary">· {x.entry_count || 0}</span></button>)}</div></div> : null}
      <details className="mt-3 text-[10px] text-text-tertiary"><summary className="cursor-pointer">進階：手動指定 linked thesis</summary><input value={thesisId} onChange={(e) => setThesisId(e.target.value)} placeholder="thesis id" className="mt-2 w-full rounded-xl border border-border-secondary bg-bg-secondary/35 px-3 py-2 text-xs text-text-primary" /></details>
    </section>

    <section className="mt-5 grid gap-5 xl:grid-cols-[420px_1fr]">
      <form onSubmit={submitEntry} className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
        <div className="flex items-center gap-2"><Plus size={15} className="text-text-tertiary" /><h2 className="text-sm font-semibold text-text-primary">把這次討論留下來</h2></div>
        <label className="mt-4 block text-[11px] text-text-secondary">這是什麼
          <select value={entryType} onChange={(e) => setEntryType(e.target.value as SignalForgeFounderMemoryEntryType)} className="mt-1.5 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary">
            {entryTypes.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
          </select>
        </label>
        <div className="mt-1 text-[10px] leading-4 text-text-tertiary">{selectedType?.help}</div>
        <label className="mt-4 block text-[11px] text-text-secondary">內容
          <textarea value={statement} onChange={(e) => setStatement(e.target.value)} placeholder={entryType === "DECISION" ? "例如：DoneProof 暫停繼續開發。" : entryType === "REJECTED_DIRECTION" ? "例如：Generic AI code reviewer 不做。" : "寫下這次真的不想再忘的東西"} className="mt-1.5 min-h-28 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-3 text-xs leading-5 text-text-primary outline-none focus:border-info/50" />
        </label>
        <label className="mt-3 block text-[11px] text-text-secondary">原因 {reasonRequired ? <span className="text-danger">· 必填</span> : <span className="text-text-tertiary">· 選填</span>}
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="為什麼當時這樣決定／否決？" className="mt-1.5 min-h-20 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-3 text-xs leading-5 text-text-primary outline-none focus:border-info/50" />
        </label>
        <label className="mt-3 block text-[11px] text-text-secondary">對話 / 文件 reference（選填）
          <input value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} placeholder="例如 ChatGPT 2026-09-06 / meeting note" className="mt-1.5 w-full rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs text-text-primary" />
        </label>
        {record.error ? <div className="mt-3 rounded-xl border border-danger/25 bg-bg-danger p-3 text-[10px] text-danger">{String(record.error)}</div> : null}
        <button type="submit" disabled={!canSave} className="mt-4 w-full rounded-xl bg-text-primary px-4 py-3 text-xs font-semibold text-bg-primary disabled:opacity-40">{record.isPending ? "記錄中…" : "記住這件事"}</button>
        <div className="mt-2 text-[9px] leading-4 text-text-tertiary">這個按鈕只寫 Founder Memory ledger，不會 Publish、改 C01–C14 或改 calibration。</div>
      </form>

      <div className="space-y-5">
        <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
          <div className="flex items-center gap-2"><BookOpenCheck size={15} className="text-text-tertiary" /><h2 className="text-sm font-semibold text-text-primary">Founder Discussion Brief</h2></div>
          {!activeSubject ? <div className="mt-4 text-xs text-text-tertiary">先輸入一個討論主題。</div> : brief.isLoading ? <div className="mt-4 text-xs text-text-tertiary">整理中…</div> : brief.error ? <div className="mt-4 text-xs text-danger">Brief 目前讀不到：{String(brief.error)}</div> : <>
            <div className="mt-5 rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4">
              <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">Current Decision Frontier</div>
              <div className="mt-2 text-sm font-semibold leading-6 text-text-primary">{brief.data?.current_decision_frontier?.statement || "目前 Founder Memory 還沒有記一個明確 Question。"}</div>
            </div>

            <div className="mt-5">
              <div className="flex items-center justify-between gap-3"><h3 className="text-xs font-semibold text-text-primary">MARKET TRUTH</h3><span className="text-[9px] text-text-tertiary">唯讀 Published state</span></div>
              {brief.data?.market_truth?.status === "PASS" ? <div className="mt-3 grid gap-3 md:grid-cols-3">
                <ClaimList title="WHAT WE KNOW" rows={brief.data.market_truth.known} empty="目前沒有 SUPPORTED claim。" />
                <ClaimList title="CONTRADICTED" rows={brief.data.market_truth.contradicted} empty="目前沒有 Published contradiction。" />
                <ClaimList title="STILL UNKNOWN" rows={brief.data.market_truth.unknown} empty="目前沒有 Unknown。" />
              </div> : <div className="mt-3 rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4 text-xs leading-5 text-text-secondary">沒有 linked Published thesis，所以這裡不會拿 Founder 說過的話補市場事實。<div className="mt-1 text-[10px] text-text-tertiary">{brief.data?.market_truth?.status}</div></div>}
            </div>

            <div className="mt-5 grid gap-3 lg:grid-cols-2">
              <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">WHAT WE SUSPECT</div><div className="mt-3"><MemoryList rows={suspects} empty="目前沒有 Founder hypothesis / assumption。" /></div></div>
              <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">DECISIONS</div><div className="mt-3"><MemoryList rows={fr?.decisions} empty="目前沒有已記錄決策。" /></div></div>
              <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">REJECTED DIRECTIONS</div><div className="mt-3 space-y-2">{(fr?.rejected_directions || []).length ? fr!.rejected_directions!.slice().reverse().map((x, i) => <div key={`${x.statement}-${i}`} className="rounded-xl bg-bg-primary p-3"><div className="text-xs leading-5 text-text-primary">{x.statement}</div>{x.reason ? <div className="mt-2 text-[10px] leading-4 text-text-secondary"><span className="font-semibold">WHY</span> · {x.reason}</div> : null}</div>) : <div className="text-xs text-text-tertiary">目前沒有否決方向。</div>}</div></div>
              <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">CONSTRAINTS</div><div className="mt-3"><MemoryList rows={fr?.constraints} empty="目前沒有 constraints。" /></div></div>
            </div>

            {(brief.data?.do_not_discuss_again || []).length ? <div className="mt-5 rounded-2xl border border-warning/25 bg-bg-warning p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-txt-warning">DO NOT DISCUSS AGAIN WITHOUT NEW REASON</div><div className="mt-3 space-y-2">{brief.data!.do_not_discuss_again!.map((x, i) => <div key={`${x.statement}-${i}`} className="text-xs leading-5 text-text-primary">• {x.statement}{x.reason ? <span className="text-text-secondary"> — {x.reason}</span> : null}</div>)}</div></div> : null}
          </>}
        </section>

        <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div><div className="flex items-center gap-2"><Clock3 size={15} className="text-text-tertiary" /><h2 className="text-sm font-semibold text-text-primary">Since Last Discussion</h2></div><p className="mt-1 text-[10px] leading-4 text-text-tertiary">只比較你明確設過的討論基準；沒有 baseline 就不假裝知道「上次」。</p></div>
            <button type="button" disabled={activeSubject.length < 2 || checkpoint.isPending} onClick={() => checkpoint.mutate({ subject_key: activeSubject, thesis_id: activeThesis, note: checkpointNote.trim() || undefined })} className="rounded-xl border border-border-secondary bg-bg-secondary/40 px-3 py-2 text-[10px] font-semibold text-text-primary disabled:opacity-40">{checkpoint.isPending ? "建立中…" : "把現在設為已討論基準"}</button>
          </div>
          <input value={checkpointNote} onChange={(e) => setCheckpointNote(e.target.value)} placeholder="基準備註（選填，例如：9/6 晚上討論完）" className="mt-3 w-full rounded-xl border border-border-secondary bg-bg-secondary/30 px-3 py-2 text-[10px] text-text-primary" />
          {delta.data?.status === "NO_DISCUSSION_BASELINE" ? <div className="mt-4 rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4 text-xs leading-5 text-text-secondary">還沒有 discussion baseline。現在的記憶都會先保留，但系統不會冒充它們是「新變化」。討論完按上面的基準按鈕，下一次才開始真正 Delta。</div> : <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">NEW FOUNDER REASONING</div><div className="mt-3"><MemoryList rows={newMemory} empty="上次討論後沒有新增 Founder reasoning。" /></div></div>
            <div className="rounded-2xl border border-border-secondary bg-bg-secondary/20 p-4"><div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-tertiary">MARKET TRUTH CHANGED</div><div className="mt-3 space-y-2">{marketChanges.length ? marketChanges.map((x) => <div key={x.claim_code} className="rounded-xl bg-bg-primary p-3 text-xs text-text-primary"><span className="font-semibold">{x.claim_code} · {x.label}</span><div className="mt-1 text-[10px] text-text-secondary">{readableState(x.before)} → {readableState(x.after)}</div></div>) : <div className="text-xs text-text-tertiary">Published claim state 沒有可見變化。</div>}</div></div>
          </div>}
          {delta.data?.new_next_question?.statement ? <div className="mt-3 rounded-2xl border border-info/25 bg-bg-info p-4"><div className="text-[10px] font-semibold text-txt-info">NEW / CURRENT NEXT QUESTION</div><div className="mt-2 text-xs font-semibold leading-5 text-text-primary">{delta.data.new_next_question.statement}</div></div> : null}
        </section>
      </div>
    </section>

    <section className="mt-5 rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
      <div className="flex items-center justify-between gap-4"><div><h2 className="text-sm font-semibold text-text-primary">Founder Discussion Ledger</h2><p className="mt-1 text-[10px] text-text-tertiary">Append-only · {ledger.data?.count || 0} 筆。舊決策不覆寫；新決策要新增一筆留下歷史。</p></div><span className="rounded-full border border-border-secondary px-2.5 py-1 text-[9px] text-text-tertiary">MARKET AUTHORITY NONE</span></div>
      <div className="mt-4"><MemoryList rows={ledger.data?.items} empty="這個主題還沒有 Founder Memory。" /></div>
    </section>
  </div>;
}
