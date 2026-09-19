import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  
  Check,
  CirclePause,
  Copy,
  ExternalLink,
  Globe2,
  Link2,
  Loader2,
  PackageSearch,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import {
  acknowledgeResearchBacklogHandoff,
  addResearchBacklogIdeas,
  getResearchBacklog,
  getResearchBacklogDetail,
  refreshResearchBacklogItem,
  startResearchBacklog,
  stopResearchBacklog,
  type MaterialLibrary,
  type ResearchBacklogCard,
  type ResearchBacklogItem,
  type ResearchBacklogResponse,
  type ResearchHistoryEntry,
} from "../api/researchBacklog";

function n(value?: number) {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function fmtTime(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

function fmtInterval(seconds?: number) {
  const value = n(seconds);
  if (!value) return "定期";
  if (value % 86400 === 0) return `${value / 86400} 天`;
  if (value % 3600 === 0) return `${value / 3600} 小時`;
  return `${Math.max(1, Math.round(value / 60))} 分鐘`;
}

function statusMeta(status?: string, hasNewData = false) {
  const raw = String(status || "TRACKING_NEW").toUpperCase();
  if (raw === "SEARCHING") return { label: "搜尋中", cls: "border-info/30 bg-bg-info text-info" };
  if (raw === "SOURCE_LIMITED") return { label: "來源受限", cls: "border-warning/30 bg-bg-warning text-warning" };
  if (raw === "TRACKING_NEW") return { label: "待首次追蹤", cls: "border-border-secondary bg-bg-secondary text-text-secondary" };
  if (raw === "TRACKING_DUE") return { label: "待更新", cls: "border-info/30 bg-bg-info text-info" };
  if (hasNewData) return { label: "有新資料", cls: "border-success/30 bg-bg-success text-txt-success" };
  return { label: "自動追蹤", cls: "border-success/30 bg-bg-success text-txt-success" };
}

function categoryLabel(category: string) {
  return {
    discussions: "真人 / 使用者討論與評論",
    products: "相關產品",
    articles: "文章 / 研究",
    technical: "GitHub / 技術資料",
    other: "其他相關資料",
  }[category] || category;
}

function trackingFamilyLabel(value?: string) {
  return {
    general_web: "一般網頁",
    local_language: "本地語言搜尋",
    public_discussions: "Reddit / 公開討論",
    practitioner_communities: "實務社群 / Q&A",
    vendor_support_communities: "產品 / 產業支援社群",
    product_reviews: "產品評論",
    app_marketplaces: "App / 外掛市集",
    related_products: "相關產品搜尋",
    manual_workarounds: "人工 workaround",
    research_cases: "研究 / 案例",
    academic_sources: "論文 / 學術來源",
    b2b_operational_signals: "B2B 營運訊號",
    job_procurement_signals: "職缺 / 採購 / RFP",
    legacy_or_specialist: "HN / GitHub / 既有來源",
  }[String(value || "")] || String(value || "");
}

function cardSeenTime(card: ResearchBacklogCard) {
  return card.first_seen_at ? fmtTime(card.first_seen_at) : "—";
}

function MaterialCard({ card, category }: { card: ResearchBacklogCard; category: string }) {
  const grounding = card.source_grounding || {};
  const grounded = typeof grounding === "object" ? String((grounding as Record<string, unknown>).status || "") : "";
  return (
    <article className="min-w-0 rounded-xl border border-border-secondary bg-bg-primary p-3">
      <div className="flex flex-wrap items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">
        <span>{categoryLabel(category)}</span>
        {card.source ? <span>· {card.source}</span> : null}
        {card.tracking_family ? <span>· {trackingFamilyLabel(card.tracking_family)}</span> : null}
        {card.first_seen_at ? <span>· 首次找到 {cardSeenTime(card)}</span> : null}
      </div>
      <div className="mt-1.5 break-words text-[11px] font-semibold leading-4 text-text-primary">{card.title || "未命名資料"}</div>
      {card.excerpt ? <p className="mt-1.5 line-clamp-5 break-words text-[10px] leading-4 text-text-secondary">{card.excerpt}</p> : null}
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[10px] text-text-tertiary">
          <Link2 size={12} />
          <span>{grounded ? `來源核對 ${grounded}` : "保留原始連結"}</span>
          {n(card.seen_count) > 1 ? <span>· 追蹤到 {n(card.seen_count)} 次</span> : null}
        </div>
        {card.url ? (
          <a href={card.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-info/25 bg-bg-info px-2.5 py-1.5 text-[10px] font-semibold text-info hover:bg-bg-info/70">
            看原文 <ExternalLink size={11} />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function MaterialSection({ title, category, rows }: { title: string; category: string; rows: ResearchBacklogCard[] }) {
  if (!rows.length) return null;
  return (
    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        <div className="rounded-full border border-border-secondary bg-bg-secondary px-3 py-1.5 text-[10px] text-text-secondary">{rows.length} 筆</div>
      </div>
      <div className="mt-3 grid gap-2.5 lg:grid-cols-2 2xl:grid-cols-3">
        {rows.map((card, index) => <MaterialCard key={`${category}-${card.url || card.title}-${index}`} card={card} category={category} />)}
      </div>
    </section>
  );
}

function TraceRow({ row }: { row: ResearchHistoryEntry }) {
  const trace = row.research_trace || {};
  const runs = Array.isArray(trace.query_runs) ? trace.query_runs : [];
  return (
    <div className="rounded-xl border border-border-secondary bg-bg-secondary/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold text-text-primary">追蹤搜尋 · {fmtTime(row.completed_at)}</div>
        <div className="text-[10px] text-text-tertiary">{row.status || "—"}</div>
      </div>
      <div className="mt-2 text-[10px] text-text-secondary">
        討論 {n(row.counts?.human)} · 產品 {n(row.counts?.products)} · 技術 {n(row.counts?.repos)} · 其他 {n(row.counts?.supporting) + n(row.counts?.counter)} · 搜尋角度 {runs.length}
      </div>
      {runs.length ? (
        <div className="mt-3 space-y-1.5 text-[10px] leading-4 text-text-tertiary">
          {runs.slice(-8).map((run, index) => {
            const value = run as Record<string, unknown>;
            return <div key={index}>• {String(value.label || "SEARCH")}: {String(value.retrieval_query || "")}</div>;
          })}
        </div>
      ) : null}
    </div>
  );
}


const WORKSPACE_LIST_CACHE_KEY = "signalforge:research-backlog:v254:list";
const WORKSPACE_SELECTED_KEY = "signalforge:research-backlog:v254:selected";
const WORKSPACE_DETAIL_PREFIX = "signalforge:research-backlog:v254:detail:";
const WORKSPACE_DETAIL_INDEX_KEY = "signalforge:research-backlog:v254:detail-index";
const DETAIL_CACHE_LIMIT = 6;
const ACTIVE_REFRESH_MS = 12_000;
const IDLE_REFRESH_MS = 30_000;
const FOCUS_STALE_MS = 15_000;

type CachedListSnapshot = { saved_at: number; data: ResearchBacklogResponse };
type CachedDetailSnapshot = { saved_at: number; item: ResearchBacklogItem };

function safeSessionGet(key: string) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function safeSessionSet(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* Cache is an optimization only. */ }
}

function safeSessionRemove(key: string) {
  try { window.localStorage.removeItem(key); } catch { /* noop */ }
}

function lightweightListItem(item: ResearchBacklogItem): ResearchBacklogItem {
  const summary: ResearchBacklogItem = { ...item };
  delete summary.material_library;
  delete summary.history;
  delete summary.handoff;
  delete summary.aliases;
  return summary;
}

function readListSnapshot(): ResearchBacklogResponse {
  const raw = safeSessionGet(WORKSPACE_LIST_CACHE_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as CachedListSnapshot;
    return parsed?.data && typeof parsed.data === "object" ? parsed.data : {};
  } catch {
    return {};
  }
}

function writeListSnapshot(data: ResearchBacklogResponse) {
  const compact: ResearchBacklogResponse = {
    ...data,
    items: (data.items || []).map(lightweightListItem),
    founder_inbox: (data.founder_inbox || []).map(lightweightListItem),
  };
  safeSessionSet(WORKSPACE_LIST_CACHE_KEY, JSON.stringify({ saved_at: Date.now(), data: compact } satisfies CachedListSnapshot));
}

function readSelectedId() {
  return safeSessionGet(WORKSPACE_SELECTED_KEY) || "";
}

function writeSelectedId(itemId: string) {
  if (itemId) safeSessionSet(WORKSPACE_SELECTED_KEY, itemId);
}

function readDetailSnapshot(itemId: string): ResearchBacklogItem | null {
  if (!itemId) return null;
  const raw = safeSessionGet(`${WORKSPACE_DETAIL_PREFIX}${itemId}`);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as CachedDetailSnapshot;
    return parsed?.item?.id === itemId ? parsed.item : null;
  } catch {
    return null;
  }
}

function writeDetailSnapshot(item: ResearchBacklogItem) {
  if (!item?.id) return;
  safeSessionSet(`${WORKSPACE_DETAIL_PREFIX}${item.id}`, JSON.stringify({ saved_at: Date.now(), item } satisfies CachedDetailSnapshot));
  let index: string[] = [];
  try { index = JSON.parse(safeSessionGet(WORKSPACE_DETAIL_INDEX_KEY) || "[]"); } catch { index = []; }
  index = [item.id, ...index.filter((value) => value !== item.id)].slice(0, DETAIL_CACHE_LIMIT);
  safeSessionSet(WORKSPACE_DETAIL_INDEX_KEY, JSON.stringify(index));
  const keep = new Set(index);
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key?.startsWith(WORKSPACE_DETAIL_PREFIX)) {
        const id = key.slice(WORKSPACE_DETAIL_PREFIX.length);
        if (!keep.has(id)) safeSessionRemove(key);
      }
    }
  } catch { /* noop */ }
}

function normalized(value?: string | null) {
  return String(value || "").trim().toLocaleLowerCase();
}

function itemMatchesQuery(item: ResearchBacklogItem, query: string) {
  const needle = normalized(query);
  if (!needle) return true;
  const haystack = normalized([item.title, item.description, item.why, item.current_call, item.source_kind].filter(Boolean).join(" "));
  return haystack.includes(needle);
}

function itemMatchesStatus(item: ResearchBacklogItem, filter: string) {
  if (!filter) return true;
  const raw = String(item.auto_status || "").toUpperCase();
  if (filter === "NEW_DATA") return Boolean(item.has_new_data) || n(item.new_material_count) > 0;
  if (filter === "TRACKING") return Boolean(item.tracking_enabled) && raw !== "SEARCHING" && raw !== "SOURCE_LIMITED";
  return raw === filter;
}

function detailNeedsRefresh(summary: ResearchBacklogItem | undefined, detail: ResearchBacklogItem | null) {
  if (!summary || !detail || summary.id !== detail.id) return Boolean(summary);
  if (summary.updated_at && summary.updated_at !== detail.updated_at) return true;
  if (n(summary.research_count) !== n(detail.research_count)) return true;
  if (n(summary.tracking_cycle_count) !== n(detail.tracking_cycle_count)) return true;
  if (n(summary.new_material_count) !== n(detail.new_material_count)) return true;
  if (n(summary.material_stats?.total) !== n(detail.material_stats?.total)) return true;
  return false;
}

export default function ResearchBacklog() {
  const initialData = useMemo(() => readListSnapshot(), []);
  const initialSelectedId = useMemo(() => {
    const remembered = readSelectedId();
    if (remembered) return remembered;
    return initialData.items?.[0]?.id || "";
  }, [initialData]);
  const initialDetail = useMemo(() => {
    const cached = readDetailSnapshot(initialSelectedId);
    if (cached) return cached;
    return initialData.items?.find((item) => item.id === initialSelectedId) || null;
  }, [initialData, initialSelectedId]);

  const [data, setData] = useState<ResearchBacklogResponse>(initialData);
  const [selectedId, setSelectedId] = useState(initialSelectedId);
  const [selectedDetail, setSelectedDetail] = useState<ResearchBacklogItem | null>(initialDetail);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const [showAdd, setShowAdd] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");

  const selectedIdRef = useRef(selectedId);
  const selectedDetailRef = useRef<ResearchBacklogItem | null>(selectedDetail);
  const listRequestSeq = useRef(0);
  const detailRequestSeq = useRef(0);
  const lastRefreshAtRef = useRef(0);

  useEffect(() => { selectedIdRef.current = selectedId; if (selectedId) writeSelectedId(selectedId); }, [selectedId]);
  useEffect(() => { selectedDetailRef.current = selectedDetail; }, [selectedDetail]);

  const loadList = useCallback(async (silent = true) => {
    const seq = ++listRequestSeq.current;
    if (!silent) setBusy("refresh");
    try {
      // Always load the canonical full list. Search/status are instant local filters and never start a server round-trip.
      const next = await getResearchBacklog({ limit: 1000 });
      if (seq !== listRequestSeq.current) return null;
      setData(next);
      writeListSnapshot(next);
      lastRefreshAtRef.current = Date.now();
      setError("");
      const current = selectedIdRef.current;
      const items = next.items || [];
      if (!current && items.length) setSelectedId(items[0].id);
      else if (current && !items.some((item) => item.id === current) && items.length) setSelectedId(items[0].id);
      return next;
    } catch (err) {
      if (seq === listRequestSeq.current) setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      if (!silent && seq === listRequestSeq.current) setBusy("");
    }
  }, []);

  const loadDetail = useCallback(async (itemId: string) => {
    if (!itemId) return null;
    const seq = ++detailRequestSeq.current;
    try {
      const result = await getResearchBacklogDetail(itemId);
      const item = result.item || null;
      if (seq !== detailRequestSeq.current || selectedIdRef.current !== itemId) return item;
      if (item) {
        setSelectedDetail(item);
        writeDetailSnapshot(item);
      }
      setError("");
      return item;
    } catch (err) {
      if (seq === detailRequestSeq.current && selectedIdRef.current === itemId) setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  const revalidateWorkspace = useCallback(async (explicit = false) => {
    const next = await loadList(!explicit);
    const itemId = selectedIdRef.current;
    if (!next || !itemId) return;
    const summaryItem = (next.items || []).find((item) => item.id === itemId);
    if (detailNeedsRefresh(summaryItem, selectedDetailRef.current)) void loadDetail(itemId);
  }, [loadDetail, loadList]);

  useEffect(() => {
    // Stale-while-revalidate: cached list/detail render first; network freshness is background work.
    void revalidateWorkspace(false);
  }, [revalidateWorkspace]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedDetail(null);
      return;
    }
    setCopyState("idle");
    const cached = readDetailSnapshot(selectedId);
    if (cached) setSelectedDetail(cached);
    else {
      const summaryItem = (data.items || []).find((item) => item.id === selectedId) || null;
      setSelectedDetail(summaryItem);
    }
    void loadDetail(selectedId);
  // Selection is the only trigger. q/status changes must never refetch detail.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, loadDetail]);

  useEffect(() => {
    let timer: number | undefined;
    let disposed = false;
    const clear = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
    };
    const schedule = () => {
      clear();
      if (disposed || document.visibilityState !== "visible") return;
      const worker = data.worker || {};
      const active = n(worker.active_count) > 0 || ["RUNNING", "SEARCHING"].includes(String(worker.status || "").toUpperCase());
      timer = window.setTimeout(async () => {
        if (disposed || document.visibilityState !== "visible") return;
        await revalidateWorkspace(false);
        schedule();
      }, active ? ACTIVE_REFRESH_MS : IDLE_REFRESH_MS);
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") {
        clear();
        return;
      }
      if (Date.now() - lastRefreshAtRef.current >= FOCUS_STALE_MS) void revalidateWorkspace(false).finally(schedule);
      else schedule();
    };
    document.addEventListener("visibilitychange", onVisibility);
    schedule();
    return () => {
      disposed = true;
      clear();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [data.worker, revalidateWorkspace]);

  const visibleItems = useMemo(
    () => (data.items || []).filter((item) => itemMatchesQuery(item, q) && itemMatchesStatus(item, status)),
    [data.items, q, status],
  );

  const summary = data.tracking_summary || {};
  const worker = data.worker || {};
  const automation = data.automation || {};
  const paused = Boolean(automation.paused_by_founder);
  const selected = selectedDetail || (data.items || []).find((item) => item.id === selectedId) || null;
  const library: MaterialLibrary = selected?.material_library || {};
  const stats = selected?.material_stats || {};

  const allMaterials = useMemo(() => {
    const rows: Array<{ category: string; card: ResearchBacklogCard }> = [];
    for (const category of ["products", "discussions", "articles", "technical", "other"] as const) {
      for (const card of library[category] || []) rows.push({ category, card });
    }
    return rows.sort((a, b) => {
      const at = new Date(a.card.first_seen_at || 0).getTime();
      const bt = new Date(b.card.first_seen_at || 0).getTime();
      return bt - at;
    });
  }, [library]);

  const newMaterials = useMemo(() => {
    if (!selected?.founder_reviewed_at) return allMaterials;
    const cutoff = new Date(selected.founder_reviewed_at).getTime();
    return allMaterials.filter(({ card }) => new Date(card.first_seen_at || 0).getTime() > cutoff);
  }, [allMaterials, selected?.founder_reviewed_at]);

  async function toggleTracking() {
    setBusy(paused ? "resume" : "pause");
    try {
      if (paused) await startResearchBacklog(500);
      else await stopResearchBacklog();
      await loadList(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function refreshSelected() {
    if (!selectedId) return;
    setBusy("selected-refresh");
    try {
      await refreshResearchBacklogItem(selectedId);
      await loadList(true);
      await loadDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function addIdea() {
    if (!newTitle.trim()) return;
    setBusy("add");
    try {
      const result = await addResearchBacklogIdeas([{ title: newTitle.trim(), description: newDescription.trim() || newTitle.trim(), source_kind: "USER_SUBMITTED" }]);
      setNewTitle("");
      setNewDescription("");
      setShowAdd(false);
      const nextId = result.added_ids?.[0] || result.refreshed_ids?.[0];
      await loadList(true);
      if (nextId) setSelectedId(nextId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  }

  async function copyHandoff() {
    if (!selected?.handoff) return;
    try {
      await navigator.clipboard.writeText(selected.handoff);
      setCopyState("copied");
      if (selected.handoff_hash) await acknowledgeResearchBacklogHandoff(selected.id, selected.handoff_hash);
      await loadList(true);
      await loadDetail(selected.id);
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const activeNames = (worker.active_jobs || []).map((job) => data.items?.find((item) => item.id === job.item_id)?.title || job.item_id).filter(Boolean).slice(0, 6);

  return (
    <div className="min-h-screen min-w-0 overflow-x-hidden bg-bg-secondary text-text-primary">
      <div className="mx-auto w-full min-w-0 max-w-[1480px] px-3 py-3 md:px-4">
        <header className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold text-info"><Globe2 size={15} /> SignalForge</div>
              <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-text-primary">商機自動追蹤</h1>
              <p className="mt-1.5 max-w-3xl text-xs leading-5 text-text-secondary">
                SignalForge 只負責持續找跟 idea 有關的公開資料、相關產品與原始來源。商機研究、比較與判斷交給 ChatGPT / Founder。
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-1.5">
              <button type="button" onClick={() => void revalidateWorkspace(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-border-secondary bg-bg-secondary px-3 py-2 text-[11px] font-semibold text-text-secondary">
                <RefreshCw size={13} className={busy === "refresh" ? "animate-spin" : ""} /> 重新整理
              </button>
              <button type="button" onClick={() => setShowAdd((value) => !value)} className="inline-flex items-center gap-1.5 rounded-lg border border-border-secondary bg-bg-secondary px-3 py-2 text-[11px] font-semibold text-text-secondary">
                <Plus size={14} /> 加方向
              </button>
              <button type="button" onClick={() => void toggleTracking()} className="inline-flex items-center gap-1.5 rounded-lg bg-text-primary px-3 py-2 text-[11px] font-semibold text-bg-primary">
                {paused ? <Play size={14} /> : <CirclePause size={14} />}{paused ? "開始追蹤" : "暫停追蹤"}
              </button>
            </div>
          </div>

          {showAdd ? (
            <div className="mt-5 grid gap-3 rounded-2xl border border-border-secondary bg-bg-secondary p-4 md:grid-cols-[1fr_1.6fr_auto]">
              <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="商機 / idea 標題" className="rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs outline-none focus:border-info/50" />
              <input value={newDescription} onChange={(e) => setNewDescription(e.target.value)} placeholder="誰、什麼情境、遇到什麼問題（可以很短）" className="rounded-xl border border-border-secondary bg-bg-primary px-3 py-2.5 text-xs outline-none focus:border-info/50" />
              <button type="button" disabled={!newTitle.trim() || busy === "add"} onClick={() => void addIdea()} className="rounded-xl bg-text-primary px-4 py-2.5 text-xs font-semibold text-bg-primary disabled:opacity-40">加入追蹤</button>
            </div>
          ) : null}

          <div className="mt-4 grid gap-2 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
            {[
              ["追蹤方向", n(summary.directions)],
              ["搜尋中", n(summary.searching)],
              ["有新資料", n(summary.directions_with_new_data)],
              ["新資料", n(summary.new_materials)],
              ["新相關產品", n(summary.new_products)],
              ["來源受限", n(summary.source_limited)],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2.5">
                <div className="text-[10px] font-semibold text-text-tertiary">{label}</div>
                <div className="mt-0.5 text-lg font-semibold text-text-primary">{value}</div>
              </div>
            ))}
          </div>

          <div className="mt-3 rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2.5 text-[10px] leading-4 text-text-secondary">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <Activity size={13} className="text-info" />
              <span className="font-semibold text-text-primary">自動追蹤：{paused ? "PAUSED" : String(worker.status || "IDLE")}</span>
              <span>· {n(worker.active_count)} active</span>
              <span>· {n(worker.queued_jobs_estimate)} queued</span>
              <span>· concurrency {n(worker.max_concurrency) || 6}</span>
              <span>· 每 {fmtInterval(summary.tracking_interval_seconds)} 重查</span>
              <span>· 首次擴展 {n(summary.broad_query_fanout) || 10} 個搜尋角度</span>
              <span>· 後續 {n(summary.refresh_query_fanout) || 5} 個</span>
            </div>
            {activeNames.length ? <div className="mt-1 truncate text-text-tertiary">正在找：{activeNames.join("、")}</div> : null}
            <div className="mt-1 text-text-tertiary">來源面：Reddit / 實務社群 / 產品評論 / 支援論壇 / 相關產品 / 人工 workaround / 研究案例 / B2B 營運 / 職缺與 RFP + HN / GitHub / 一般網頁；資料不足時會自動針對缺口深挖。</div>
            {worker.last_error ? <div className="mt-1 text-warning">{worker.last_error}</div> : null}
          </div>
          {error ? <div className="mt-3 rounded-2xl border border-danger/30 bg-bg-danger p-3 text-xs text-danger">{error}</div> : null}
        </header>

        <section className="mt-3 grid min-w-0 gap-3 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="min-w-0 rounded-2xl border border-border-secondary bg-bg-primary p-3 xl:sticky xl:top-3 xl:max-h-[calc(100vh-1.5rem)] xl:overflow-hidden">
            <div className="flex gap-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border-secondary bg-bg-secondary px-2.5 py-2">
                <Search size={13} className="text-text-tertiary" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`即時搜尋 ${n(data.total)} 個方向`} className="min-w-0 flex-1 bg-transparent text-xs outline-none" />
              </label>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-[92px] rounded-lg border border-border-secondary bg-bg-secondary px-2 text-[11px] text-text-secondary outline-none">
                <option value="">全部</option>
                <option value="NEW_DATA">有新資料</option>
                <option value="TRACKING">自動追蹤</option>
                <option value="SEARCHING">搜尋中</option>
                <option value="SOURCE_LIMITED">來源受限</option>
              </select>
            </div>
            <div className="mt-2 text-[10px] text-text-tertiary">{visibleItems.length} / {n(data.total)} 個方向</div>
            <div className="mt-2 space-y-1.5 overflow-y-auto pr-1 xl:max-h-[calc(100vh-112px)]">
              {visibleItems.map((item) => {
                const meta = statusMeta(item.auto_status, item.has_new_data);
                const itemStats = item.material_stats || {};
                return (
                  <button key={item.id} type="button" onClick={() => { setSelectedDetail(readDetailSnapshot(item.id) || item); setSelectedId(item.id); }} className={`w-full rounded-xl border p-2.5 text-left transition ${selectedId === item.id ? "border-info/40 bg-bg-info" : "border-border-secondary bg-bg-secondary/45 hover:bg-bg-secondary"}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 line-clamp-2 text-[11px] font-semibold leading-4 text-text-primary">{item.title}</div>
                      <span className={`shrink-0 rounded-full border px-2 py-1 text-[9px] font-semibold ${meta.cls}`}>{meta.label}</span>
                    </div>
                    <div className="mt-1.5 text-[9px] leading-4 text-text-secondary">
                      累積 {n(itemStats.total)} · 討論 {n(itemStats.discussions)} · 產品 {n(itemStats.products)}
                      {n(item.new_material_count) ? <span className="text-txt-success"> · 新增 {n(item.new_material_count)}</span> : null}
                    </div>
                    <div className="mt-0.5 line-clamp-2 text-[9px] leading-4 text-text-tertiary">{item.why || item.description}</div>
                  </button>
                );
              })}
              {!visibleItems.length ? (
                <div className="rounded-xl border border-dashed border-border-secondary bg-bg-secondary/45 px-3 py-5 text-center text-[10px] leading-4 text-text-tertiary">
                  找不到符合的方向。這個搜尋只篩目前已載入的方向，不會重新啟動研究。
                </div>
              ) : null}
            </div>
          </aside>

          <main className="min-w-0 space-y-3">
            {selected ? (
              <>
                <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-semibold text-text-primary">{selected.title}</h2>
                        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${statusMeta(selected.auto_status, selected.has_new_data).cls}`}>{statusMeta(selected.auto_status, selected.has_new_data).label}</span>
                      </div>
                      <p className="mt-1.5 max-w-4xl text-xs leading-5 text-text-secondary">{selected.description}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-1.5">
                      <button type="button" onClick={() => void refreshSelected()} disabled={busy === "selected-refresh"} className="inline-flex items-center gap-1.5 rounded-lg border border-border-secondary bg-bg-secondary px-3 py-2 text-[11px] font-semibold text-text-secondary disabled:opacity-50">
                        {busy === "selected-refresh" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} 立即追蹤
                      </button>
                      <button type="button" onClick={() => void copyHandoff()} className="inline-flex items-center gap-1.5 rounded-lg bg-text-primary px-3 py-2 text-[11px] font-semibold text-bg-primary">
                        {copyState === "copied" ? <Check size={14} /> : <Copy size={14} />} {copyState === "copied" ? "已複製" : "給 ChatGPT"}
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-2 grid-cols-2 md:grid-cols-4 2xl:grid-cols-7">
                    {[
                      ["累積資料", n(stats.total)],
                      ["可能相關（仍保留）", n(stats.possibly_related)],
                      ["真人 / 使用者材料", n(stats.discussions)],
                      ["相關產品", n(stats.products)],
                      ["文章 / 研究", n(stats.articles)],
                      ["技術資料", n(stats.technical)],
                      ["尚未回報的新資料", n(stats.new_total)],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-xl border border-border-secondary bg-bg-secondary p-2.5">
                        <div className="text-[9px] font-semibold text-text-tertiary">{label}</div>
                        <div className="mt-0.5 text-base font-semibold text-text-primary">{value}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[9px] text-text-tertiary">
                    <span>上次檢查：{fmtTime(selected.last_checked_at)}</span>
                    <span>下次自動追蹤：{fmtTime(selected.next_track_after)}</span>
                    <span>已跑 {n(selected.tracking_cycle_count)} 輪追蹤</span>
                    <span>{selected.tracking_source_expansion_pending ? "等待 WideNet 補資料" : "WideNet 高召回追蹤已啟用"}</span>
                  </div>
                  {selected.tracking_family_stats && Object.keys(selected.tracking_family_stats).length ? (
                    <div className="mt-3 rounded-xl border border-border-secondary bg-bg-secondary p-3">
                      <div className="text-[9px] font-semibold text-text-tertiary">目前資料來自哪些搜尋面</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(selected.tracking_family_stats).slice(0, 10).map(([family, count]) => (
                          <span key={family} className="rounded-full border border-border-secondary bg-bg-primary px-2.5 py-1 text-[10px] text-text-secondary">
                            {trackingFamilyLabel(family)} {n(count)}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {selected.auto_status === "SOURCE_LIMITED" ? (
                    <div className="mt-3 rounded-2xl border border-warning/30 bg-bg-warning p-3 text-[11px] leading-5 text-warning">
                      來源暫時受限，之後會自動重試。這只代表來源問題，不代表沒有相關資料。
                      {selected.source_retry_after ? ` 下次重試 ${fmtTime(selected.source_retry_after)}` : ""}
                    </div>
                  ) : null}
                </section>

                {newMaterials.length ? (
                  <section className="rounded-2xl border border-success/25 bg-bg-primary p-4">
                    <div className="flex items-center gap-2"><Sparkles size={15} className="text-txt-success" /><h2 className="text-base font-semibold text-text-primary">上次回報後新增</h2></div>
                    <p className="mt-1 text-xs text-text-secondary">這裡只表示 SignalForge 新找到且跟 idea 有關，不代表它判斷這些資料很強。</p>
                    <div className="mt-3 grid gap-2.5 lg:grid-cols-2 2xl:grid-cols-3">
                      {newMaterials.slice(0, 20).map(({ card, category }, index) => <MaterialCard key={`new-${card.url || card.title}-${index}`} card={card} category={category} />)}
                    </div>
                  </section>
                ) : null}

                <MaterialSection title="相關產品 / 競品 / 替代方案" category="products" rows={library.products || []} />
                <MaterialSection title="真人 / 使用者討論、評論、留言、貼文" category="discussions" rows={library.discussions || []} />
                <MaterialSection title="文章 / 研究 / 案例" category="articles" rows={library.articles || []} />
                <MaterialSection title="GitHub / 技術資料" category="technical" rows={library.technical || []} />
                <MaterialSection title="其他相關資料" category="other" rows={library.other || []} />

                {!allMaterials.length ? (
                  <section className="rounded-2xl border border-border-secondary bg-bg-primary p-6 text-center">
                    <PackageSearch size={28} className="mx-auto text-text-tertiary" />
                    <div className="mt-3 text-sm font-semibold text-text-primary">目前還沒找到相關資料</div>
                    <p className="mt-1 text-xs text-text-secondary">SignalForge 會繼續追蹤；這不是市場判斷，也不代表這個問題不存在。</p>
                  </section>
                ) : null}

                <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
                  <div className="flex items-center gap-2"><Activity size={15} className="text-info" /><h2 className="text-base font-semibold text-text-primary">追蹤紀錄</h2></div>
                  <p className="mt-1 text-xs text-text-secondary">只記錄 SignalForge 查了什麼、哪些來源成功、找到多少相關資料；不是商機評分。</p>
                  <div className="mt-3 grid gap-2 lg:grid-cols-2 2xl:grid-cols-3">
                    {(selected.history || []).length ? [...(selected.history || [])].reverse().slice(0, 12).map((row) => <TraceRow key={row.research_id || `${row.completed_at}`} row={row} />) : <div className="rounded-2xl bg-bg-secondary p-4 text-xs text-text-secondary">還沒有追蹤紀錄。</div>}
                  </div>
                </section>

                <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold text-text-primary">給 ChatGPT 分析</h2>
                      <p className="mt-1 text-xs leading-5 text-text-secondary">這包會帶上相關產品、討論、文章／研究、技術資料與原始連結。複製成功後，這一批資料會被標成已回報；之後新找到的內容會重新亮起。</p>
                    </div>
                    <button type="button" onClick={() => void copyHandoff()} className="inline-flex items-center gap-1.5 rounded-lg bg-text-primary px-3 py-2 text-[11px] font-semibold text-bg-primary">
                      {copyState === "copied" ? <Check size={14} /> : <Copy size={14} />} {copyState === "copied" ? "已複製" : "複製完整資料包"}
                    </button>
                  </div>
                  <textarea readOnly value={selected.handoff || ""} rows={16} onFocus={(e) => e.currentTarget.select()} className="mt-3 w-full resize-y rounded-xl border border-border-secondary bg-bg-secondary p-3 font-mono text-[10px] leading-4 text-text-primary outline-none focus:border-info/50" />
                </section>
              </>
            ) : (
              <section className="rounded-2xl border border-border-secondary bg-bg-primary p-6 text-sm text-text-secondary">{selectedId ? "正在載入追蹤資料…" : "先從左邊選一個追蹤方向。"}</section>
            )}
          </main>
        </section>
      </div>
    </div>
  );
}
