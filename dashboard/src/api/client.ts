const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

// Types — matched to actual Pydantic schemas in api/models/schemas.py

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  per_page: number;
  items: T[];
}

export interface Topic {
  id: number;
  name: string;
  slug: string | null;
  description: string | null;
  keywords: string[] | null;
  velocity: number | null;
  total_mentions: number | null;
  sentiment_distribution: Record<string, number> | null;
  platforms_active: Record<string, number> | null;
  opinion_camps: Record<string, unknown>[] | null;
  status: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface TopicDetail extends Topic {
  top_posts: PostItem[];
  related_news: NewsEvent[];
}

export interface TimelinePoint {
  date: string;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  avg_sentiment: number | null;
}

export interface TopicTimeline {
  topic_id: number;
  topic_name: string;
  timeline: TimelinePoint[];
}

export interface PostItem {
  id: number;
  user_id: number | null;
  username: string | null;
  platform_id: number | null;
  platform_name: string | null;
  post_type: string | null;
  title: string | null;
  body: string | null;
  url: string | null;
  subreddit: string | null;
  score: number | null;
  num_comments: number | null;
  posted_at: string | null;
  sentiment: Record<string, unknown> | null;
}

export interface Persona {
  id: number;
  user_id: number;
  username: string | null;
  platform_name: string | null;
  personality_summary: string | null;
  inferred_role: string | null;
  expertise_domains: Record<string, unknown>[] | null;
  core_beliefs: Record<string, unknown>[] | null;
  communication_style: Record<string, unknown> | null;
  emotional_triggers: Record<string, unknown>[] | null;
  influence_score: number | null;
  inferred_location: string | null;
  active_topics: string[] | null;
  system_prompt: string | null;
  karma: number | null;
  post_count: number | null;
  first_seen: string | null;
}

export interface PersonaDetail extends Persona {
  top_posts: PostItem[];
  connections: GraphEdge[];
}

export interface NewsEvent {
  id: number;
  source_type: string;
  source_name: string | null;
  title: string;
  body: string | null;
  url: string | null;
  authors: unknown[] | null;
  published_at: string | null;
  categories: unknown[] | null;
  entities: Record<string, unknown> | null;
  sentiment: number | null;
  magnitude: string | null;
}

export interface NewsImpact {
  event: NewsEvent;
  reactions: Record<string, unknown>[];
  platforms_reacted: string[];
  avg_community_sentiment: number | null;
}

export interface Leader {
  id: number;
  user_id: number;
  username: string | null;
  platform_name: string | null;
  influence_score: number | null;
  inferred_role: string | null;
  inferred_location: string | null;
  personality_summary: string | null;
  core_beliefs: Record<string, unknown>[] | null;
  active_topics: string[] | null;
}

// Wrapper types matching actual API responses
interface PulseResponse { topics: Topic[] }
interface DebateResponse { debates: DebateItem[] }
interface ResearchResponse { papers: NewsEvent[] }
interface FundingResponse { events: NewsEvent[] }
interface GeoResponse { locations: GeoItem[] }

export interface DebateItem {
  id: number;
  name: string;
  slug: string;
  opinion_camps: unknown;
  sentiment_distribution: Record<string, number>;
  total_mentions: number;
  polarization_score: number;
}

export interface JobTrend {
  weekly_counts: { week: string; count: number }[];
  recent_listings: Record<string, unknown>[];
  role_cards?: { role: string; count: number; growth: number }[];
}

export interface GeoItem {
  location: string;
  user_count: number;
  avg_influence: number;
  top_topics: string[];
}

export interface GraphEdge {
  connected_user_id: number;
  connected_username: string | null;
  interaction_type: string | null;
  interaction_count: number | null;
  avg_sentiment: number | null;
}

export interface Overview {
  total_users: number;
  total_posts: number;
  total_personas: number;
  total_topics: number;
  news_by_source: Record<string, number>;
  trending_topics: Topic[];
  top_leaders: Leader[];
  latest_news: NewsEvent[];
  scraper_health: Record<string, unknown>[];
}

export interface SpendingHistoryItem {
  phase: string;
  cost_usd: number;
  cumulative_usd: number;
  details: string;
  timestamp: string | null;
}

export interface SpendingStatus {
  currency: "USD";
  tracked_scope: string;
  total_spent_usd: number;
  today_spent_usd: number;
  today_calls: number;
  cap_usd: number;
  remaining_usd: number;
  used_pct: number;
  history_count: number;
  recent: SpendingHistoryItem[];
  updated_at: string;
}

export interface SearchResults {
  posts: PostItem[];
  news: NewsEvent[];
  topics: Topic[];
  users: { id: number; username: string | null; platform_name: string | null }[];
}

// ── Intelligence Types ─────────────────────────────────────────

export interface Product {
  id: number;
  canonical_name: string;
  category: string | null;
  aliases: string[] | null;
  confidence: number | null;
  status: string | null;
  discovered_by: string | null;
  total_mentions: number;
  last_seen_at: string | null;
  recommendation_rate: number | null;
  avg_sentiment: number | null;
  trend: string | null;
}

export interface MigrationAggregate {
  from_product: string;
  to_product: string;
  count: number;
  avg_confidence: number | null;
}

export interface Migration {
  id: number;
  from_product: string;
  to_product: string;
  from_product_id: number | null;
  to_product_id: number | null;
  reason: string | null;
  confidence: number | null;
  confirmed_by: string | null;
  count: number;
  detected_at: string | null;
}

export interface PainPoint {
  id: number;
  title: string;
  description: string | null;
  intensity_score: number | null;
  has_solution: boolean | null;
  mentioned_products: string[] | null;
  platforms: string[] | null;
  sample_quotes: string[] | null;
  topic_id: number | null;
  topic_name: string | null;
  post_count: number | null;
  status: string | null;
  created_at: string | null;
}

export interface HypeIndexItem {
  id: number;
  topic_id: number | null;
  sector_name: string | null;
  topic_name: string | null;
  builder_sentiment: number | null;
  vc_sentiment: number | null;
  gap: number | null;
  status: string | null;
  builder_post_count: number | null;
  vc_post_count: number | null;
  calculated_at: string | null;
}

export interface LeaderShift {
  id: number;
  persona_id: number | null;
  persona_name: string | null;
  topic_id: number | null;
  topic_name: string | null;
  old_stance: string | null;
  new_stance: string | null;
  shift_type: string | null;
  trigger: string | null;
  summary: string | null;
  old_sentiment: number | null;
  new_sentiment: number | null;
  detected_at: string | null;
}

export interface FundingRound {
  id: number;
  company_name: string;
  amount: string | null;
  stage: string | null;
  sector: string | null;
  location: string | null;
  news_event_id: number | null;
  community_sentiment: number | null;
  community_post_count: number | null;
  reaction_summary: string | null;
  announced_at: string | null;
}

export interface PlatformTone {
  id: number;
  topic_id: number | null;
  platform_name: string | null;
  tone_description: string | null;
  post_count: number | null;
  avg_sentiment: number | null;
  analyzed_at: string | null;
}

export interface JobAnalysis {
  total_listings_90d: number;
  role_trends: { role: string; total_90d: number; total_30d: number }[];
  geo_breakdown: { location: string; count: number }[];
}

// ── Job Intelligence Types (LLM-extracted) ────────────────────

export interface JobIntelSummary {
  total_jobs: number;
  total_processed: number;
  coverage_pct: number;
  by_role: { role: string; count: number }[];
  by_seniority: { seniority: string; count: number }[];
  by_market: { market: string; count: number }[];
  by_ai_level: { level: string; count: number }[];
  by_remote_policy: { policy: string; count: number }[];
}

export interface TechStackItem {
  name: string;
  category: string;
  mentions: number;
}

export interface SalaryBand {
  role: string;
  seniority: string;
  sample_size: number;
  p25_min: number | null;
  median_min: number | null;
  p75_max: number | null;
  median_max: number | null;
  avg_min: number | null;
  avg_max: number | null;
}

export interface HiringVelocityCompany {
  company: string;
  open_roles: number;
  market: string | null;
  stage: string | null;
  ai_level: string | null;
  role_types: string[];
  urgent_roles: number;
}

export interface JobGeoData {
  by_country: { country: string; count: number; remote_count: number }[];
  by_city: { city: string; country: string; count: number }[];
}

export interface AILandscape {
  ai_by_market: { market: string; ai_level: string; count: number }[];
  top_ai_tools: { tool: string; mentions: number }[];
  roles_at_ai_companies: { role: string; count: number; avg_salary_min: number | null; avg_salary_max: number | null }[];
}

export interface CompanyStage {
  stage: string;
  jobs: number;
  companies: number;
  avg_salary_min: number | null;
  avg_salary_max: number | null;
}

export interface BenefitsCulture {
  top_benefits: { benefit: string; count: number }[];
  top_culture_signals: { signal: string; count: number }[];
}

export interface SkillDemand {
  skill: string;
  type: string;
  mentions: number;
}

export interface OpportunityEvidenceItem {
  id:number; post_id:number|null; source_type:string; platform:string|null; source_ref:string|null;
  evidence_type:string; title:string|null; excerpt:string|null; url:string|null; strength:number|null; observed_at:string|null;
}
export interface OpportunityItem {
  id:number; canonical_key:string; title:string; problem_statement:string|null; who_has_problem:string|null; why_now:string|null; status:string;
  opportunity_score:number; confidence_score:number; pain_score:number; demand_score:number; growth_score:number; buyer_score:number; supply_gap_score:number; cross_source_score:number;
  independent_users:number; evidence_count:number; source_counts:Record<string,number>; score_breakdown:Record<string,unknown>; workarounds:string[]; existing_solutions:string[]; buyer_signals:string[];
  cluster_cohesion:number|null; first_seen_at:string|null; last_seen_at:string|null; calculated_at:string|null; updated_at:string|null;
}
export interface OpportunityDetail extends OpportunityItem { evidence:OpportunityEvidenceItem[]; }
export interface OpportunitySummary { total:number; high_score:number; high_confidence:number; statuses:Record<string,number>; }

export interface CandidateEvidenceItem {id:number;source_type:string;source_table:string|null;source_ref:string|null;relation:string;title:string|null;excerpt:string|null;url:string|null;retrieval_score:number|null;verified:boolean;verification_confidence:number|null;metadata:Record<string,unknown>;}
export interface ProblemCandidateItem {id:number;canonical_key:string;title:string;problem_statement:string|null;actor:string|null;actor_category:string|null;task:string|null;object:string|null;failure_mode:string|null;consequence:string|null;buyer_context:string|null;workaround:string|null;community_platform:string|null;discussion_key:string|null;community_evidence_count:number;community_user_count:number;stage:string;founder_status:string;market_score:number;confidence_score:number;community_problem_score:number;corroboration_score:number;buyer_demand_score:number;supply_gap_score:number;cross_source_score:number;source_support:Record<string,number>;relation_support:Record<string,number>;fingerprint:Record<string,unknown>;first_seen_at:string|null;last_seen_at:string|null;calculated_at:string|null;updated_at:string|null;}
export interface ProblemCandidateDetail extends ProblemCandidateItem {evidence:CandidateEvidenceItem[];}
export interface ProblemCandidateSummary {total:number;stages:Record<string,number>;active_founder_work:number;}

export interface SignalForgeEvidenceQuery { source_group?:string; purpose?:string; query?:string; claims?:string[]; }
export interface SignalForgeDailyCard {
  case_id:number; candidate_id:number|null; title:string; verdict:string; attention_score:number;
  why_now:string[]; decision_reason:string; biggest_unknown:string; machine_action:string; founder_action:string;
  market_validation_boundary:string; buyer_organizations:string[]; claims:Record<string,string>;
  reality:Record<string,unknown>; progression:Record<string,unknown>;
  next_evidence_queries?:SignalForgeEvidenceQuery[];
  company_gap_plan?:Array<{capability?:string;status?:string;action?:string;boundary?:string}>;
  solo_transition?:{classification?:string;problem_shape?:string;problem_specificity_score?:number;transition_gap?:string;economic_necessity?:string;solo_fit?:string;solo_score?:number;next_gate?:string;disqualifiers?:string[]};
}
export interface SignalForgeOpportunityEvidence {
  claim_code:string; claim_state:string; stance:string; validated:boolean;
  interpretation_confidence:number|null; rationale:string;
  source_type:string; source_title:string; excerpt:string; source_url:string|null;
  source_family_key:string; directness:string; authority_class:string;
  raw_metadata:Record<string,unknown>;
}
export interface SignalForgeOpportunityDetail {
  status:string; candidate_id:number; case_id:number|null;
  claim_states:Record<string,string>;
  solo_assessment?:{classification?:string;problem_shape?:string;problem_specificity_score?:number;transition_gap?:string;economic_necessity?:string;solo_fit?:string;solo_score?:number;next_gate?:string;disqualifiers?:string[]};
  current_solutions:string[];
  competitive_context:string[];
  solution_evidence:SignalForgeOpportunityEvidence[];
  gap_evidence:SignalForgeOpportunityEvidence[];
  published_evidence:SignalForgeOpportunityEvidence[];
  failure_reasons:string[];
  truth_boundary?:string;
}

export interface SignalForgeResearchGapProgress {
  gap:string; gap_id?:string; attempts?:number; retrieved_candidates?:number; adjudicated?:number;
  confirmed_independent_support?:number; confirmed_refute?:number; dependent_duplicates?:number;
  zero_confirmed_yield_streak?:number; state?:string; marginal_voi?:number; last_query?:string|null;
}
export interface SignalForgeResearchRequest {
  request_id?:string; gap?:string; query?:string; adapter?:string; surface?:string; seconds?:number; error?:string|null;
  candidate_count?:number; confirmed_count?:number; confirmed_source_groups?:string[]; marginal_voi_after?:number;
}
export interface SignalForgeResearchState {
  status:string; candidate_id:number; card_id?:string; thesis_id?:string;
  best_next_research?:Record<string,unknown>|null; gap_progress?:SignalForgeResearchGapProgress[];
  recent_requests?:SignalForgeResearchRequest[]; request_result?:Record<string,unknown>;
  published_truth_changed?:boolean; truth_boundary?:string; reason?:string;
}


export interface SignalForgeAddressabilityDimension {
  state:string; basis?:string; evidence_refs?:string[]; metrics?:Record<string,unknown>; truth_owner?:string;
}
export interface SignalForgeFounderAddressability {
  engine_version?:string; third_person_opportunity_state?:string; first_person_addressability_state?:string;
  domains?:string[]; trust_burden?:string; learning_distance?:string;
  dimensions?:Record<string,SignalForgeAddressabilityDimension>; blocking_unknowns?:string[]; hard_blocked?:boolean;
  company_profile_version?:string|null; truth_boundary?:string;
}
export interface SignalForgeFastValidation {
  state?:string; revealed_behavior?:string; market_action_candidate?:boolean; falsification_cost_class?:string; truth_boundary?:string;
}
export interface SignalForgeBestNextAction {
  mode?:string; action?:string; reason?:string; authority?:string; dimension?:string; voi?:number;
}
export interface SignalForgeStrategicThesis {
  thesis_id:string; representative_title?:string; representative_problem?:string; strategic_track?:string;
  classification?:string; zip2_readiness?:string; opportunity_class?:string; member_candidate_ids?:number[];
  founder_addressability?:SignalForgeFounderAddressability; fast_validation?:SignalForgeFastValidation;
  best_next_action?:SignalForgeBestNextAction; dimensions?:Record<string,Record<string,unknown>>;
  claim_states?:Record<string,string>; research_plan?:Array<Record<string,unknown>>; portfolio_rank?:number;
}
export interface SignalForgeStrategicPortfolio {
  engine_version?:string; status?:string; refreshed_at?:string; count:number; items:SignalForgeStrategicThesis[];
  strategic_summary?:{strategic_track_counts?:Record<string,number>;fast_validation_counts?:Record<string,number>;founder_addressability_counts?:Record<string,number>;golden_overlap_count?:number;empty_is_valid?:boolean};
  market_calibration?:Record<string,unknown>; authority?:string; read_only?:boolean;
}
export interface SignalForgeResearchWorkspaceItem {
  research_question_id:string; thesis_id?:string; problem_lineage_id?:string; dimension?:string; state?:string;
  fatal_gate?:boolean; voi?:number; source_group?:string; action?:string; attempts?:number; status?:string;
  representative_title?:string; representative_problem?:string; strategic_track?:string; zip2_readiness?:string;
  fast_validation?:SignalForgeFastValidation; founder_addressability?:SignalForgeFounderAddressability; best_next_action?:SignalForgeBestNextAction;
}
export interface SignalForgeResearchWorkspace {
  engine_version?:string; status?:string; refreshed_at?:string; count:number; items:SignalForgeResearchWorkspaceItem[]; truth_boundary?:string; read_only?:boolean;
}
export interface SignalForgeBrainSearchResult {
  object_type:string; object_id:string; title?:string; subtitle?:string; strategic_track?:string; zip2_readiness?:string; classification?:string;
}
export interface SignalForgeBrainSearch { query:string; count:number; items:SignalForgeBrainSearchResult[]; search_scope?:string; read_only?:boolean; }

export interface SignalForgeExecutionRoute {
  engine_version?:string; case_id?:number; candidate_id?:number; route:string; action?:string; priority_tier?:number;
  decision_critical?:boolean; machine_execution_eligible?:boolean; machine_execution_selected?:boolean; machine_execution_deferred_by_capacity?:boolean; current_gate?:string; current_gate_research_status?:string;
  brain_voi?:number; brain_mode?:string|null; reason_codes?:string[]; revisit_triggers?:string[]; truth_boundary?:string;
}
export interface SignalForgeOperatingQueueItem {
  case_id?:number; candidate_id?:number; title?:string; decision_verdict?:string; current_gate?:string; route?:string; action?:string;
  brain_voi?:number; machine_execution_selected?:boolean; machine_execution_deferred_by_capacity?:boolean; reason_codes?:string[]; revisit_triggers?:string[];
}
export interface SignalForgeOperatingQueue {
  engine_version?:string; counts?:Record<string,number>; machine_research?:SignalForgeOperatingQueueItem[]; machine_research_backlog?:SignalForgeOperatingQueueItem[]; market_action?:SignalForgeOperatingQueueItem[];
  founder_discovery?:SignalForgeOperatingQueueItem[]; waiting?:SignalForgeOperatingQueueItem[]; parked?:SignalForgeOperatingQueueItem[]; monitor?:SignalForgeOperatingQueueItem[];
  bounded_machine_case_ids?:number[]; semantics?:Record<string,string>; truth_boundary?:string;
}
export interface SignalForgeMarketActionSuggestion {
  thesis_id:string; representative_title?:string; strategic_track?:string; zip2_readiness?:string; addressability?:string;
  mode?:string; action_type?:string; reason?:string; voi?:number;
  template?:{category?:string;target?:string;success_signal?:string;failure_signal?:string;default_sample?:number;cost_class?:string};
  registered_action_id?:string|null; registration_status?:string; truth_boundary?:string;
}
export interface SignalForgeMarketActionRecord {
  action_id:string; thesis_id:string; status:string; mode?:string; category?:string; action_type?:string; target?:string; sample_target?:number;
  success_criteria?:string; failure_criteria?:string; registered_at?:string; completed_at?:string|null; result?:string|null;
  observations?:Record<string,unknown>|null; result_note?:string|null; pretest_snapshot?:Record<string,unknown>; outcome_quality?:{status?:string;eligible?:boolean;eligible_domains?:string[];reasons?:string[]};
  part6_test_design?:SignalForgeMarketTestDesign|Record<string,unknown>; decision_rule?:SignalForgeMarketTestDecisionRule; inconclusive_criteria?:string|null; max_cost?:number|null; max_cost_currency?:string|null; buyer_outreach_pack?:SignalForgeBuyerOutreachPack|Record<string,unknown>; learning_features?:Record<string,unknown>;
  truth_boundary?:string;
}
export interface SignalForgeStrategicRoutingCoherence {
  status?:string; candidate_actions_total?:number; actionable_candidate_actions?:number; radar_candidates_checked?:number; matched?:number; mismatch_count?:number;
  thesis_only_or_no_radar_row?:number; expected_route_counts?:Record<string,number>; mismatches?:Array<Record<string,unknown>>; thesis_only_items?:Array<Record<string,unknown>>; truth_boundary?:string;
}
export interface SignalForgeOperatingLoop {
  engine_version?:string; published_founder_generated_at?:string; founder_strategy?:{brain_status?:string;brain_refreshed_at?:string;strategic_summary?:Record<string,unknown>;action_queue?:Array<Record<string,unknown>>}; execution_governor?:Record<string,unknown>;
  strategic_routing_coherence?:SignalForgeStrategicRoutingCoherence; operating_queue?:SignalForgeOperatingQueue; market_action_queue?:{count?:number;items?:SignalForgeMarketActionSuggestion[];truth_boundary?:string};
  market_action_registry?:{total?:number;registered?:number;running?:number;completed?:number;rows?:SignalForgeMarketActionRecord[];truth_boundary?:string};
  truth_boundary?:string;
}
export interface SignalForgeMarketActions {
  suggested?:{engine_version?:string;status?:string;count?:number;items?:SignalForgeMarketActionSuggestion[];registered_open?:number;completed?:number;truth_boundary?:string};
  registry?:{engine_version?:string;total?:number;registered?:number;running?:number;completed?:number;calibration_eligible?:number;calibration_ineligible_recorded?:number;rows?:SignalForgeMarketActionRecord[];truth_boundary?:string};
}

export interface SignalForgeMoneyTrailEvidence {
  claim_code?:string; claim_state?:string; stance?:string; source_type?:string; source_title?:string;
  excerpt?:string; source_url?:string|null; source_family_key?:string; authority_class?:string; directness?:string;
  bucket?:string; evidence_grade?:string; amount_mentions?:string[]; matched_terms?:string[];
  paid_cues?:string[]; dissatisfaction_cues?:string[];
}
export interface SignalForgeMoneyTrail {
  engine_version?:string; status?:string; thesis_id?:string; source?:string; title?:string; problem?:string;
  strategic_track?:string; zip2_readiness?:string;
  buyer_segment?:{key?:string;label?:string;evidence_cues?:string[];state?:string};
  claim_states?:Record<string,string>;
  current_spend?:{status?:string;evidence_count?:number;numeric_estimate_created?:boolean;buckets?:Record<string,SignalForgeMoneyTrailEvidence[]>;truth_boundary?:string};
  money_recipients_today?:Array<{recipient?:string;type?:string;basis?:string}>;
  current_solutions?:string[];
  paid_dissatisfaction?:{status?:string;count?:number;items?:SignalForgeMoneyTrailEvidence[];truth_boundary?:string};
  possible_revenue_wedge?:{status?:string;statement?:string;basis?:SignalForgeMoneyTrailEvidence[];truth_boundary?:string};
  revenue_wedge?:{decision?:string;existing_spend?:string;pain?:string;buyer_reality?:string;unresolved_gap?:string;buyer_reachability?:string;mvp_buildability?:string;trust_required?:string;competition_evidence?:string;paid_dissatisfaction_count?:number;current_solution_count?:number;rationale?:string;score?:number|null;truth_boundary?:string};
  cheapest_test?:{action_type?:string;sample_target?:number;instruction?:string;success_signal?:string;failure_signal?:string;cost_class?:string;source?:string};
  founder_playbook?:{target_person?:string;channels?:string[];observed_source_hints?:string[];outreach_message?:string;questions?:string[];offer_rule?:string;sample_target?:number;success_signal?:string;failure_signal?:string;truth_boundary?:string};
  founder_addressability?:SignalForgeFounderAddressability; member_candidate_ids?:number[]; published_evidence_count?:number;
  matched_candidates?:Array<{candidate_id:number;case_id:number;title?:string;match_score?:number}>; message?:string; next_step?:string; truth_boundary?:string;
}
export interface SignalForgeMoneyTrailPortfolio {
  engine_version?:string;status?:string;count:number;counts?:Record<string,number>;items:SignalForgeMoneyTrail[];market_calibration?:Record<string,unknown>;truth_boundary?:string;
}

export interface SignalForgeFounderIdeaTrace {
  source?:string; kind?:string; title?:string; excerpt?:string; url?:string|null; author?:string|null; created_at?:string|null;
  signals?:{pain?:string[];workaround?:string[];paid?:string[];dissatisfaction?:string[]};
  metadata?:Record<string,unknown>; truth_status?:string;
}
export interface SignalForgeFounderIdeaSourceHealth {
  source?:string; status?:string; count?:number; error?:string|null; transport?:Record<string,unknown>;
}
export interface SignalForgeDecisionFrontier {
  question?:string; next_mode?:string; today_action?:string; advance_if?:string; kill_if?:string; do_not_research?:string[]; truth_boundary?:string;
}
export interface SignalForgeFounderIdeaProbe {
  engine_version?:string; status?:string;
  idea?:{title?:string;description?:string;queries?:string[]};
  fast_probe?:{
    status?:string;elapsed_ms?:number;problem_discussions?:number;firsthand_pain?:number;workarounds?:number;existing_solutions?:number;paid_signals?:number;post_purchase_complaints?:number;
    spend_observations?:Array<Record<string,unknown>>;paid_dissatisfaction_observations?:Array<Record<string,unknown>>;source_health?:SignalForgeFounderIdeaSourceHealth[];coverage?:string;top_traces?:SignalForgeFounderIdeaTrace[];truth_boundary?:string;
  };
  published_money_trail?:SignalForgeMoneyTrail;
  decision_frontier?:SignalForgeDecisionFrontier;
  today?:{one_question?:string;next_mode?:string;instruction?:string;advance_if?:string;kill_if?:string};
  market_truth_writes?:number;ai_api_calls?:number;truth_boundary?:string;
}

export interface SignalForgeCounterevidenceCandidate extends SignalForgeFounderIdeaTrace {
  counterevidence_categories?:string[]; falsification_themes?:string[]; truth_status?:string;
}
export interface SignalForgeEvidenceReplayClaim {
  claim_code?:string; state?:string; statement?:string; supporting?:number; contradicting?:number; insufficient?:number; independent_source_families?:number;
  evidence?:Array<{stance?:string;source_type?:string;source_title?:string;source_url?:string|null;source_family_key?:string;excerpt?:string;directness?:string;authority_class?:string;rationale?:string;validated?:boolean}>;
}
export interface SignalForgeEvidenceReplay {
  engine_version?:string; status?:string; thesis_id?:string; title?:string;
  summary?:{validated_evidence_links?:number;supporting?:number;contradicting?:number;insufficient?:number;unknown_claims?:number;claims_with_contradiction?:number};
  claims?:SignalForgeEvidenceReplayClaim[]; search_coverage?:{status?:string;message?:string}; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeFalsificationResult {
  engine_version?:string;status?:string;target?:{thesis_id?:string|null;title?:string;description?:string};
  falsification_queries?:Array<{theme?:string;query?:string}>;
  fresh_counterevidence_search?:{coverage?:string;successful_source_runs?:number;failed_source_runs?:number;candidate_count?:number;category_counts?:Record<string,number>;candidates?:SignalForgeCounterevidenceCandidate[];interpretation?:string;message?:string;source_runs?:Array<{theme?:string;query?:string;source?:string;status?:string;count?:number;error?:string|null;transport?:Record<string,unknown>}>;truth_boundary?:string};
  published_disposition?:{current_disposition?:string;basis?:string;critical_claim_states?:Record<string,string>;conditions?:Record<string,string>;fresh_search_can_trigger_disposition?:boolean;truth_boundary?:string};
  evidence_replay?:SignalForgeEvidenceReplay|null;market_truth_writes?:number;ai_api_calls?:number;truth_boundary?:string;
}

export type SignalForgeFounderDecisionTrack = "CASH" | "BOTH" | "ZIP2" | "PARK";
export type SignalForgeFounderAction = "ACTION_NOW" | "VALIDATE_DISTRIBUTION" | "NARROW_WEDGE" | "INVESTIGATE" | "WATCH" | "PARK_OR_PARTNER" | "PARK";
export interface SignalForgeDecisionTrigger {
  current_track?:SignalForgeFounderDecisionTrack; promote_if?:Array<{to?:string;if?:string}>; demote_if?:Array<{to?:string;if?:string}>;
  kill_if?:string[]; watch_for?:Array<{trigger?:string;for?:string}>; current_facts?:Record<string,string>; truth_boundary?:string;
}
export interface SignalForgeDecisionItem {
  engine_version?:string;thesis_id?:string;title?:string;problem?:string;current_track?:SignalForgeFounderDecisionTrack;canonical_strategic_track?:string;
  classification?:string;zip2_readiness?:string;revenue_wedge_decision?:string;existing_spend?:string;paid_dissatisfaction_count?:number;published_evidence_count?:number;
  founder_fit?:{state?:string;trust_burden?:string;learning_distance?:string;domains?:string[];blocking_unknowns?:string[];dimensions?:Record<string,{state?:string;basis?:string;evidence_refs?:string[]}>;truth_boundary?:string};
  structural_mapper?:{zip2_readiness?:string;opportunity_class?:string;structural_thesis?:Record<string,unknown>;dimensions?:Array<{dimension?:string;state?:string;basis?:string;evidence_refs?:string[];metrics?:Record<string,unknown>;truth_owner?:string}>;open_dimensions?:string[];refuted_dimensions?:string[];truth_boundary?:string};
  wedge_ladder?:{stages?:Array<{stage?:string;state?:string;basis?:string}>;next_blocker?:{stage?:string;state?:string;basis?:string}|null;revenue_wedge_decision?:string;paid_outcome_authority?:string;truth_boundary?:string};
  best_next_action?:Record<string,unknown>;decision_frontier?:unknown;part3_disposition?:{current_disposition?:string;basis?:string;critical_claim_states?:Record<string,string>};hard_kill?:boolean;
  promotion_demotion_watch?:SignalForgeDecisionTrigger;do_not_research?:Array<{topic?:string;reason?:string}>;what_changes_rank?:string[];
  priority_band?:string;rank?:number;founder_rank?:number;rank_explanation?:{band?:string;track?:string;revenue_wedge?:string;existing_spend?:string;founder_fit?:string;paid_dissatisfaction?:number;note?:string};
  market_track?:SignalForgeFounderDecisionTrack; founder_action?:SignalForgeFounderAction;
  founder_actionability?:{market_track?:string;founder_action?:SignalForgeFounderAction;gate_pass?:boolean;blockers?:string[];unknowns?:string[];matrix?:Record<string,string>;reason?:string;truth_boundary?:string};
  validation_ladder?:SignalForgeDecisionItem["wedge_ladder"];
  structural_relationship_mapper?:{nodes?:Array<{type?:string;id?:string|null;text?:unknown;state?:string;trajectory?:unknown;driver?:string;authority?:string;payload?:Record<string,unknown>}>;edges?:Array<{from?:string;to?:string;relation?:string}>;truth_boundary?:string};
  wedge_expansion_ladder?:{current_wedge?:{status?:string;statement?:string;authority?:string};evidence_to_collect?:Array<Record<string,unknown>>;unlock_condition?:string;possible_next_wedges?:Array<{wedge?:string;authority?:string;state?:string}>;next_wedge_status?:string;truth_boundary?:string};
  market_truth_writes?:number;truth_boundary?:string;closure_truth_boundary?:string;
}
export interface SignalForgeResourceAllocation {
  weekly_hours?:number;cash_need?:string;long_term?:string;allocated_hours?:number;unallocated_hours?:number;advisory_only?:boolean;authority?:string;
  allocations?:Array<{bucket?:string;thesis_id?:string;title?:string;hours?:number;why?:string;dependency?:string|null;expected_learning?:unknown;what_changes_this?:string[]}>;truth_boundary?:string;
}
export interface SignalForgeDecisionPortfolio {
  engine_version?:string;status?:string;settings?:{cash_need?:string;long_term?:string};count:number;items:SignalForgeDecisionItem[];top?:SignalForgeDecisionItem|null;
  ranking_method?:string;track_counts?:Record<string,number>;founder_action_counts?:Record<string,number>;resource_allocation?:SignalForgeResourceAllocation;market_calibration?:Record<string,unknown>;authority?:string;market_truth_writes?:number;truth_boundary?:string;
}
export interface SignalForgeDecisionAsk {
  engine_version?:string;status?:string;query?:string;intent?:string;answer?:string;predicates?:string[];composite?:boolean;matches?:SignalForgeDecisionItem[];market_truth_writes?:number;truth_boundary?:string;
}

export interface SignalForgeBenchmarkHypothesis { title:string; description?:string; provenance_type?:string; source_model?:string; source_ref?:string; }
export interface SignalForgeBenchmarkBatchResult { engine_version?:string;status?:string;input_count?:number;deduped_count?:number;synthetic_convergence_counts_as_market_recurrence?:boolean;items?:Array<{hypothesis_id?:string;title?:string;description?:string;contributors?:Array<Record<string,unknown>>;synthetic_contributor_count?:number;independent_market_recurrence_count?:number;truth_status?:string;probe?:Record<string,unknown>|null;possible_lineage_match?:Record<string,unknown>|null;route?:string;market_authority?:string}>;market_truth_writes?:number;truth_boundary?:string; }

export type SignalForgeFounderMemoryEntryType = "HYPOTHESIS" | "QUESTION" | "ASSUMPTION" | "DECISION" | "REJECTED_DIRECTION" | "CONSTRAINT" | "REASON";
export interface SignalForgeFounderMemoryEntry {
  entry_id?:string; subject_key?:string; subject_label?:string; thesis_id?:string|null; entry_type?:SignalForgeFounderMemoryEntryType;
  statement?:string; reason?:string|null; source_ref?:string|null; tags?:string[]; created_at?:string; authority?:string; market_authority?:string;
  market_truth_impact?:string; validation_status?:string; truth_boundary?:string;
}
export interface SignalForgeFounderMemorySubject {
  subject_key:string; subject_label?:string; thesis_id?:string|null; entry_count?:number; last_entry_at?:string|null; latest_decision?:string|null; latest_question?:string|null;
}
export interface SignalForgeFounderMarketClaimState { claim_code?:string; label?:string; state?:string; }
export interface SignalForgeFounderMemoryBrief {
  engine_version?:string; status?:string; subject?:{subject_key?:string;subject_label?:string;thesis_id?:string|null};
  market_truth?:{status?:string;thesis_id?:string|null;representative_title?:string;revision?:unknown;classification?:string;strategic_track?:string;zip2_readiness?:string;claim_states?:Record<string,string>;known?:SignalForgeFounderMarketClaimState[];contradicted?:SignalForgeFounderMarketClaimState[];unknown?:SignalForgeFounderMarketClaimState[];truth_boundary?:string};
  founder_reasoning?:{hypotheses?:SignalForgeFounderMemoryEntry[];assumptions?:SignalForgeFounderMemoryEntry[];questions?:SignalForgeFounderMemoryEntry[];decisions?:SignalForgeFounderMemoryEntry[];rejected_directions?:Array<{statement?:string;reason?:string|null;created_at?:string}>;constraints?:SignalForgeFounderMemoryEntry[];reasons?:SignalForgeFounderMemoryEntry[]};
  current_decision_frontier?:SignalForgeFounderMemoryEntry|null; latest_founder_decision?:SignalForgeFounderMemoryEntry|null; do_not_discuss_again?:Array<{type?:string;statement?:string;reason?:string|null}>; entry_count?:number; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeFounderMemoryDelta {
  engine_version?:string; status?:string; subject_key?:string; baseline?:{checkpoint_id?:string;created_at?:string;note?:string|null;memory_entry_count?:number}|null;
  new_founder_reasoning?:SignalForgeFounderMemoryEntry[]; market_delta?:{changed?:boolean;changed_claims?:Array<{claim_code?:string;label?:string;before?:string;after?:string}>;newly_contradicted?:Array<{claim_code?:string;label?:string;before?:string;after?:string}>;metadata_changes?:Array<{field?:string;before?:unknown;after?:unknown}>;reason?:string};
  new_next_question?:SignalForgeFounderMemoryEntry|null; instruction?:string; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeFounderMemoryLedger { engine_version?:string;status?:string;count:number;items:SignalForgeFounderMemoryEntry[];append_only?:boolean;market_truth_writes?:number;truth_boundary?:string; }
export interface SignalForgeFounderMemorySubjects { engine_version?:string;count:number;items:SignalForgeFounderMemorySubject[];truth_boundary?:string; }

export interface SignalForgeDecisionArtifactEntry {
  entry_type:SignalForgeFounderMemoryEntryType; statement:string; reason?:string|null; tags?:string[];
}
export interface SignalForgeDecisionArtifact {
  artifact_id:string; status?:string; subject_key?:string; subject_label?:string; thesis_id?:string|null; discussion_summary?:string|null;
  entries?:SignalForgeDecisionArtifactEntry[]; prepared_at?:string; confirmed_at?:string|null; rejected_at?:string|null; rejection_reason?:string|null;
  founder_memory_entry_ids?:string[]; authority?:string; market_authority?:string; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeDecisionArtifactList {
  engine_version?:string; status?:string; count:number; items:SignalForgeDecisionArtifact[]; append_only?:boolean; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeDiscussionPacket {
  engine_version?:string; status?:string; thesis_id?:string;
  published_market_truth?:Record<string,unknown>; money_trail?:SignalForgeMoneyTrail; evidence_replay?:SignalForgeEvidenceReplay;
  decision_projection?:SignalForgeDecisionItem; founder_discussion_brief?:SignalForgeFounderMemoryBrief|Record<string,unknown>; since_last_discussion?:SignalForgeFounderMemoryDelta|Record<string,unknown>;
  instructions_for_chatgpt?:string[]; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeChatGPTIntegrationStatus {
  engine_version?:string; status?:string; engineering_acceptance?:string; live_chatgpt_acceptance?:string; mcp_adapter?:string; mcp_python_dependency?:string; chatgpt_connection_requirement?:string;
  supported_deployment_mode?:string; public_remote_endpoint?:string; tool_permission_contract?:Record<string,string>;
  writeback_policy?:string; artifact_store?:Record<string,unknown>; market_truth_writes?:number; truth_boundary?:string;
}


export interface SignalForgeMarketTestDecisionRule { metric?:string; operator?:string; success_min?:number; failure_rule?:string; inconclusive_rule?:string; sample_target?:number; authority?:string; }
export interface SignalForgeBuyerOutreachPack { who?:string; where?:string[]; what_to_ask?:string[]; what_not_to_say?:string[]; evidence_to_capture?:string[]; offer_or_wedge?:string; truth_boundary?:string; }
export interface SignalForgeMarketTestDesign {
  engine_version?:string; thesis_id?:string; title?:string; market_track?:string; founder_action?:string; hypothesis?:string; target?:string;
  test?:{action_type?:string;category?:string;instruction?:string;offer?:string|null};
  success?:{criterion?:string;decision_rule?:SignalForgeMarketTestDecisionRule}; failure?:{criterion?:string;decision_rule?:string}; inconclusive?:{criterion?:string;decision_rule?:string};
  max_sample?:number; max_cost?:number|null; max_cost_currency?:string|null; cost_boundary?:string; buyer_outreach_pack?:SignalForgeBuyerOutreachPack;
  atomic_promotion_hint?:{event?:string|null;claims?:string[];requires_claim_specific_preregistration_before_outcome?:boolean}; learning_features?:Record<string,unknown>; frozen_on_preregistration?:boolean; market_truth_writes?:number; truth_boundary?:string;
}
export interface SignalForgeMarketExecutionDashboard {
  engine_version?:string; status?:string; candidates?:Array<{thesis_id?:string;title?:string;market_track?:string;founder_action?:string;decision_frontier?:unknown;hard_kill?:boolean}>;
  registry?:{total?:number;registered?:number;running?:number;completed?:number;rows?:SignalForgeMarketActionRecord[]}; claim_validation?:SignalForgeValidationExperiments;
  learning_calibration?:SignalForgeMarketLearningCalibration; market_calibration_state?:string; market_truth_writes_on_read?:number; truth_boundary?:string;
}
export interface SignalForgeMarketLearningCalibration { engine_version?:string; status?:string; eligible_outcomes?:number; distinct_entities?:number; minimum_policy?:Record<string,unknown>; features?:Record<string,Array<Record<string,unknown>>>; actionable_adjustments?:Array<Record<string,unknown>>; general_predictive_accuracy?:string; market_truth_writes?:number; truth_boundary?:string; }
export interface SignalForgePromotionOption { experiment_id?:string;case_id?:number;candidate_id?:number;claim_code?:string;registered_event?:string;registered_at?:string;action_result?:string;suggested_record_event?:string;actor_label?:string|null;amount?:number|null;currency?:string|null;explicit_founder_promotion_required?:boolean; }
export interface SignalForgePromotionOptions { action_id?:string;status?:string;items?:SignalForgePromotionOption[];market_truth_writes?:number;truth_boundary?:string; }

export interface SignalForgeValidationExperiment {
  experiment_id:string; case_id:number; title?:string; claim_code:string; event:string; status:string; created_at?:string; completed_at?:string|null;
  result?:string|null; result_note?:string|null; actor_label?:string|null; amount?:number|null; currency?:string|null; plan?:Record<string,unknown>;
  pretest_snapshot?:Record<string,unknown>; note?:string|null;
}
export interface SignalForgeValidationExperiments {
  engine_version?:string; total:number; pending:number; completed:number; claim_event_map?:Record<string,string>; rows:SignalForgeValidationExperiment[]; truth_boundary?:string;
}
export interface SignalForgeClaimValidationReady {
  case_id:number; candidate_id?:number|null; title?:string; claim_states?:Record<string,string>; prepared_claims?:string[]; events?:Record<string,string>;
}

export interface SignalForgeSourceHealth {
  contract?:string; groups_attempted?:string[]; groups_refreshed?:string[]; groups_passed?:string[]; groups_failed?:string[];
  scraper_status_counts?:Record<string,number>; same_round_source_materialization?:boolean;
  structured_buyer?:{effective_refresh_passed?:boolean;runs?:number;fresh_runs?:number;latest_named?:number};
}
export interface SignalForgeRuntime {
  status:string; running:boolean; last_success_at:string|null; data_age_hours:number|null; stale_after_hours:number; fresh:boolean;
  next_due_at:string|null; last_error:string|null;
  last_attempt_started_at?:string|null; last_attempt_finished_at?:string|null; last_attempt_status?:string|null; last_attempt_error?:string|null;
  last_attempt_cycle?:Record<string,unknown>;
  lease?:{pid?:number;started_at?:string;reason?:string}|null;
  last_cycle?:{changes?:number;llm_calls?:number;llm_cost_twd?:number;source_health?:SignalForgeSourceHealth;recurrence?:{supported?:number;coverage_gap?:number};
    production_admission?:Record<string,unknown>;execution_governor?:Record<string,unknown>;strategic_routing_coherence?:SignalForgeStrategicRoutingCoherence;operating_queue?:SignalForgeOperatingQueue;
    phase_seconds?:Record<string,number>;phase_value?:Record<string,unknown>;warm_cache_readiness?:Record<string,unknown>;discovery_portfolio?:Record<string,unknown>};
}
export interface SignalForgeDaily {
  engine_version:string; generated_at:string; verdict_counts:Record<string,number>; build_locked:boolean;
  validation_boundary:{founder_action_now:number;prebuilt_waiting:number;machine_first:number};
  calibration:{status?:string;positive_precision?:number|null;warning?:string}|null;
  research_portfolio?:{ordered_groups?:string[];query_jobs?:number;ranked_groups?:Array<Record<string,unknown>>;top_query_jobs?:Array<Record<string,unknown>>};
  validation_cohort?:{treatment_candidates:number;control_candidates:number;matched_pairs:number;clean_matched_pairs?:number;contaminated_pairs?:number;selection_snapshot_frozen?:boolean;predictive_accuracy_claimed:boolean};
  quality:{status:string;critical_count:number;warning_count:number}; cards:SignalForgeDailyCard[];
  solo_founder_gate?:{ready:number;watch:number;research_themes_parked:number;definition:string;empty_is_valid:boolean};
  solo_watch_preview?:Array<{case_id?:number;candidate_id?:number;title?:string;solo_transition?:Record<string,unknown>}>;
  founder_strategy?:{authority?:string;strategic_summary?:Record<string,unknown>;brain_status?:string;brain_refreshed_at?:string;items?:SignalForgeStrategicThesis[];candidate_surface_role?:string};
  runtime?:SignalForgeRuntime;
  execution_governor?:Record<string,unknown>;
  strategic_routing_coherence?:SignalForgeStrategicRoutingCoherence;
  operating_queue?:SignalForgeOperatingQueue;
  market_action_queue?:{count?:number;items?:SignalForgeMarketActionSuggestion[];truth_boundary?:string};
  market_action_registry?:{total?:number;registered?:number;running?:number;completed?:number;calibration_eligible?:number;calibration_ineligible_recorded?:number;truth_boundary?:string};
  claim_validation_ready?:SignalForgeClaimValidationReady[];
  claim_validation_registry?:{engine_version?:string;total?:number;pending?:number;completed?:number;truth_boundary?:string};
  spending?:SpendingStatus;
}
// ── Cross-Source Signal Types ─────────────────────────────────

export interface ResearchPipelineItem {
  id: number;
  paper_title: string;
  arxiv_id: string | null;
  published_at: string | null;
  current_stage: string | null;
  pipeline_velocity: string | null;
  github_repos: number | null;
  github_first_impl_at: string | null;
  hf_model_ids: string[] | null;
  hf_total_downloads: number | null;
  hf_first_upload_at: string | null;
  community_mention_count: number | null;
  community_sentiment: number | null;
  community_first_mention_at: string | null;
  ph_launches: number | null;
  ph_first_launch_at: string | null;
  so_question_count: number | null;
  days_paper_to_code: number | null;
  days_code_to_adoption: number | null;
  days_total_pipeline: number | null;
  updated_at: string | null;
}

export interface TractionScoreItem {
  id: number;
  entity_name: string;
  entity_type: string | null;
  traction_score: number | null;
  traction_label: string | null;
  ph_votes: number | null;
  gh_stars: number | null;
  gh_star_velocity: number | null;
  gh_non_founder_contributors: number | null;
  pypi_monthly_downloads: number | null;
  npm_monthly_downloads: number | null;
  organic_mentions: number | null;
  self_promo_mentions: number | null;
  job_listings: number | null;
  recommendation_rate: number | null;
  score_breakdown: Record<string, unknown> | null;
  red_flags: string[] | null;
  reasoning: string | null;
  calculated_at: string | null;
}

export interface TechnologyLifecycleItem {
  id: number;
  technology_name: string;
  current_stage: string | null;
  stage_evidence: Record<string, unknown> | null;
  arxiv_paper_count: number | null;
  github_repo_count: number | null;
  hf_model_count: number | null;
  so_question_count: number | null;
  so_question_type: string | null;
  job_listing_count: number | null;
  job_listing_type: string | null;
  community_mention_count: number | null;
  community_sentiment_trajectory: Record<string, unknown> | null;
  pypi_download_trend: Record<string, unknown> | null;
  calculated_at: string | null;
}

export interface MarketGapItem {
  id: number;
  problem_title: string;
  pain_score: number | null;
  complaint_count: number | null;
  existing_products: number | null;
  existing_product_names: string[] | null;
  total_funding_in_space: number | null;
  funded_startups: number | null;
  job_postings_related: number | null;
  yc_batch_presence: number | null;
  gap_signal: string | null;
  opportunity_score: number | null;
  reasoning: string | null;
  calculated_at: string | null;
}

export interface CompetitiveThreatItem {
  id: number;
  target_product: string;
  competitor: string;
  migrations_away: number | null;
  competitor_gh_velocity: number | null;
  competitor_hiring: number | null;
  competitor_sentiment: number | null;
  competitor_sentiment_trend: string | null;
  opinion_leaders_flipped: number | null;
  threat_score: number | null;
  threat_summary: string | null;
  calculated_at: string | null;
}

export interface PlatformDivergenceItem {
  id: number;
  topic_name: string;
  reddit_sentiment: number | null;
  hn_sentiment: number | null;
  youtube_sentiment: number | null;
  ph_sentiment: number | null;
  max_divergence: number | null;
  divergence_direction: string | null;
  prediction: string | null;
  status: string | null;
  calculated_at: string | null;
}

export interface SmartMoneyItem {
  id: number;
  sector: string;
  yc_companies_last_batch: number | null;
  yc_trend: string | null;
  yc_percentage_of_batch: number | null;
  vc_funding_articles: number | null;
  vc_signal: string | null;
  builder_repos: number | null;
  builder_stars: number | null;
  community_posts_30d: number | null;
  classification: string | null;
  reasoning: string | null;
  calculated_at: string | null;
}

export interface TalentFlowItem {
  id: number;
  skill: string;
  category: string | null;
  demand_score: number | null;
  supply_score: number | null;
  gap: number | null;
  salary_pressure: string | null;
  trend: string | null;
  job_listings_30d: number | null;
  so_questions_30d: number | null;
  reasoning: string | null;
  prediction: string | null;
  calculated_at: string | null;
}

export interface NarrativeShiftItem {
  id: number;
  topic_name: string;
  topic_id: number | null;
  shift_type: string | null;
  shift_velocity: string | null;
  older_frame: string | null;
  recent_frame: string | null;
  media_alignment: string | null;
  prediction: string | null;
  confidence: string | null;
  narrative_timeline: unknown[] | null;
  calculated_at: string | null;
}

export interface SignalSummary {
  total_signals: Record<string, number>;
  top_opportunities: { problem_title: string; opportunity_score: number | null; gap_signal: string | null; complaint_count: number | null }[];
  top_threats: { target_product: string; competitor: string; threat_score: number | null; migrations_away: number | null }[];
  top_skill_gaps: { skill: string; gap: number | null; salary_pressure: string | null; trend: string | null; demand_score: number | null; supply_score: number | null }[];
  smart_money_early: { sector: string; yc_companies_last_batch: number | null; yc_trend: string | null; vc_signal: string | null; builder_repos: number | null }[];
  narrative_shifts: { topic_name: string; shift_type: string | null; shift_velocity: string | null; older_frame: string | null; recent_frame: string | null }[];
  insights: InsightCard[];
}

export interface InsightCard {
  category: string | null;
  color: string | null;
  insight: string | null;
  signals_used: string[] | null;
  confidence: string | null;
  recommended_action: string | null;
}

export interface AgentOutput {
  agent: string;
  data: unknown;
  last_run: string | null;
  duration_seconds: number | null;
  tokens_used: number | null;
}

export interface CrossSourceHighlight {
  type: string;
  title: string;
  description: string | null;
  confidence: string | null;
  signals_used: string[] | null;
  color: string | null;
}

// ── Agent Management Types ────────────────────────────────────

export interface AgentRun {
  id: number;
  agent_name: string;
  status: string;
  duration_seconds: number | null;
  tokens_used: number | null;
  cost_usd: number | null;
  records_produced: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentRunDetail extends AgentRun {
  output: string | null;
  output_json: unknown;
  error_message: string | null;
}

export interface AgentStatus {
  agent_name: string;
  model: string | null;
  schedule_hours: number | null;
  last_run: AgentRun | null;
  total_runs: number;
  success_rate: number | null;
}

export interface AgentCost {
  agent_name: string;
  total_runs: number;
  total_tokens: number | null;
  total_cost_usd: number | null;
  avg_duration_seconds: number | null;
}

// ── Source Data Types ─────────────────────────────────────────

export interface GithubRepo {
  id: number;
  full_name: string;
  description: string | null;
  language: string | null;
  stars: number | null;
  forks: number | null;
  star_velocity_7d: number | null;
  topics: string[] | null;
  pushed_at: string | null;
  scraped_at: string | null;
}

export interface HFModel {
  id: number;
  model_id: string;
  author: string | null;
  pipeline_tag: string | null;
  library_name: string | null;
  downloads: number | null;
  likes: number | null;
  trending_score: number | null;
  tags: string[] | null;
  scraped_at: string | null;
}

export interface PackageDownloadTrend {
  package_name: string;
  registry: string | null;
  total_downloads_30d: number;
  latest_daily: number | null;
  trend: string | null;
}

export interface YCCompany {
  id: number;
  name: string;
  slug: string | null;
  batch: string | null;
  status: string | null;
  one_liner: string | null;
  industry: string[] | null;
  website: string | null;
  team_size: number | null;
  scraped_at: string | null;
}

export interface SOQuestion {
  id: number;
  question_id: number;
  title: string;
  tags: string[] | null;
  view_count: number | null;
  answer_count: number | null;
  score: number | null;
  is_answered: boolean | null;
  creation_date: string | null;
  scraped_at: string | null;
}

export interface PHLaunch {
  id: number;
  name: string;
  tagline: string | null;
  description: string | null;
  url: string | null;
  votes_count: number | null;
  comments_count: number | null;
  topics: string[] | null;
  thumbnail_url: string | null;
  featured_at: string | null;
  scraped_at: string | null;
}

// ── Product Review Types ─────────────────────────────────────

export interface ProductReviewItem {
  id: number;
  product_id: number;
  product_name: string;
  overall_sentiment: string | null;
  satisfaction_score: number | null;
  pros: string[] | null;
  cons: string[] | null;
  common_use_cases: string[] | null;
  feature_requests: string[] | null;
  churn_reasons: string[] | null;
  competitor_comparisons: { competitor: string; context: string }[] | null;
  post_count: number | null;
  source_subreddits: string[] | null;
  calculated_at: string | null;
  updated_at: string | null;
}

export interface ProductReviewSummary {
  total_reviews: number;
  sentiment_distribution: Record<string, number>;
  avg_satisfaction: number | null;
  top_rated: { product: string; score: number }[];
  top_feature_requests: { request: string; count: number }[];
  top_churn_reasons: { reason: string; count: number }[];
}

// ── Gig Board Types ─────────────────────────────────────────

export interface GigPostItem {
  id: number;
  post_id: number | null;
  project_type: string | null;
  need_description: string | null;
  need_category: string | null;
  budget_text: string | null;
  budget_min_usd: number | null;
  budget_max_usd: number | null;
  tech_stack: string[] | null;
  experience_level: string | null;
  remote_policy: string | null;
  project_duration: string | null;
  industry: string | null;
  contact_method: string | null;
  poster_username: string | null;
  source_url: string | null;
  source_subreddit: string | null;
  posted_at: string | null;
  extracted_at: string | null;
}

export interface GigSummary {
  total_gigs: number;
  by_project_type: Record<string, number>;
  by_need_category: Record<string, number>;
  budget: { avg_min: number | null; avg_max: number | null; min: number | null; max: number | null };
  top_tech_stacks: { tech: string; count: number }[];
  by_remote_policy: Record<string, number>;
}

export interface GigTrends {
  weekly_trend: { week: string; count: number }[];
}

// ── Custom Market Research Types ─────────────────────────────

export interface ResearchProject {
  id: number;
  name: string;
  description: string | null;
  initial_terms: string[] | null;
  expanded_keywords: string[] | null;
  status: string;
  post_count: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface ResearchProjectCreate {
  name: string;
  description?: string;
  initial_terms: string[];
}

export interface ResearchInsights {
  id: number;
  project_id: number;
  discussion_summary: string | null;
  overall_sentiment: string | null;
  sentiment_breakdown: Record<string, number> | null;
  products_mentioned: { name: string; pros: string[]; cons: string[]; mention_count: number }[] | null;
  feature_requests: { description: string; frequency: string; source_count: number }[] | null;
  unmet_needs: { description: string; intensity: string; evidence: string }[] | null;
  key_themes: { theme: string; post_count: number; sentiment: string }[] | null;
  calculated_at: string | null;
}

export interface ResearchContact {
  id: number;
  project_id: number;
  user_id: number | null;
  username: string;
  platform: string;
  post_count: number;
  avg_sentiment: number | null;
  sentiment_leaning: string | null;
  topics_discussed: string[] | null;
  sample_post_ids: number[] | null;
  profile_url: string | null;
}

// API functions — unwrap wrappers to keep hooks simple
export const api = {
  // Dashboard
  overview: () => fetchJSON<Overview>("/dashboard/overview"),
  pulse: (params?: Record<string, string>) =>
    fetchJSON<PulseResponse>(`/dashboard/pulse?${new URLSearchParams(params)}`).then(r => r.topics),
  debates: () =>
    fetchJSON<DebateResponse>("/dashboard/debates").then(r => r.debates),
  leaders: (params?: Record<string, string>) =>
    fetchJSON<Leader[]>(`/dashboard/leaders?${new URLSearchParams(params)}`),
  research: () =>
    fetchJSON<ResearchResponse>("/dashboard/research").then(r => r.papers),
  funding: () =>
    fetchJSON<FundingResponse>("/dashboard/funding").then(r => r.events),
  jobs: () => fetchJSON<JobTrend>("/dashboard/jobs"),
  newsImpact: () => fetchJSON<NewsImpact[]>("/dashboard/news-impact"),
  geo: () =>
    fetchJSON<GeoResponse>("/dashboard/geo").then(r => r.locations),

  // Topics
  topics: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<Topic>>(`/topics?${new URLSearchParams(params)}`),
  topic: (id: number) => fetchJSON<TopicDetail>(`/topics/${id}`),
  topicTimeline: (id: number) => fetchJSON<TopicTimeline>(`/topics/${id}/timeline`),
  topicPosts: (id: number, params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<PostItem>>(`/topics/${id}/posts?${new URLSearchParams(params)}`),

  // Personas
  personas: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<Persona>>(`/personas?${new URLSearchParams(params)}`),
  persona: (id: number) => fetchJSON<PersonaDetail>(`/personas/${id}`),
  personaPosts: (id: number, params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<PostItem>>(`/personas/${id}/posts?${new URLSearchParams(params)}`),
  personaGraph: (id: number) => fetchJSON<GraphEdge[]>(`/personas/${id}/graph`),

  // News
  news: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<NewsEvent>>(`/news?${new URLSearchParams(params)}`),
  newsItem: (id: number) => fetchJSON<NewsEvent & { related_posts: PostItem[] }>(`/news/${id}`),

  // Search
  search: (q: string) => fetchJSON<SearchResults>(`/search?q=${encodeURIComponent(q)}`),

  // Intelligence
  products: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<Product>>(`/intelligence/products?${new URLSearchParams(params)}`),
  migrations: () =>
    fetchJSON<MigrationAggregate[]>("/intelligence/migrations"),
  unmetNeeds: () =>
    fetchJSON<PainPoint[]>("/intelligence/unmet-needs"),
  jobAnalysis: () =>
    fetchJSON<JobAnalysis>("/intelligence/job-analysis"),

  // Job Intelligence (LLM-extracted)
  jobIntelSummary: () =>
    fetchJSON<JobIntelSummary>("/job-intelligence/summary"),
  jobIntelTechStack: (params?: Record<string, string>) =>
    fetchJSON<{ filter_role: string | null; technologies: TechStackItem[] }>(`/job-intelligence/tech-stack?${new URLSearchParams(params)}`),
  jobIntelSalary: (params?: Record<string, string>) =>
    fetchJSON<{ filter_country: string | null; salary_bands: SalaryBand[] }>(`/job-intelligence/salary-insights?${new URLSearchParams(params)}`),
  jobIntelHiring: (params?: Record<string, string>) =>
    fetchJSON<{ companies: HiringVelocityCompany[] }>(`/job-intelligence/hiring-velocity?${new URLSearchParams(params)}`),
  jobIntelGeo: () =>
    fetchJSON<JobGeoData>("/job-intelligence/geographic"),
  jobIntelAI: () =>
    fetchJSON<AILandscape>("/job-intelligence/ai-landscape"),
  jobIntelStages: () =>
    fetchJSON<{ stages: CompanyStage[] }>("/job-intelligence/company-stages"),
  jobIntelBenefits: () =>
    fetchJSON<BenefitsCulture>("/job-intelligence/benefits-culture"),
  jobIntelSkills: (params?: Record<string, string>) =>
    fetchJSON<{ filter_role: string | null; skills: SkillDemand[] }>(`/job-intelligence/skills-demand?${new URLSearchParams(params)}`),

  // Dashboard Intelligence
  hypeIndex: (params?: Record<string, string>) =>
    fetchJSON<HypeIndexItem[]>(`/dashboard/hype-index?${new URLSearchParams(params)}`),
  painPoints: (params?: Record<string, string>) =>
    fetchJSON<PainPoint[]>(`/dashboard/pain-points?${new URLSearchParams(params)}`),
  leaderShifts: () =>
    fetchJSON<LeaderShift[]>("/dashboard/leader-shifts"),
  fundingRounds: (params?: Record<string, string>) =>
    fetchJSON<FundingRound[]>(`/dashboard/funding-rounds?${new URLSearchParams(params)}`),

  // Topic platform tones
  topicPlatformTones: (id: number) =>
    fetchJSON<PlatformTone[]>(`/topics/${id}/platform-tones`),

  // Health
  health: () => fetchJSON<{ status: string }>("/health"),
  spending: () => fetchJSON<SpendingStatus>("/system/spending"),
  stats: () => fetchJSON<Record<string, number>>("/stats"),
  signalforgeDaily: () => fetchJSON<SignalForgeDaily>("/signalforge/daily"),
  signalforgeOpportunity: (id:number) => fetchJSON<SignalForgeOpportunityDetail>(`/signalforge/opportunity/${id}`),
  signalforgeResearchState: (id:number) => fetchJSON<SignalForgeResearchState>(`/signalforge/opportunity/${id}/research-state`),
  signalforgeResearchMore: (id:number) => fetchJSON<SignalForgeResearchState>(`/signalforge/opportunity/${id}/research-more`, {method:"POST"}),
  signalforgeStatus: () => fetchJSON<Record<string, unknown>>("/signalforge/status"),
  signalforgeBrainStrategicPortfolio: () => fetchJSON<SignalForgeStrategicPortfolio>("/signalforge/brain-v2/strategic-portfolio"),
  signalforgeBrainThesis: (id:string) => fetchJSON<SignalForgeStrategicThesis>(`/signalforge/brain-v2/thesis/${encodeURIComponent(id)}`),
  signalforgeBrainResearchWorkspace: () => fetchJSON<SignalForgeResearchWorkspace>("/signalforge/brain-v2/research-workspace"),
  signalforgeBrainSearch: (q:string) => fetchJSON<SignalForgeBrainSearch>(`/signalforge/brain-v2/search?q=${encodeURIComponent(q)}`),
  signalforgeBrainStatus: () => fetchJSON<Record<string,unknown>>("/signalforge/brain-v2/status"),
  signalforgeFounderProfile: () => fetchJSON<Record<string,unknown>>("/signalforge/brain-v2/founder-profile"),
  signalforgeOperatingQueue: () => fetchJSON<SignalForgeOperatingLoop>("/signalforge/operating-queue"),
  signalforgeMarketActions: () => fetchJSON<SignalForgeMarketActions>("/signalforge/market-actions"),
  signalforgeMarketExecution: (limit=30) => fetchJSON<SignalForgeMarketExecutionDashboard>(`/signalforge/market-execution?limit=${encodeURIComponent(String(limit))}`),
  designSignalForgeMarketTest: (payload:{thesis_id:string;max_sample?:number;max_cost?:number;cost_currency?:string}) => fetchJSON<SignalForgeMarketTestDesign>("/signalforge/market-execution/design", {method:"POST",body:JSON.stringify(payload)}),
  preregisterSignalForgeMarketTest: (payload:{thesis_id:string;max_sample?:number;max_cost?:number;cost_currency?:string;decision_rule?:SignalForgeMarketTestDecisionRule;note?:string}) => fetchJSON<Record<string,unknown>>("/signalforge/market-execution/preregister", {method:"POST",body:JSON.stringify(payload)}),
  signalforgeClaimPreregistrationOptions: (actionId:string) => fetchJSON<Record<string,unknown>>(`/signalforge/market-execution/actions/${encodeURIComponent(actionId)}/claim-preregistration-options`),
  preregisterSignalForgeClaimForAction: (actionId:string,payload:{case_id:number;claim_code:string;note?:string}) => fetchJSON<Record<string,unknown>>(`/signalforge/market-execution/actions/${encodeURIComponent(actionId)}/claim-preregister`, {method:"POST",body:JSON.stringify(payload)}),
  captureSignalForgeMarketOutcome: (actionId:string,payload:{outcome_counts:Record<string,number>;actor_labels:string[];evidence_refs:string[];observation_records?:Array<{observation_id?:string;actor_label:string;evidence_ref:string;observed_behavior?:string;decision_relevant_finding?:string;signals?:Record<string,unknown>}>;observed_behavior?:string;decision_relevant_findings?:string;reason_counts?:Record<string,number>;amount?:number;currency?:string;actual_cost?:number;actual_cost_currency?:string;note?:string}) => fetchJSON<Record<string,unknown>>(`/signalforge/market-execution/actions/${encodeURIComponent(actionId)}/capture`, {method:"POST",body:JSON.stringify(payload)}),
  signalforgePromotionOptions: (actionId:string) => fetchJSON<SignalForgePromotionOptions>(`/signalforge/market-execution/actions/${encodeURIComponent(actionId)}/promotion-options`),
  promoteSignalForgeMarketOutcome: (actionId:string,payload:{experiment_id:string;note?:string}) => fetchJSON<Record<string,unknown>>(`/signalforge/market-execution/actions/${encodeURIComponent(actionId)}/promote`, {method:"POST",body:JSON.stringify(payload)}),
  signalforgeMarketLearningCalibration: () => fetchJSON<{part6_signal_calibration?:SignalForgeMarketLearningCalibration;existing_domain_calibration?:Record<string,unknown>;general_predictive_accuracy?:string;truth_boundary?:string}>("/signalforge/market-execution/calibration"),
  signalforgeMoneyTrails: () => fetchJSON<SignalForgeMoneyTrailPortfolio>("/signalforge/money-trails"),
  signalforgeMoneyTrail: (id:string) => fetchJSON<SignalForgeMoneyTrail>(`/signalforge/money-trails/${encodeURIComponent(id)}`),
  probeSignalForgeMoneyTrail: (payload:{title:string;description?:string}) => fetchJSON<SignalForgeMoneyTrail>("/signalforge/money-trails/probe", {method:"POST",body:JSON.stringify(payload)}),
  probeSignalForgeFounderIdea: (payload:{title:string;description?:string}) => fetchJSON<SignalForgeFounderIdeaProbe>("/signalforge/founder-idea/probe", {method:"POST",body:JSON.stringify(payload)}),
  falsifySignalForge: (payload:{title:string;description?:string;thesis_id?:string}) => fetchJSON<SignalForgeFalsificationResult>("/signalforge/trust/falsify", {method:"POST",body:JSON.stringify(payload)}),
  signalforgeEvidenceReplay: (thesisId:string) => fetchJSON<SignalForgeEvidenceReplay>(`/signalforge/trust/evidence-replay/${encodeURIComponent(thesisId)}`),
  signalforgeDecisionPortfolio: (params?:{limit?:number;weekly_hours?:number;cash_need?:string;long_term?:string}) => { const p=new URLSearchParams(); if(params?.limit) p.set("limit",String(params.limit)); if(params?.weekly_hours) p.set("weekly_hours",String(params.weekly_hours)); if(params?.cash_need) p.set("cash_need",params.cash_need); if(params?.long_term) p.set("long_term",params.long_term); return fetchJSON<SignalForgeDecisionPortfolio>(`/signalforge/decision/portfolio${p.toString()?`?${p.toString()}`:""}`); },
  compareSignalForgeDecisions: (payload:{thesis_ids:string[];weekly_hours?:number;cash_need?:string;long_term?:string}) => fetchJSON<SignalForgeDecisionPortfolio>("/signalforge/decision/compare", {method:"POST",body:JSON.stringify(payload)}),
  askSignalForgeDecision: (payload:{q:string;weekly_hours?:number;cash_need?:string;long_term?:string}) => fetchJSON<SignalForgeDecisionAsk>("/signalforge/decision/ask", {method:"POST",body:JSON.stringify(payload)}),
  signalforgeBenchmarkBatch: (payload:{hypotheses:SignalForgeBenchmarkHypothesis[];run_probe?:boolean}) => fetchJSON<SignalForgeBenchmarkBatchResult>("/signalforge/decision/benchmark-batch", {method:"POST",body:JSON.stringify(payload)}),
  signalforgeDecisionWatch: () => fetchJSON<{engine_version?:string;status?:string;count?:number;items?:Array<{thesis_id?:string;title?:string;current_track?:SignalForgeFounderDecisionTrack;promotion_demotion_watch?:SignalForgeDecisionTrigger}>;truth_boundary?:string}>("/signalforge/decision/watch"),
  signalforgeChatGPTStatus: () => fetchJSON<SignalForgeChatGPTIntegrationStatus>("/signalforge/chatgpt/status"),
  signalforgeDiscussionPacket: (thesisId:string) => fetchJSON<SignalForgeDiscussionPacket>(`/signalforge/chatgpt/discussion-packet/${encodeURIComponent(thesisId)}`),
  signalforgeDecisionArtifacts: (status?:string) => fetchJSON<SignalForgeDecisionArtifactList>(`/signalforge/chatgpt/decision-artifacts${status?`?status=${encodeURIComponent(status)}`:""}`),
  prepareSignalForgeDecisionArtifact: (payload:{subject_key:string;subject_label?:string;thesis_id?:string;discussion_summary?:string;entries:SignalForgeDecisionArtifactEntry[];source?:string}) => fetchJSON<{status?:string;artifact?:SignalForgeDecisionArtifact;market_truth_writes?:number;truth_boundary?:string}>("/signalforge/chatgpt/decision-artifacts", {method:"POST",body:JSON.stringify(payload)}),
  confirmSignalForgeDecisionArtifact: (artifactId:string) => fetchJSON<{status?:string;artifact?:SignalForgeDecisionArtifact;market_truth_writes?:number;truth_boundary?:string}>(`/signalforge/chatgpt/decision-artifacts/${encodeURIComponent(artifactId)}/confirm`, {method:"POST",body:JSON.stringify({founder_confirmed:true})}),
  rejectSignalForgeDecisionArtifact: (artifactId:string,reason?:string) => fetchJSON<{status?:string;artifact?:SignalForgeDecisionArtifact;market_truth_writes?:number;truth_boundary?:string}>(`/signalforge/chatgpt/decision-artifacts/${encodeURIComponent(artifactId)}/reject`, {method:"POST",body:JSON.stringify({reason})}),
  signalforgeFounderMemorySubjects: () => fetchJSON<SignalForgeFounderMemorySubjects>("/signalforge/founder-memory/subjects"),
  signalforgeFounderMemory: (subjectKey?:string, thesisId?:string) => { const p=new URLSearchParams(); if(subjectKey) p.set("subject_key",subjectKey); if(thesisId) p.set("thesis_id",thesisId); return fetchJSON<SignalForgeFounderMemoryLedger>(`/signalforge/founder-memory${p.toString()?`?${p.toString()}`:""}`); },
  signalforgeFounderMemoryBrief: (subjectKey:string, thesisId?:string) => { const p=new URLSearchParams({subject_key:subjectKey}); if(thesisId) p.set("thesis_id",thesisId); return fetchJSON<SignalForgeFounderMemoryBrief>(`/signalforge/founder-memory/brief?${p.toString()}`); },
  signalforgeFounderMemoryDelta: (subjectKey:string, thesisId?:string) => { const p=new URLSearchParams({subject_key:subjectKey}); if(thesisId) p.set("thesis_id",thesisId); return fetchJSON<SignalForgeFounderMemoryDelta>(`/signalforge/founder-memory/delta?${p.toString()}`); },
  recordSignalForgeFounderMemory: (payload:{subject_key:string;subject_label?:string;thesis_id?:string;entry_type:SignalForgeFounderMemoryEntryType;statement:string;reason?:string;source_ref?:string;tags?:string[]}) => fetchJSON<{status?:string;entry?:SignalForgeFounderMemoryEntry;market_truth_writes?:number;truth_boundary?:string}>("/signalforge/founder-memory/entries", {method:"POST",body:JSON.stringify(payload)}),
  checkpointSignalForgeFounderMemory: (payload:{subject_key:string;thesis_id?:string;note?:string}) => fetchJSON<Record<string,unknown>>("/signalforge/founder-memory/checkpoints", {method:"POST",body:JSON.stringify(payload)}),
  registerSignalForgeMarketAction: (payload:{thesis_id:string;action_type?:string;sample_target?:number;success_criteria?:string;failure_criteria?:string;note?:string}) => fetchJSON<Record<string,unknown>>("/signalforge/market-actions/register", {method:"POST",body:JSON.stringify(payload)}),
  completeSignalForgeMarketAction: (actionId:string,payload:{result:string;observations?:Record<string,unknown>;note?:string}) => fetchJSON<Record<string,unknown>>(`/signalforge/market-actions/${encodeURIComponent(actionId)}/complete`, {method:"POST",body:JSON.stringify(payload)}),
  signalforgeValidationExperiments: () => fetchJSON<SignalForgeValidationExperiments>("/signalforge/validation-experiments"),
  registerSignalForgeValidationExperiment: (payload:{case_id:number;claim_code:string;note?:string}) => fetchJSON<SignalForgeValidationExperiment>("/signalforge/validation-experiments/register", {method:"POST",body:JSON.stringify(payload)}),
  recordSignalForgeValidationResult: (experimentId:string,payload:{result:string;note:string;event?:string;actor_label?:string;amount?:number;currency?:string}) => fetchJSON<Record<string,unknown>>(`/signalforge/validation-experiments/${encodeURIComponent(experimentId)}/record-result`, {method:"POST",body:JSON.stringify(payload)}),
  triggerSignalForge: () => fetchJSON<{status:string;accepted?:boolean;pid?:number;dispatch_id?:string}>("/signalforge/trigger", {method:"POST"}),

  // Founder Opportunity Radar
  opportunitySummary: () => fetchJSON<OpportunitySummary>("/opportunities/summary"),
  opportunities: (params?:Record<string,string>) => fetchJSON<OpportunityItem[]>(`/opportunities?${new URLSearchParams(params)}`),
  opportunity: (id:number) => fetchJSON<OpportunityDetail>(`/opportunities/${id}`),
  updateOpportunityStatus: (id:number,status:string) => fetchJSON<OpportunityItem>(`/opportunities/${id}/status`, {method:"PATCH",body:JSON.stringify({status})}),

  problemCandidateSummary:()=>fetchJSON<ProblemCandidateSummary>("/candidates/summary"),
  problemCandidates:(params?:Record<string,string>)=>fetchJSON<ProblemCandidateItem[]>(`/candidates?${new URLSearchParams(params)}`),
  problemCandidate:(id:number)=>fetchJSON<ProblemCandidateDetail>(`/signalforge/opportunity/${id}/candidate`),
  updateProblemCandidateStatus:(id:number,status:string)=>fetchJSON<ProblemCandidateItem>(`/candidates/${id}/founder-status`,{method:"PATCH",body:JSON.stringify({status})}),
  // ── Cross-Source Signals ────────────────────────────────────────
  researchPipeline: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<ResearchPipelineItem>>(`/signals/research-pipeline?${new URLSearchParams(params)}`),
  tractionScores: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<TractionScoreItem>>(`/signals/traction-scores?${new URLSearchParams(params)}`),
  technologyLifecycle: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<TechnologyLifecycleItem>>(`/signals/technology-lifecycle?${new URLSearchParams(params)}`),
  marketGaps: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<MarketGapItem>>(`/signals/market-gaps?${new URLSearchParams(params)}`),
  competitiveThreats: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<CompetitiveThreatItem>>(`/signals/competitive-threats?${new URLSearchParams(params)}`),
  platformDivergence: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<PlatformDivergenceItem>>(`/signals/platform-divergence?${new URLSearchParams(params)}`),
  smartMoney: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<SmartMoneyItem>>(`/signals/smart-money?${new URLSearchParams(params)}`),
  talentFlow: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<TalentFlowItem>>(`/signals/talent-flow?${new URLSearchParams(params)}`),
  narrativeShifts: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<NarrativeShiftItem>>(`/signals/narrative-shifts?${new URLSearchParams(params)}`),
  signalSummary: () => fetchJSON<SignalSummary>("/signals/summary"),
  productDiscoveries: () => fetchJSON<AgentOutput>("/signals/product-discoveries"),
  insights: (params?: Record<string, string>) =>
    fetchJSON<InsightCard[]>(`/signals/insights?${new URLSearchParams(params)}`),
  crossSourceHighlights: () =>
    fetchJSON<CrossSourceHighlight[]>("/dashboard/cross-source-highlights"),
  agentOutput: (name: string) =>
    fetchJSON<AgentOutput>(`/signals/agent-output/${name}`),

  // ── Agent Management ────────────────────────────────────────────
  agentStatus: () => fetchJSON<AgentStatus[]>("/agents/status"),
  agentRuns: (params?: Record<string, string>) =>
    fetchJSON<AgentRun[]>(`/agents/runs?${new URLSearchParams(params)}`),
  agentRunDetail: (id: number) => fetchJSON<AgentRunDetail>(`/agents/runs/${id}`),
  triggerAgent: (name: string) =>
    fetchJSON<{ status: string; agent: string }>(`/agents/trigger/${name}`, { method: "POST" }),
  triggerAllAgents: () =>
    fetchJSON<{ status: string; agents: string }>("/agents/trigger-all", { method: "POST" }),
  agentCosts: (params?: Record<string, string>) =>
    fetchJSON<AgentCost[]>(`/agents/costs?${new URLSearchParams(params)}`),

  // ── Source Data ─────────────────────────────────────────────────
  githubTrending: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<GithubRepo>>(`/sources/github-trending?${new URLSearchParams(params)}`),
  hfTrending: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<HFModel>>(`/sources/hf-trending?${new URLSearchParams(params)}`),
  packageTrends: (params?: Record<string, string>) =>
    fetchJSON<PackageDownloadTrend[]>(`/sources/package-trends?${new URLSearchParams(params)}`),
  ycBatches: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<YCCompany>>(`/sources/yc-batches?${new URLSearchParams(params)}`),
  soTrends: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<SOQuestion>>(`/sources/so-trends?${new URLSearchParams(params)}`),
  phRecent: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<PHLaunch>>(`/sources/ph-recent?${new URLSearchParams(params)}`),

  // ── Product Reviews ───────────────────────────────────────────
  productReviews: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<ProductReviewItem>>(`/product-reviews/?${new URLSearchParams(params)}`),
  productReviewSummary: () =>
    fetchJSON<ProductReviewSummary>("/product-reviews/summary"),
  productReview: (productId: number) =>
    fetchJSON<ProductReviewItem>(`/product-reviews/${productId}`),

  // ── Gig Board ────────────────────────────────────────────────
  gigBoard: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<GigPostItem>>(`/gig-board/?${new URLSearchParams(params)}`),
  gigSummary: () =>
    fetchJSON<GigSummary>("/gig-board/summary"),
  gigTrends: () =>
    fetchJSON<GigTrends>("/gig-board/trends"),

  // ── Custom Market Research ────────────────────────────────────
  researchProjects: (params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<ResearchProject>>(`/research/?${new URLSearchParams(params)}`),
  researchProject: (id: number) =>
    fetchJSON<ResearchProject>(`/research/${id}`),
  createResearchProject: (data: ResearchProjectCreate) =>
    fetchJSON<ResearchProject>("/research/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  runResearch: (id: number) =>
    fetchJSON<{ status: string; project_id: number }>(`/research/${id}/run`, { method: "POST" }),
  researchInsights: (id: number) =>
    fetchJSON<ResearchInsights>(`/research/${id}/insights`),
  researchContacts: (id: number, params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<ResearchContact>>(`/research/${id}/contacts?${new URLSearchParams(params)}`),
  researchPosts: (id: number, params?: Record<string, string>) =>
    fetchJSON<PaginatedResponse<PostItem>>(`/research/${id}/posts?${new URLSearchParams(params)}`),
  deleteResearch: (id: number) =>
    fetchJSON<{ status: string }>(`/research/${id}`, { method: "DELETE" }),
};
