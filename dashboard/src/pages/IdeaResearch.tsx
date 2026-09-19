import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  Github,
  MessageSquareText,
  PackageSearch,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useProbeSignalForgeFounderIdea } from "../api/hooks";

type ResearchCard = {
  source?: string;
  kind?: string;
  title?: string;
  excerpt?: string;
  url?: string | null;
  author?: string | null;
  created_at?: string | null;
  solution_type?: string | null;
  match_level?: string | null;
  why_relevant?: string | null;
};

type ResearchBrief = {
  mode?: string;
  idea?: { title?: string; description?: string };
  summary?: {
    useful_result_count?: number;
    human_comment_count?: number;
    similar_product_count?: number;
    product_or_service_count?: number;
    repo_solution_count?: number;
    supporting_evidence_count?: number;
    counter_evidence_count?: number;
  };
  human_comments?: ResearchCard[];
  similar_products?: ResearchCard[];
  repo_solutions?: ResearchCard[];
  supporting_evidence?: ResearchCard[];
  counter_evidence?: ResearchCard[];
  gaps?: string[];
  search?: {
    queries?: string[];
    source_profile_queries?: string[];
    successful_sources?: string[];
    failed_sources?: Array<{ source?: string; status?: string; error?: string | null }>;
    elapsed_ms?: number;
    query_bridge?: {
      status?: string;
      retrieval_query?: string;
      relevance_query?: string;
      api_calls?: number;
      error?: string | null;
    };
  };
  note?: string;
};

type ResearchProbePayload = {
  status?: string;
  idea?: { title?: string; description?: string };
  research_brief?: ResearchBrief;
};

function statusMeta(status?: string) {
  const raw = String(status || "").toUpperCase();
  if (raw === "RESEARCH_READY") return { label: "研究結果可看", cls: "border-success/30 bg-bg-success text-txt-success" };
  if (raw === "RESEARCH_PARTIAL") return { label: "部分來源受限", cls: "border-warning/30 bg-bg-warning text-warning" };
  if (raw === "NO_RELEVANT_RESULTS") return { label: "沒有找到夠相關結果", cls: "border-border-secondary bg-bg-secondary text-text-secondary" };
  if (raw === "SEARCH_FAILED") return { label: "搜尋失敗", cls: "border-danger/30 bg-bg-danger text-danger" };
  if (raw === "INVALID_QUERY") return { label: "Idea 太空泛", cls: "border-danger/30 bg-bg-danger text-danger" };
  return { label: raw || "研究中", cls: "border-border-secondary bg-bg-secondary text-text-secondary" };
}

function count(value?: number) {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function ResultCard({ item, repo = false }: { item: ResearchCard; repo?: boolean }) {
  const related = String(item.match_level || "").toUpperCase() === "RELATED";
  return (
    <article className="rounded-2xl border border-border-secondary bg-bg-primary p-4 md:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">{item.source || "SOURCE"}</span>
            {related ? <span className="rounded-full border border-warning/25 bg-bg-warning px-2 py-0.5 text-[9px] font-semibold text-warning">相關</span> : null}
            {item.solution_type ? <span className="rounded-full border border-border-secondary bg-bg-secondary px-2 py-0.5 text-[9px] text-text-tertiary">{item.solution_type.replaceAll("_", " ")}</span> : null}
          </div>
          <h3 className="mt-1.5 text-sm font-semibold leading-5 text-text-primary">{item.title || "未命名結果"}</h3>
        </div>
        {repo ? <Github className="h-4 w-4 shrink-0 text-text-tertiary" /> : null}
      </div>
      {item.excerpt ? <p className="mt-3 whitespace-pre-wrap text-xs leading-5 text-text-secondary">{item.excerpt}</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-text-tertiary">
        {item.author ? <span>author: {item.author}</span> : null}
        {item.created_at ? <span>{item.created_at}</span> : null}
        {item.url ? (
          <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-info hover:underline">
            看來源 <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </div>
      {item.why_relevant ? <div className="mt-3 border-t border-border-secondary pt-3 text-[10px] leading-4 text-text-tertiary">為什麼相關：{item.why_relevant}</div> : null}
    </article>
  );
}

function Section({
  title,
  description,
  items,
  empty,
  icon,
  repo = false,
}: {
  title: string;
  description: string;
  items?: ResearchCard[];
  empty: string;
  icon: React.ReactNode;
  repo?: boolean;
}) {
  return (
    <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 text-text-tertiary">{icon}</div>
        <div>
          <h2 className="text-base font-semibold text-text-primary">{title}</h2>
          <p className="mt-1 text-xs leading-5 text-text-secondary">{description}</p>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {(items || []).length ? (items || []).map((item, i) => <ResultCard key={`${item.url || item.title || "row"}-${i}`} item={item} repo={repo} />) : <div className="rounded-2xl bg-bg-secondary/70 p-4 text-xs text-text-secondary">{empty}</div>}
      </div>
    </section>
  );
}

export default function IdeaResearch() {
  const probe = useProbeSignalForgeFounderIdea();
  const [name, setName] = useState("");
  const [idea, setIdea] = useState("");

  const payload = probe.data as unknown as ResearchProbePayload | undefined;
  const brief = payload?.research_brief as ResearchBrief | undefined;
  const status = statusMeta(payload?.status);
  const summary = brief?.summary;
  const hasLegacyOnlyResponse = Boolean(payload && !brief);

  const canSubmit = idea.trim().length >= 4 || name.trim().length >= 4;
  const submit = () => {
    if (!canSubmit || probe.isPending) return;
    const cleanName = name.trim();
    const cleanIdea = idea.trim();
    probe.mutate({
      title: cleanName || cleanIdea,
      description: cleanName ? cleanIdea : "",
    });
  };

  const counts = useMemo(() => [
    ["真人留言", count(summary?.human_comment_count)],
    ["產品 / 方案", count(summary?.product_or_service_count)],
    ["Repo", count(summary?.repo_solution_count)],
    ["其他資料", count(summary?.supporting_evidence_count)],
    ["反面資料", count(summary?.counter_evidence_count)],
  ] as Array<[string, number]>, [summary]);

  return (
    <div className="mx-auto max-w-[1180px] pb-14">
      <header className="pb-5 pt-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-info">Idea Research</div>
        <h1 className="mt-2 text-[30px] font-semibold tracking-[-0.025em] text-text-primary">先查市場，再決定要不要做</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-text-secondary">丟一個 idea 或問題進來。SignalForge 只整理找到的真人討論、現有方案、Repo、旁證、反面資料與缺口；沒有證據就留白，不替你編市場故事。</p>
      </header>

      <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
        <div className="flex items-center gap-2"><Search size={16} /><h2 className="text-base font-semibold text-text-primary">研究一個 idea</h2></div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[0.72fr_1.5fr_auto]">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名稱（可選），例如 DoneProof"
            className="rounded-xl border border-border-secondary bg-bg-primary px-3.5 py-3 text-sm text-text-primary outline-none focus:border-info/50"
          />
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="描述你想查的問題／假設，例如：AI coding agent 說做完了，但使用者仍要花很多時間確認它到底有沒有做對、做完。"
            className="min-h-[48px] resize-y rounded-xl border border-border-secondary bg-bg-primary px-3.5 py-3 text-sm text-text-primary outline-none focus:border-info/50"
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit(); }}
          />
          <button type="button" disabled={!canSubmit || probe.isPending} onClick={submit} className="self-stretch rounded-xl bg-text-primary px-5 py-3 text-xs font-semibold text-bg-primary disabled:opacity-40">
            {probe.isPending ? "正在找市場資料…" : "開始研究"}
          </button>
        </div>
        <div className="mt-2 text-[10px] text-text-tertiary">Ctrl / Cmd + Enter 也可以送出。純中文 idea 只有在本地 query bridge 不夠時，才會用一次 bounded mini bridge。</div>
      </section>

      {probe.error ? <div className="mt-5 rounded-2xl border border-danger/25 bg-bg-danger p-4 text-sm text-danger">這次研究失敗。SignalForge 不會拿舊結果冒充新答案；請看後端 terminal 的實際錯誤。</div> : null}

      {hasLegacyOnlyResponse ? <div className="mt-5 rounded-2xl border border-danger/25 bg-bg-danger p-4 text-sm text-danger">Dashboard 已切到 Idea Research，但後端回傳的不是 FIX5 research_brief。請不要把舊 Money Trail 結果當成這次研究答案。</div> : null}

      {brief ? (
        <div className="mt-6 space-y-5">
          <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${status.cls}`}>{status.label}</span>
                  <span className="text-[10px] text-text-tertiary">{count(summary?.useful_result_count)} 筆可用材料</span>
                </div>
                <h2 className="mt-3 text-lg font-semibold text-text-primary">{brief.idea?.title || payload?.idea?.title || "研究結果"}</h2>
                {brief.idea?.description ? <p className="mt-1 max-w-4xl text-xs leading-5 text-text-secondary">{brief.idea.description}</p> : null}
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-5">
              {counts.map(([label, value]) => <div key={label} className="rounded-2xl bg-bg-secondary p-3"><div className="text-[10px] text-text-tertiary">{label}</div><div className="mt-1 text-xl font-semibold text-text-primary">{value}</div></div>)}
            </div>
            {brief.note ? <p className="mt-4 text-[10px] leading-4 text-text-tertiary">{brief.note}</p> : null}
          </section>

          <Section title="真人留言" description="只放真正的人類留言／討論；作者的產品 pitch 不會混進來。" items={brief.human_comments} empty="這次沒有找到夠相關的真人留言。" icon={<MessageSquareText className="h-4 w-4" />} />
          <Section title="產品 / 服務 / 作者提出的方案" description="現有商業產品、服務，或作者自己提出的解法。" items={brief.similar_products} empty="這次沒有找到夠相關的產品或作者方案。" icon={<PackageSearch className="h-4 w-4" />} />
          <Section title="Repo / 開源方案" description="GitHub / 開源實作獨立列出，不假裝它等於商業 competitor。" items={brief.repo_solutions} empty="這次沒有找到夠相關的 Repo / 開源方案。" icon={<Github className="h-4 w-4" />} repo />
          <Section title="其他有用資料" description="市場、技術、新聞、職缺等能補充這個問題的旁證。" items={brief.supporting_evidence} empty="這次沒有找到額外旁證。" icon={<CheckCircle2 className="h-4 w-4" />} />
          <Section title="反面 / 不支持資料" description="明確指出問題不嚴重、現有方案夠好、工具效果差或其他會推翻假設的材料。" items={brief.counter_evidence} empty="這次沒有找到夠相關的反面資料。" icon={<ShieldAlert className="h-4 w-4" />} />

          <section className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
            <div className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-warning" /><h2 className="text-base font-semibold text-text-primary">目前缺口</h2></div>
            {(brief.gaps || []).length ? <ul className="mt-4 space-y-2 text-xs leading-5 text-text-secondary">{(brief.gaps || []).map((gap, i) => <li key={i} className="rounded-xl bg-bg-secondary px-3.5 py-3">{gap}</li>)}</ul> : <div className="mt-4 rounded-xl bg-bg-secondary px-3.5 py-3 text-xs text-text-secondary">目前沒有額外缺口訊息。</div>}
          </section>

          <details className="rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
              <div><h2 className="text-base font-semibold text-text-primary">搜尋診斷</h2><p className="mt-1 text-xs text-text-secondary">需要 debug coverage 時再展開，平常不用看工程細節。</p></div>
              <ChevronDown className="h-4 w-4 text-text-tertiary" />
            </summary>
            <div className="mt-4 space-y-4 border-t border-border-secondary pt-4 text-xs text-text-secondary">
              <div><div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Queries</div><div className="mt-1 space-y-1">{(brief.search?.queries || []).map((q, i) => <div key={i} className="rounded-lg bg-bg-secondary px-3 py-2 font-mono text-[10px]">{q}</div>)}</div></div>
              {brief.search?.query_bridge ? <div><div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Query bridge</div><div className="mt-1 rounded-xl bg-bg-secondary p-3 text-[10px] leading-5"><div>status: {brief.search.query_bridge.status || "—"}</div><div>retrieval: {brief.search.query_bridge.retrieval_query || "—"}</div><div>relevance: {brief.search.query_bridge.relevance_query || "—"}</div><div>AI calls: {brief.search.query_bridge.api_calls ?? 0}</div>{brief.search.query_bridge.error ? <div className="text-danger">error: {brief.search.query_bridge.error}</div> : null}</div></div> : null}
              <div className="grid gap-3 md:grid-cols-2">
                <div><div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">成功來源</div><div className="mt-1 rounded-xl bg-bg-secondary p-3 text-[10px] leading-5">{(brief.search?.successful_sources || []).join(", ") || "—"}</div></div>
                <div><div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">失敗 / 受限來源</div><div className="mt-1 space-y-1">{(brief.search?.failed_sources || []).length ? (brief.search?.failed_sources || []).map((row, i) => <div key={i} className="rounded-xl bg-bg-danger p-3 text-[10px] leading-5 text-danger">{row.source || "SOURCE"} · {row.status || "FAILED"}{row.error ? ` · ${row.error}` : ""}</div>) : <div className="rounded-xl bg-bg-secondary p-3 text-[10px]">—</div>}</div></div>
              </div>
              <div className="text-[10px] text-text-tertiary">elapsed: {brief.search?.elapsed_ms ?? "—"} ms</div>
            </div>
          </details>
        </div>
      ) : null}
    </div>
  );
}
