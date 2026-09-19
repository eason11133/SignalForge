const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Keep HTTP status text when the body is not JSON.
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export type ResearchBacklogStatus =
  | "TRACKING_NEW"
  | "TRACKING_DUE"
  | "TRACKING"
  | "SEARCHING"
  | "SOURCE_LIMITED"
  | string;

export interface ResearchBacklogCard {
  source?: string;
  title?: string;
  excerpt?: string;
  url?: string;
  author?: string;
  match_level?: string;
  solution_type?: string;
  tracking_family?: string;
  search_query?: string;
  first_seen_at?: string;
  last_seen_at?: string;
  seen_count?: number;
  source_grounding?: Record<string, unknown>;
  evidence_trust?: Record<string, unknown>;
}

export interface OriginalPageCheck {
  url?: string;
  source?: string;
  title?: string;
  lane?: string;
  ok?: boolean;
  status?: number | null;
  final_url?: string | null;
  content_type?: string | null;
  bytes_read?: number;
  page_title?: string | null;
  error?: string | null;
}

export interface ResearchTrace {
  mode?: string;
  retrieval_query?: string;
  relevance_query?: string;
  query_bridge_status?: string;
  query_bridge_api_calls?: number;
  successful_sources?: string[];
  failed_sources?: Array<Record<string, unknown>>;
  source_attempts?: Array<Record<string, unknown>>;
  query_runs?: Array<Record<string, unknown>>;
  original_page_checks?: OriginalPageCheck[];
  search_metadata?: Record<string, unknown>;
}

export interface ResearchHistoryEntry {
  research_id?: string;
  job?: string;
  started_at?: string;
  completed_at?: string;
  status?: string;
  counts?: Record<string, number>;
  human_comments?: ResearchBacklogCard[];
  products?: ResearchBacklogCard[];
  repos?: ResearchBacklogCard[];
  supporting?: ResearchBacklogCard[];
  counterevidence?: ResearchBacklogCard[];
  successful_sources?: string[];
  failed_sources?: Array<Record<string, unknown>>;
  evidence_trust_gate?: Record<string, unknown>;
  traceability_gate?: Record<string, unknown>;
  research_trace?: ResearchTrace;
}

export interface MaterialLibrary {
  discussions?: ResearchBacklogCard[];
  products?: ResearchBacklogCard[];
  articles?: ResearchBacklogCard[];
  technical?: ResearchBacklogCard[];
  other?: ResearchBacklogCard[];
}

export interface MaterialStats {
  total?: number;
  direct_related?: number;
  possibly_related?: number;
  discussions?: number;
  products?: number;
  articles?: number;
  technical?: number;
  other?: number;
  new_total?: number;
  new_products?: number;
  today_total?: number;
  today_products?: number;
  latest_material_at?: string | null;
}

export interface ResearchBacklogItem {
  id: string;
  source_kind?: string;
  source_ref?: string | null;
  canonical_key?: string;
  title?: string;
  description?: string;
  source_context?: Record<string, unknown>;
  aliases?: Array<Record<string, unknown>>;
  import_rank?: number;
  auto_status?: ResearchBacklogStatus;
  tracking_enabled?: boolean;
  current_call?: string;
  why?: string;
  last_checked_at?: string | null;
  next_track_after?: string | null;
  tracking_cycle_count?: number;
  tracking_source_expansion_version?: string | null;
  tracking_source_expansion_pending?: boolean;
  material_library?: MaterialLibrary;
  material_stats?: MaterialStats;
  tracking_family_stats?: Record<string, number>;
  new_material_count?: number;
  new_product_count?: number;
  has_new_data?: boolean;
  last_tracking_delta?: Record<string, number | string>;
  founder_reviewed_at?: string | null;
  founder_reviewed_research_count?: number;
  research_count?: number;
  latest_research?: ResearchHistoryEntry | null;
  latest_change?: string;
  source_retry_count?: number;
  source_retry_after?: string | null;
  source_retry_reason?: string | null;
  legacy?: Record<string, unknown>;
  updated_at?: string;
  handoff?: string;
  handoff_hash?: string;
  history?: ResearchHistoryEntry[];
}

export interface ResearchBacklogWorker {
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  current_item_id?: string | null;
  current_job?: string | null;
  jobs_completed?: number;
  jobs_requested?: number;
  last_error?: string | null;
  stop_requested?: boolean;
  retry_attempts?: number;
  consecutive_source_limited?: number;
  session_jobs_completed?: number;
  batches_completed?: number;
  batch_size?: number;
  session_job_cap?: number;
  safety_cap_reached?: boolean;
  pending_after_session?: boolean;
  active_jobs?: Array<{ item_id?: string; job?: string; started_at?: string }>;
  active_count?: number;
  max_concurrency?: number;
  queued_jobs_estimate?: number;
}

export interface ResearchBacklogAutomation {
  auto_run_enabled?: boolean;
  paused_by_founder?: boolean;
  last_auto_start_at?: string | null;
  last_founder_resume_at?: string | null;
  last_founder_pause_at?: string | null;
  last_live_sync_at?: string | null;
  idle_poll_seconds?: number;
  continuous_batch_size?: number;
  session_job_cap?: number;
  source_circuit_open_count?: number;
  source_circuit_retry_after?: string | null;
  source_circuit_reason?: string | null;
  source_circuit_threshold?: number;
  research_concurrency?: number;
  tracking_mode?: string;
  tracking_interval_seconds?: number;
  source_expansion_version?: string;
  broad_query_fanout?: number;
  refresh_query_fanout?: number;
  source_families?: string[];
}

export interface TrackingSummary {
  directions?: number;
  tracking_enabled?: number;
  searching?: number;
  directions_with_new_data?: number;
  new_materials?: number;
  new_products?: number;
  source_limited?: number;
  paused?: number;
  tracking_interval_seconds?: number;
  source_expansion_pending?: number;
  broad_query_fanout?: number;
  refresh_query_fanout?: number;
  source_families?: string[];
}

export interface ResearchBacklogResponse {
  engine_version?: string;
  status?: string;
  total?: number;
  filtered?: number;
  counts?: Record<string, number>;
  tracking_summary?: TrackingSummary;
  founder_inbox?: ResearchBacklogItem[];
  founder_attention_total?: number;
  items?: ResearchBacklogItem[];
  worker?: ResearchBacklogWorker;
  automation?: ResearchBacklogAutomation;
  legacy_archive_summary?: Record<string, unknown>;
  import_warnings?: string[];
  market_truth_writes?: number;
  truth_boundary?: string;
}

export interface ResearchBacklogDetailResponse {
  status?: string;
  item?: ResearchBacklogItem;
  market_truth_writes?: number;
  truth_boundary?: string;
}

export interface ResearchRun {
  run_id?: string;
  item_id?: string;
  item_key?: string;
  status?: string;
  created_at?: string;
  started_at?: string;
  updated_at?: string;
  finished_at?: string | null;
  error?: string | null;
  duplicate_start_suppressed?: number;
  material_count?: number | null;
  original_http_status?: number | null;
  original_response?: {
    status?: string;
    id?: string;
    materials_added?: number;
    history_count?: number;
    paused_before?: boolean;
    paused_after?: boolean;
    market_truth_writes?: number;
    [key: string]: unknown;
  } | null;
  market_truth_writes?: number;
}

export interface ResearchRunStartResponse {
  run_id?: string;
  item_id?: string;
  item_key?: string;
  status?: string;
  research_run_status?: string;
  reason?: string;
  started?: boolean;
  worker_started?: boolean;
  worker_running?: boolean;
  running?: boolean;
  accepted?: boolean;
  duplicate_start_suppressed?: number;
  status_url?: string;
  research_continues_without_browser?: boolean;
  market_truth_writes?: number;
}

export async function getResearchBacklog(params?: { q?: string; status?: string; limit?: number }) {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return fetchJSON<ResearchBacklogResponse>(`/signalforge/research-backlog${suffix}`);
}

export async function getResearchBacklogDetail(itemId: string) {
  return fetchJSON<ResearchBacklogDetailResponse>(`/signalforge/research-backlog/${encodeURIComponent(itemId)}`);
}

export async function syncResearchBacklog() {
  return fetchJSON<{ status?: string; added?: number; refreshed?: number; merged_duplicates?: number; total?: number; auto_start?: { status?: string } }>(
    "/signalforge/research-backlog/sync",
    { method: "POST", body: JSON.stringify({ ideas: [] }) },
  );
}

export async function addResearchBacklogIdeas(ideas: Array<{ title?: string; description?: string; source_kind?: string }>) {
  return fetchJSON<{
    status?: string;
    added?: number;
    refreshed?: number;
    merged_duplicates?: number;
    added_ids?: string[];
    refreshed_ids?: string[];
    total?: number;
    auto_start?: { status?: string };
  }>(
    "/signalforge/research-backlog/ideas",
    { method: "POST", body: JSON.stringify({ ideas }) },
  );
}

export async function startResearchBacklog(maxJobs = 500) {
  return fetchJSON<{ status?: string; worker?: ResearchBacklogWorker }>(
    "/signalforge/research-backlog/start",
    { method: "POST", body: JSON.stringify({ max_jobs: maxJobs }) },
  );
}

export async function stopResearchBacklog() {
  return fetchJSON<{ status?: string; worker?: ResearchBacklogWorker }>(
    "/signalforge/research-backlog/stop",
    { method: "POST" },
  );
}

export async function refreshResearchBacklogItem(itemId: string) {
  return fetchJSON<{ status?: string; id?: string; auto_start?: { status?: string } }>(
    `/signalforge/research-backlog/${encodeURIComponent(itemId)}/refresh`,
    { method: "POST" },
  );
}

export async function runResearchBacklogItem(itemId: string) {
  return fetchJSON<ResearchRunStartResponse>(
    `/signalforge/research-backlog/${encodeURIComponent(itemId)}/run`,
    { method: "POST" },
  );
}

export async function getResearchBacklogRun(itemId: string) {
  return fetchJSON<{ version?: string; run?: ResearchRun | null; market_truth_writes?: number }>(
    `/signalforge/research-backlog/runs/${encodeURIComponent(itemId)}`,
  );
}

export async function acknowledgeResearchBacklogHandoff(itemId: string, handoffHash: string) {
  return fetchJSON<{ status?: string; id?: string; handoff_hash?: string; founder_reviewed_at?: string; new_material_count?: number }>(
    `/signalforge/research-backlog/${encodeURIComponent(itemId)}/handoff-copied`,
    { method: "POST", body: JSON.stringify({ handoff_hash: handoffHash }) },
  );
}
