import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search as SearchIcon, Database, ExternalLink, GitBranch, FileText, Newspaper, MessageSquare } from "lucide-react";
import { useSearch, useSignalForgeBrainSearch } from "../api/hooks";
import Skeleton from "../components/common/Skeleton";
import { timeAgo } from "../lib/utils";

type Mode = "intelligence" | "corpus";

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const initial = params.get("q") || "";
  const [input, setInput] = useState(initial);
  const [query, setQuery] = useState(initial);
  const [mode, setMode] = useState<Mode>((params.get("scope") as Mode) || "intelligence");
  const brain = useSignalForgeBrainSearch(query);
  const corpus = useSearch(query);

  useEffect(() => {
    const q = params.get("q") || "";
    setInput(q);
    setQuery(q);
    const scope = params.get("scope");
    if (scope === "corpus" || scope === "intelligence") setMode(scope);
  }, [params]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (q.length < 2) return;
    setQuery(q);
    setParams({ q, scope: mode });
  }

  const brainRows = brain.data?.items || [];
  const rawTotal = (corpus.data?.posts?.length || 0) + (corpus.data?.news?.length || 0) + (corpus.data?.topics?.length || 0) + (corpus.data?.users?.length || 0);
  const loading = mode === "intelligence" ? brain.isLoading : corpus.isLoading;

  return (
    <div className="max-w-[1480px] mx-auto space-y-5 pb-10">
      <header className="border-b border-border-secondary pb-5">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-text-tertiary"><SearchIcon size={13} /> Search</div>
        <h1 className="mt-2 text-2xl font-semibold text-text-primary">搜尋 SignalForge</h1>
        <p className="mt-2 text-sm text-text-secondary">預設搜尋已整理過的商機方向、問題與轉變。只有需要追原始來源時，再切到原始資料。</p>
      </header>

      <div className="inline-flex rounded-xl border border-border-primary bg-bg-primary p-1">
        <button onClick={() => { setMode("intelligence"); if (query) setParams({ q: query, scope: "intelligence" }); }} className={`rounded-lg px-3 py-1.5 text-xs ${mode === "intelligence" ? "bg-text-primary text-bg-primary" : "text-text-secondary hover:bg-bg-secondary"}`}>商機與問題</button>
        <button onClick={() => { setMode("corpus"); if (query) setParams({ q: query, scope: "corpus" }); }} className={`rounded-lg px-3 py-1.5 text-xs ${mode === "corpus" ? "bg-text-primary text-bg-primary" : "text-text-secondary hover:bg-bg-secondary"}`}>原始資料</button>
      </div>

      <form onSubmit={submit} className="flex gap-3">
        <div className="flex flex-1 max-w-3xl items-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5">
          <SearchIcon size={15} className="text-text-tertiary" />
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={mode === "intelligence" ? "搜尋商機方向、問題、Buyer…" : "搜尋原始貼文、新聞、來源…"} className="w-full bg-transparent text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none" />
        </div>
        <button type="submit" className="rounded-xl bg-text-primary px-4 py-2 text-sm font-medium text-bg-primary">Search</button>
      </form>

      {query ? <div className="text-xs text-text-secondary">{loading ? "搜尋中…" : mode === "intelligence" ? `${brainRows.length} 個整理後結果，關鍵字 “${query}”` : `${rawTotal} 個原始資料結果，關鍵字 “${query}”`}</div> : null}

      {loading ? <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="rounded-xl border border-border-secondary bg-bg-primary p-4"><Skeleton className="h-4 w-3/4" /><Skeleton className="mt-2 h-3 w-1/2" /></div>)}</div> : null}

      {mode === "intelligence" && !loading ? (
        <section className="space-y-3">
          {brainRows.map((row) => (
            <article key={`${row.object_type}:${row.object_id}`} className="rounded-xl border border-border-secondary bg-bg-primary p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-text-tertiary"><GitBranch size={11} /> {row.object_type}<span className="font-mono">{row.object_id}</span>{row.strategic_track ? <span>{row.strategic_track}</span> : null}{row.zip2_readiness ? <span>{row.zip2_readiness}</span> : null}</div>
                  <div className="mt-2 text-sm font-semibold text-text-primary">{row.title}</div>
                  {row.subtitle ? <div className="mt-1 text-xs text-text-secondary">{row.subtitle}</div> : null}
                </div>
                {row.object_type === "OPPORTUNITY_THESIS" ? <Link to={`/theses/${encodeURIComponent(row.object_id)}`} className="shrink-0 text-[11px] text-info hover:underline">看完整判斷</Link> : null}
              </div>
            </article>
          ))}
          {query && brainRows.length === 0 ? <div className="rounded-xl border border-border-secondary bg-bg-primary p-8 text-center text-sm text-text-secondary">目前沒有符合的商機方向或問題。</div> : null}
        </section>
      ) : null}

      {mode === "corpus" && !loading && corpus.data ? (
        <section className="space-y-4">
          {corpus.data.news.length ? <RawBlock title={`News (${corpus.data.news.length})`} icon={<Newspaper size={14} />}>{corpus.data.news.map((n) => <div key={n.id} className="flex items-start justify-between gap-3 py-2"><div><div className="text-sm text-text-primary">{n.title}</div><div className="text-[10px] text-text-tertiary">{n.source_name} · {timeAgo(n.published_at)}</div></div>{n.url ? <a href={n.url} target="_blank" rel="noreferrer"><ExternalLink size={13} className="text-text-tertiary" /></a> : null}</div>)}</RawBlock> : null}
          {corpus.data.posts.length ? <RawBlock title={`Posts (${corpus.data.posts.length})`} icon={<MessageSquare size={14} />}>{corpus.data.posts.map((p) => <div key={p.id} className="py-2"><div className="text-sm text-text-primary">{p.title || (p.body || "").slice(0, 140)}</div><div className="text-[10px] text-text-tertiary">{p.platform_name || "source"} · {timeAgo(p.posted_at)}</div></div>)}</RawBlock> : null}
          {corpus.data.topics.length || corpus.data.users.length ? <RawBlock title="Other raw corpus objects" icon={<Database size={14} />}><div className="text-xs text-text-secondary">Topics {corpus.data.topics.length} · People {corpus.data.users.length}. These are corpus navigation objects, not Opportunity Theses.</div></RawBlock> : null}
          {query && rawTotal === 0 ? <div className="rounded-xl border border-border-secondary bg-bg-primary p-8 text-center text-sm text-text-secondary">目前沒有符合的原始資料。</div> : null}
        </section>
      ) : null}

      <div className="flex items-center gap-2 text-[10px] text-text-tertiary"><FileText size={11} /> 商機與問題 search never upgrades a claim; it only navigates already materialized derived objects.</div>
    </div>
  );
}

function RawBlock({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <div className="rounded-xl border border-border-secondary bg-bg-primary p-4"><div className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">{icon}{title}</div><div className="divide-y divide-border-secondary">{children}</div></div>;
}
