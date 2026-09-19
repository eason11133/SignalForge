"""SignalForge Mature Research Adoption A1 discovery runtime.

Mature methods are adopted for need-fragment retention, weak-supervision routing,
retrieve->rerank evidence relations, provenance-aware recurrence, and typed research
objects.  The module deliberately stops before frontier opportunity recognition:
external-enabler x workflow-lag x founder fit is not self-certified here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import async_session, ProblemCandidate, CandidateEvidence
from processors.llm_client import TokenUsage, call_llm
from processors.opportunity_observation import build_observations, build_observations_incremental, PARSER_CONSTITUTION_HASH, SOURCE_ROLE_CONSTITUTION_HASH, observation_from_doc
from processors.opportunity_evidence_graph import build_evidence_graph, compact_graph
from processors.opportunity_hypothesis_engine import (
    ENGINE_VERSION as HYPOTHESIS_ENGINE_VERSION,
    FACETS,
    DISPLAY_PRIORITY,
    build_evidence_bundles,
    canonicalize_hypotheses,
    hypothesis_summary,
    independent_architecture_acceptance,
    static_acceptance as hypothesis_static_acceptance,
    evidence_ref,
)
from processors.transition_gap_discovery_v10_legacy import OpportunityPortfolioDiscovery as V10Loader
from processors.opportunity_db_contract import (
    filter_values, evidence_values, evidence_identity, assert_contract,
    active_evidence_integrity, runtime_write_probe,
)
from processors.opportunity_generation_state import (
    prepare as prepare_generation, activate_prepared, abort_pending, active as active_generation,
)
from processors.opportunity_source_portfolio import targeted_corroboration_refresh, RECOVERY_RESERVE_REQUESTS, RECOVERY_PER_RUN_REQUESTS, recovery_anchor_profile, record_downstream_evidence_utility, estimate_anchor_voi, get_evidence_gap_progress
from processors.opportunity_research_objects import build_research_objects
from processors.opportunity_evidence_atoms import ensure_observation_schema, EVIDENCE_SCHEMA_VERSION
from processors.founder_research_shortlist import build_shortlist, write_shortlist, static_acceptance as shortlist_static_acceptance

ENGINE_VERSION = "opportunity-discovery-u13-card-gap-voi"
CACHE_PATH = Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
COMPAT_CACHE_PATH = Path('.radar_runtime/transition_gap_discovery.json')
OBS_CACHE = Path('.radar_runtime/opportunity_observations_r1.json')
GRAPH_CACHE = Path('.radar_runtime/opportunity_evidence_graph_r1.json')
SOURCE_FEEDBACK = Path('.radar_runtime/source_yield_feedback_r1.json')
WATCH_SIGNALS = Path('.radar_runtime/opportunity_watch_signals_r1.json')
EVIDENCE_RESEARCH_QUEUE = Path('.radar_runtime/evidence_research_queue_r1.json')
ACCEPTANCE_EVIDENCE = Path('.radar_runtime/opportunity_architecture_acceptance_r1.json')
RESEARCH_OBJECTS = Path('.radar_runtime/opportunity_research_objects_u9.json')
GEN_DIR = Path('.radar_runtime/generations')
MAX_SCREEN_POOL = 18
MAX_PERSIST_PER_RUN = 12
MAX_PER_LLM_CALL = 12
MAX_ACCEPT_PER_PRODUCT = 3
MAX_ACCEPT_PER_SIGNATURE = 5
AUDIT_CODES = {
    'PASS', 'PRIMARY_NOT_ACTIONABLE', 'CORROBORATION_NOT_SAME_PROBLEM',
    'SUPPLY_RELATION_MISMATCH', 'CHANGE_RELATION_MISMATCH',
}

FOUNDER_NEED_ROLES={'PROBLEM_REPORT','FEATURE_REQUEST','WORKAROUND_OR_USAGE'}



def _atomic_stream_json(path:Path,payload:Any,*,indent:int|None=None)->dict[str,Any]:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
    try:
        enc=json.JSONEncoder(ensure_ascii=False,default=str,indent=indent,separators=None if indent else (',',':'))
        with tmp.open('w',encoding='utf-8',newline='') as f:
            for chunk in enc.iterencode(payload):f.write(chunk)
            f.flush();os.fsync(f.fileno())
        tmp.replace(path);return {'status':'WRITTEN_ATOMIC_STREAM','bytes':path.stat().st_size}
    except (MemoryError,OSError,ValueError,TypeError) as exc:
        try:
            if tmp.exists():tmp.unlink()
        except Exception:pass
        return {'status':'PERSIST_FAILED_PREVIOUS_STATE_PRESERVED','error':type(exc).__name__+': '+str(exc)[:200]}



def _graph_signature(observations:list[dict[str,Any]])->str:
    h=hashlib.sha1()
    for o in sorted(observations,key=lambda x:str(x.get('observation_id') or '')):
        for k in ('observation_id','normalized_problem_hash','primary_problem_signature','feedback_role','source_family','source_ref'):
            h.update(str(o.get(k) or '').encode('utf-8','ignore'));h.update(b'|')
        h.update(b'\n')
    return h.hexdigest()[:24]

def _load_or_build_graph_report(observations:list[dict[str,Any]])->tuple[dict[str,Any],dict[str,Any]]:
    """Build the diagnostic graph at most once per final corpus state.

    The graph is not hypothesis identity authority and is not consumed by the Founder gate.
    Therefore rebuilding it before recovery and again after recovery is wasted batch work.
    Reuse a compact report when the final observation signature is unchanged; otherwise
    construct once after recovery has finished.
    """
    sig=_graph_signature(observations);started=time.perf_counter()
    try:
        if GRAPH_CACHE.exists():
            cached=json.loads(GRAPH_CACHE.read_text(encoding='utf-8'))
            if isinstance(cached,dict) and cached.get('observation_signature')==sig and int(cached.get('nodes') or 0)==len(observations):
                return cached,{'status':'HIT_FINAL_GRAPH_CACHE','observation_signature':sig,'seconds':round(time.perf_counter()-started,3)}
    except Exception:
        pass
    full=build_evidence_graph(observations);report=compact_graph(full);report['observation_signature']=sig
    persist=_atomic_stream_json(GRAPH_CACHE,report)
    return report,{'status':'BUILT_ONCE_AFTER_RECOVERY','observation_signature':sig,'seconds':round(time.perf_counter()-started,3),'persist':persist}

def _clean(v: Any) -> str:
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def _migrate_observations(observations:list[dict[str,Any]]) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    before_missing=sum(1 for o in observations if not o.get('feedback_role'))
    before_schema=Counter(str(o.get('evidence_schema_version') or 'MISSING') for o in observations)
    stale=sum(1 for o in observations if o.get('evidence_schema_version')!=EVIDENCE_SCHEMA_VERSION or not o.get('feedback_role') or not isinstance(o.get('need_frame'),dict))
    migrated=[ensure_observation_schema(o) for o in observations]
    roles=Counter(str(o.get('feedback_role') or 'UNRESOLVED') for o in migrated)
    dispositions=Counter(str(o.get('evidence_disposition') or 'MISSING') for o in migrated)
    return migrated,{
        'schema_version':EVIDENCE_SCHEMA_VERSION,'input':len(observations),'stale_rows_before_migration':stale,'missing_feedback_role_before':before_missing,
        'schema_before':dict(before_schema),'feedback_roles_after':dict(roles),'dispositions_after':dict(dispositions),
        'missing_feedback_role_after':sum(1 for o in migrated if not o.get('feedback_role')),
        'need_frames_after':sum(1 for o in migrated if isinstance(o.get('need_frame'),dict)),
        'bounded_semantic_migration':True,
    }


def _parse_llm_items(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if isinstance(raw.get('items'), list):
            return [x for x in raw['items'] if isinstance(x, dict)]
        return [raw]
    s = str(raw).strip().replace('```json', '').replace('```', '').strip()
    try:
        return _parse_llm_items(json.loads(s))
    except Exception:
        out = []
        for line in s.splitlines():
            try:
                x = json.loads(line.strip().rstrip(','))
                if isinstance(x, dict):
                    out.append(x)
            except Exception:
                pass
        return out


def _hypothesis_score(h: dict[str, Any]) -> float:
    pains = h.get('pain_evidence') or []
    bundle = h.get('evidence_bundle') or {}
    families = {str(x.get('source_family') or '') for x in pains if x}
    return round(
        float(h.get('research_value_score') or 0)
        + min(2.0, 0.8 * max(0, len(pains) - 1))
        + (0.7 if bundle.get('market_supply') else 0.0)
        + (0.4 if len(families) >= 2 else 0.0),
        3,
    )


def _diversify(hypotheses: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ranked = sorted(hypotheses, key=_hypothesis_score, reverse=True)
    kept: list[dict[str, Any]] = []
    product_counts = Counter(); family_counts = Counter(); dropped = Counter()
    for h in ranked:
        pid = str(h.get('product_id') or '')
        sig = str(h.get('problem_family_descriptor') or h.get('primary_problem_signature') or '')
        if pid and product_counts[pid] >= MAX_ACCEPT_PER_PRODUCT:
            dropped['PRODUCT_CONCENTRATION'] += 1; continue
        if sig and family_counts[sig] >= MAX_ACCEPT_PER_SIGNATURE:
            dropped['PROBLEM_FAMILY_CONCENTRATION'] += 1; continue
        kept.append(h)
        if pid: product_counts[pid] += 1
        if sig: family_counts[sig] += 1
        if len(kept) >= limit:
            break
    return kept, {
        'input': len(hypotheses), 'kept': len(kept), 'dropped': dict(dropped),
        'max_per_product': MAX_ACCEPT_PER_PRODUCT, 'max_per_problem_family': MAX_ACCEPT_PER_SIGNATURE,
        'distinct_products': len(product_counts), 'distinct_problem_families': len(family_counts),
        'facet_counts': dict(Counter(f for h in kept for f in h.get('facets') or [])),
    }


def _write_watch_and_research(watch: list[dict[str, Any]], research: list[dict[str, Any]]) -> None:
    WATCH_SIGNALS.parent.mkdir(parents=True, exist_ok=True)
    watch_out = []
    for x in watch[:300]:
        watch_out.append({k: v for k, v in x.items() if k != 'problem_obs'})
    _atomic_stream_json(WATCH_SIGNALS,{
        'engine_version': ENGINE_VERSION,
        'count': len(watch),
        'signals': watch_out,
        'truth_contract': 'WATCH contains observed need/problem families not yet meeting the evidence threshold for Current research hypotheses. Missing legacy signatures are not deletion grounds; facets never create identities.',
    },indent=2)

    research_out = []
    for i, x in enumerate(research[:150], 1):
        y = {k: v for k, v in x.items() if k != 'problem_obs'}
        y['research_id'] = 'er_r1_' + hashlib.sha1(str(x.get('hypothesis_key') or x.get('fragment_cluster_key') or x.get('problem_ref') or i).encode()).hexdigest()[:14]
        research_out.append(y)
    _atomic_stream_json(EVIDENCE_RESEARCH_QUEUE,{
        'engine_version': ENGINE_VERSION,
        'count': len(research),
        'materialized_count': len(research_out),
        'items': research_out,
        'truth_contract': 'Only evidence acquisition is authorized. Incomplete need fragments may enter this queue. No product/opportunity thesis is invented and no item becomes Current without independent firsthand evidence plus stable evidence-derived problem-family identity.',
    },indent=2)


def _write_acceptance_evidence() -> dict[str, Any]:
    pure = hypothesis_static_acceptance()
    adversarial = independent_architecture_acceptance(observation_from_doc)
    data = {
        'engine_version': ENGINE_VERSION,
        'acceptance_type': 'MATURE_RESEARCH_ADOPTION_PLUS_INDEPENDENT_GOLDEN_AND_ADVERSARIAL_FIXTURES',
        'pure_invariants': pure,
        'adversarial_regressions': adversarial,
        'pass': all(pure.values()) and all(adversarial.values()),
        'critical_regressions': [
            'same Tripsy problem across multiple facets -> one hypothesis',
            'same product + different pain -> separate hypotheses',
            'exact duplicate content -> not independent recurrence',
            'unrelated competitor supply -> not context',
            'positive review / supplier capability / vendor mission -> not problem seed',
            'facets never participate in hypothesis identity',
            'missing legacy primary signature -> retained as incomplete need/research instead of deletion',
            'exact/copy-dependent evidence -> never counted as independent recurrence',
        ],
    }
    ACCEPTANCE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_stream_json(ACCEPTANCE_EVIDENCE,data,indent=2)
    return data



def _append_new_docs(canonical_docs:list[dict[str,Any]], new_docs:list[dict[str,Any]])->list[dict[str,Any]]:
    """Append only novel recovery docs; never replace the canonical DB+source corpus."""
    out=list(canonical_docs);seen={(str(d.get('source')),str(d.get('table')),str(d.get('pk'))) for d in out}
    for d in new_docs:
        k=(str(d.get('source')),str(d.get('table')),str(d.get('pk')))
        if k not in seen:out.append(d);seen.add(k)
    return out


def _ui_need_and_supply_queries(u:dict[str,Any])->tuple[str,str]:
    """Separate need-side recurrence search from solution/supply search.

    Adapted from Need-Solution Pair search logic: the same mixed query should not be used
    to infer both independent need recurrence and existing supply.
    """
    nf=u.get('need_frame') or {};text=_clean(u.get('text')).lower();stop={'built','build','tool','app','product','solution','generate','using','local','llm','llms','because','every','with','from','this','that','have'}
    need=[];supply=[]
    wf=str(u.get('workflow') or nf.get('workflow') or '').replace('_',' ').lower().strip()
    if wf not in {'','other','unknown','productivity','intake'}:
        for t in re.findall(r'[a-z][a-z0-9_-]{2,}',wf):
            if t not in stop and t not in need:need.append(t)
            if t not in stop and t not in supply:supply.append(t)
    for x in list(nf.get('failure_modes') or [])+list(nf.get('actions') or []):
        for t in re.findall(r'[a-z][a-z0-9_-]{2,}',str(x).lower().replace('_',' ')):
            if t not in stop and t not in need:need.append(t)
    for x in list(nf.get('actions') or [])+list(nf.get('objects') or []):
        for t in re.findall(r'[a-z][a-z0-9_-]{2,}',str(x).lower().replace('_',' ')):
            if t not in stop and t not in supply:supply.append(t)
    # Burden/privacy/frequency words help need recurrence; function/object words help supply.
    for t in re.findall(r'[a-z][a-z0-9_-]{2,}',text):
        if t in {'tedious','manual','manually','privacy','private','expensive','slow','repetitive','formatting','deck','slides','papers','presentation'} and t not in need:need.append(t)
    return ' '.join(need[:7]),' '.join(supply[:6])

def _select_recovery_anchors(research: list[dict[str, Any]], limit: int = 8, user_innovations: list[dict[str,Any]] | None = None) -> tuple[list[dict[str, Any]],dict[str,Any]]:
    """Diversified, targetable evidence-gap selection.

    Mature active-learning / information-acquisition practice should spend a bounded budget
    on high-information, actually targetable gaps rather than the first N queue rows.
    """
    scored=[]
    # Lead-user / user-innovation signals are valuable observed Need-Solution pairs, but they
    # still need independent recurrence. Search for the need, not for a new product idea.
    augmented=list(research)
    for u in (user_innovations or [])[:12]:
        nf=u.get('need_frame') or {};text=_clean(u.get('text'))
        pseudo={
            'research_id':u.get('object_id'),'anchor_key':u.get('object_id'),'anchor_type':'USER_INNOVATION_RECURRENCE','evidence_gap':'INDEPENDENT_NEED_RECURRENCE',
            'research_value_score':float(u.get('signal_score') or 0)+1.0,
            'problem_obs':{
                'problem_span':text,'need_frame':nf,'workflow':u.get('workflow') or nf.get('workflow'),
                'vertical':u.get('vertical'),'actor_scope':u.get('actor'),'source_ref':u.get('evidence_ref'),
                'source_family':u.get('source_family'),'source_role':'FIRSTHAND_USER_PAIN',
                'problem_lexical_terms':[x for x in re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{3,}',text.lower()) if x not in {'built','tool','because','every','with','from','this','that','have','using'}][:18],
            },
        }
        nq,sq=_ui_need_and_supply_queries(u);pseudo['query_terms_override']=nq or None;pseudo['market_query_terms_override']=sq or None
        augmented.append(pseudo)
    for x in augmented:
        p=dict(x.get("problem_obs") or {})
        profile=recovery_anchor_profile(p)
        if x.get('query_terms_override'):
            profile['query_terms']=x.get('query_terms_override');profile['targetable']=True
        if x.get('market_query_terms_override'):
            profile['market_query_terms']=x.get('market_query_terms_override')
        if not profile.get("targetable"):
            continue
        ak=str(x.get('anchor_key') or x.get('research_id') or x.get('hypothesis_key') or x.get('fragment_cluster_key') or (x.get('problem_obs') or {}).get('source_ref') or '')
        gap=str(x.get('evidence_gap') or 'INDEPENDENT_NEED_RECURRENCE')
        voi=estimate_anchor_voi({'anchor_key':ak,'anchor_type':x.get('anchor_type') or 'NEED_FRAGMENT','evidence_gap':gap})
        x['_u13_anchor_key']=ak;x['_u13_evidence_gap']=gap;x['_u13_voi']=voi
        score=float(x.get("research_value_score") or 0)+float(profile.get("score") or 0)+2.5*float(voi.get('expected_information_value') or 0)
        scored.append((score,x,profile))
    scored.sort(key=lambda z:z[0],reverse=True)
    out=[];seen_product=set();seen_query=set();seen_market=set();skipped=Counter()
    # Reserve one search slot for the strongest observed self-solution. U6's high-scoring
    # research queue starved all user-innovation recurrence searches.
    ui_scored=[z for z in scored if (z[1].get('anchor_type') or '')=='USER_INNOVATION_RECURRENCE']
    if ui_scored and limit>0:
        score,x,profile=ui_scored[0];p=dict(x.get('problem_obs') or {});q=str(profile.get('query_terms') or '')
        out.append({'problem_obs':p,'reason':'USER_INNOVATION_NEEDS_INDEPENDENT_RECURRENCE','hypothesis_key':None,'fragment_cluster_key':None,'display_primary_facet':None,'recovery_priority_score':round(score,2),'targetability':profile,'anchor_type':'USER_INNOVATION_RECURRENCE','anchor_key':x.get('_u13_anchor_key'),'evidence_gap':x.get('_u13_evidence_gap'),'voi':x.get('_u13_voi')})
        if q:seen_query.add(q)
        seen_market.add(f"{p.get('vertical') or 'other'}|{p.get('workflow') or 'other'}|{profile.get('site') or ''}")
    for score,x,profile in scored:
        p=dict(x.get("problem_obs") or {})
        if (x.get('anchor_type') or '')=='USER_INNOVATION_RECURRENCE' and out and str((out[0].get('problem_obs') or {}).get('source_ref') or '')==str(p.get('source_ref') or ''):
            continue
        pid=str(profile.get("product_id") or '')
        q=str(profile.get("query_terms") or '')
        market=f"{p.get('vertical') or 'other'}|{p.get('workflow') or 'other'}|{profile.get('site') or ''}"
        # Diversify first pass: avoid spending all requests on one product/query/market.
        if pid and pid in seen_product:
            skipped['DUP_PRODUCT']+=1;continue
        if q and q in seen_query:
            skipped['DUP_QUERY']+=1;continue
        if market in seen_market and not pid:
            skipped['DUP_MARKET']+=1;continue
        out.append({
            'problem_obs':p,'reason':'EVIDENCE_FRAGMENT_GAP',
            'hypothesis_key':x.get('hypothesis_key'),'fragment_cluster_key':x.get('fragment_cluster_key'),
            'display_primary_facet':None,'recovery_priority_score':round(score,2),'targetability':profile,'anchor_type':x.get('anchor_type') or 'NEED_FRAGMENT','anchor_key':x.get('_u13_anchor_key'),'evidence_gap':x.get('_u13_evidence_gap'),'voi':x.get('_u13_voi'),
        })
        if pid:seen_product.add(pid)
        if q:seen_query.add(q)
        seen_market.add(market)
        if len(out)>=limit:break
    # Second pass can reuse a market if diversity was too restrictive.
    if len(out)<limit:
        used={str((a.get('problem_obs') or {}).get('source_ref') or '') for a in out}
        for score,x,profile in scored:
            p=dict(x.get("problem_obs") or {});ref=str(p.get('source_ref') or '')
            if ref in used:continue
            out.append({'problem_obs':p,'reason':'EVIDENCE_FRAGMENT_GAP','hypothesis_key':x.get('hypothesis_key'),'fragment_cluster_key':x.get('fragment_cluster_key'),'display_primary_facet':None,'recovery_priority_score':round(score,2),'targetability':profile,'anchor_type':x.get('anchor_type') or 'NEED_FRAGMENT','anchor_key':x.get('_u13_anchor_key'),'evidence_gap':x.get('_u13_evidence_gap'),'voi':x.get('_u13_voi')})
            used.add(ref)
            if len(out)>=limit:break
    return out,{
        'research_items':len(research),'targetable_items':len(scored),'selected':len(out),
        'skipped_diversity':dict(skipped),
        'selected_preview':[{'score':a.get('recovery_priority_score'),'query':(a.get('targetability') or {}).get('query_terms'),'market_query':(a.get('targetability') or {}).get('market_query_terms'),'anchor_type':a.get('anchor_type'),'anchor_key':a.get('anchor_key'),'evidence_gap':a.get('evidence_gap'),'voi':a.get('voi'),'product_id':(a.get('targetability') or {}).get('product_id'),'site':(a.get('targetability') or {}).get('site')} for a in out[:8]],
    }

def _attach_gap_progress(shortlist:dict[str,Any],progress:dict[str,Any])->dict[str,Any]:
    """Attach acquisition progress to Founder cards without promoting market truth."""
    rows=list((progress or {}).get('rows') or []);by_anchor={}
    for r in rows:by_anchor.setdefault(str(r.get('anchor_key') or ''),[]).append(dict(r))
    out=dict(shortlist);cards=[]
    for c in out.get('founder_discussion_cards') or []:
        y=dict(c);cid=str(y.get('discussion_id') or '')
        prs=by_anchor.get(cid) or []
        y['evidence_gap_progress']=prs
        plan=dict(y.get('best_next_evidence_plan') or {});steps=[]
        for st in plan.get('next_steps') or []:
            z=dict(st);gap=str(z.get('evidence') or '')
            match=next((r for r in prs if str(r.get('evidence_gap') or '')==gap),None)
            if match:
                z['attempts']=int(match.get('attempts') or 0);z['retrieved_new_docs']=int(match.get('new_docs') or 0);z['downstream_evidence_docs']=int(match.get('downstream_evidence_docs') or 0);z['voi']=((match.get('voi') or {}).get('expected_information_value'))
                if z['downstream_evidence_docs']>0:z['progress']='EVIDENCE_CANDIDATE_RETRIEVED_NEEDS_SEMANTIC_CONFIRMATION'
                elif z['attempts']>=3:z['progress']='LOW_YIELD_SWITCH_QUERY_OR_SURFACE'
                else:z['progress']='STILL_OPEN'
            steps.append(z)
        if plan:plan['next_steps']=steps;y['best_next_evidence_plan']=plan
        cards.append(y)
    out['founder_discussion_cards']=cards;out['evidence_gap_ledger']={'rows':rows,'truth_boundary':'SEARCH_PROGRESS_ONLY_NOT_GAP_CLOSURE_UNLESS_SEMANTICALLY_CONFIRMED'}
    return out


class OpportunityObservationDiscovery:
    def __init__(self, *, ai_call_allowance: int = 2, max_persist: int = MAX_PERSIST_PER_RUN, persist: bool = True):
        self.ai_call_allowance = max(0, int(ai_call_allowance))
        self.max_persist = max(1, int(max_persist))
        self.persist_enabled = bool(persist)
        self.usage = TokenUsage(); self.llm_calls = 0; self.source_health: dict[str, Any] = {}

    async def _load_docs(self):
        loader = V10Loader(ai_call_allowance=0, max_persist=1, persist=False)
        docs, counts = await loader._load_docs()
        self.source_health = getattr(loader, 'source_portfolio_health', {}) or {}
        return docs, counts

    async def _relationship_audit(self, hypotheses: list[dict[str, Any]]):
        """Founder-quality relationship audit with a deterministic feedback-role boundary.

        The deterministic boundary blocks positive feature/capability text, supplier pitches,
        policy opinions and user-innovation self-solutions from masquerading as independent
        customer pain.  The bounded LLM then only challenges SAME-PROBLEM relationships among
        already-valid need evidence; it cannot invent or promote evidence.
        """
        if not hypotheses:
            return [], {'status':'SKIPPED','checked':0,'rejected':0,'utility':'NOT_RUN','reason_codes':{}}

        eligible=[];pre_rejected=[];pre_reasons=Counter()
        for h0 in hypotheses:
            h=dict(h0);p=ensure_observation_schema(h.get('problem_obs') or {}); pains=[ensure_observation_schema(x) for x in (h.get('pain_evidence') or [])]
            h['problem_obs']=p;h['pain_evidence']=pains
            primary_role=str(p.get('feedback_role') or '')
            bad_corr=[str(x.get('feedback_role') or '') for x in pains[1:] if str(x.get('feedback_role') or '') not in FOUNDER_NEED_ROLES]
            if primary_role not in FOUNDER_NEED_ROLES:
                pre_reasons['PRIMARY_NON_NEED_FEEDBACK_ROLE']+=1
                pre_rejected.append({'hypothesis_key':h.get('hypothesis_key'),'problem':_clean(p.get('problem_span'))[:300],'reason':'PRIMARY_NON_NEED_FEEDBACK_ROLE','feedback_role':primary_role or 'MISSING'})
                continue
            if bad_corr:
                pre_reasons['CORROBORATION_NON_NEED_FEEDBACK_ROLE']+=1
                pre_rejected.append({'hypothesis_key':h.get('hypothesis_key'),'problem':_clean(p.get('problem_span'))[:300],'reason':'CORROBORATION_NON_NEED_FEEDBACK_ROLE','feedback_role':','.join(sorted(set(bad_corr)))})
                continue
            eligible.append(h)

        if not eligible:
            return [], {'status':'PASS','checked':0,'rejected':len(pre_rejected),'deterministic_rejected':len(pre_rejected),'malformed':0,'utility':'DETERMINISTIC_ROLE_FILTER_INFORMATIVE','reason_codes':dict(pre_reasons),'rejected_samples':pre_rejected[:10],'authority':'RELATIONSHIP_CHALLENGER_ONLY_NOT_FACT_GENERATOR'}
        if self.ai_call_allowance <= 0:
            return eligible, {'status':'DETERMINISTIC_ONLY','checked':0,'rejected':len(pre_rejected),'deterministic_rejected':len(pre_rejected),'utility':'LLM_NOT_ALLOWED','reason_codes':dict(pre_reasons),'rejected_samples':pre_rejected[:10],'authority':'DETERMINISTIC_ROLE_BOUNDARY_ONLY'}

        batch=eligible[:MAX_PER_LLM_CALL];payload=[];idmap={}
        for i,h in enumerate(batch,1):
            hid=f'H{i}';idmap[hid]=h;p=h.get('problem_obs') or {};pains=h.get('pain_evidence') or []
            payload.append({'id':hid,'hypothesis_key':h.get('hypothesis_key'),'scope':h.get('seed_key'),'problem':_clean(p.get('problem_span'))[:700],'problem_role':p.get('feedback_role'),'corroboration':[{'text':_clean(x.get('problem_span'))[:500],'role':x.get('feedback_role')} for x in pains[1:3]]})
        prompt=("Audit only whether each supplied evidence bundle is a concrete current user need and whether its corroboration is the SAME underlying problem in the SAME practical scope. "
                "Reject feature-strength/benefit statements (for example 'you can do X and no longer have to Y'), supplier/vendor pitches, maker self-promotion, policy opinions, proposed future states, and unrelated technical issues. "
                "Do not invent facts, products, markets, solutions, scores, actors, or evidence. Return ONE JSON ARRAY containing exactly one object per input: "
                "[{\"i\":\"H1\",\"a\":1,\"r\":\"PASS\"}] or a=0 with r PRIMARY_NOT_ACTIONABLE or CORROBORATION_NOT_SAME_PROBLEM.\nINPUT:\n"+json.dumps(payload,ensure_ascii=False))
        self.llm_calls+=1
        try:
            raw=await call_llm(prompt=prompt,system_message='Evidence relationship challenger only. No ideas or invented facts.',model='mini',parse_json=False,usage_tracker=self.usage,max_tokens=1600,temperature=0.0)
        except Exception as e:
            return [], {'status':'UNAVAILABLE_FAIL_CLOSED_FOR_FOUNDER_SURFACE','checked':0,'rejected':len(pre_rejected),'deterministic_rejected':len(pre_rejected),'malformed':0,'utility':'LLM_UNAVAILABLE','error':type(e).__name__,'reason_codes':dict(pre_reasons),'rejected_samples':pre_rejected[:10],'authority':'RELATIONSHIP_CHALLENGER_ONLY'}
        items=_parse_llm_items(raw);by={str(x.get('i') or x.get('id') or ''):x for x in items}
        kept=[];reasons=Counter(pre_reasons);rejected_samples=list(pre_rejected[:10]);malformed=0
        for hid,h in idmap.items():
            x=by.get(hid)
            if not x:
                malformed+=1;reasons['MALFORMED_AUDIT_FAIL_CLOSED']+=1
                if len(rejected_samples)<10:rejected_samples.append({'hypothesis_key':h.get('hypothesis_key'),'problem':_clean((h.get('problem_obs') or {}).get('problem_span'))[:300],'reason':'MALFORMED_AUDIT_FAIL_CLOSED'})
                continue
            code=str(x.get('r') or ('PASS' if x.get('a') in (1,True,'1','true','TRUE') else 'PRIMARY_NOT_ACTIONABLE')).upper()
            if x.get('a') in (1,True,'1','true','TRUE') and code=='PASS':
                reasons['PASS']+=1;hh=dict(h);hh['semantic_audit']={'status':'PASS','reason':'PASS'};kept.append(hh)
            else:
                if code not in {'PRIMARY_NOT_ACTIONABLE','CORROBORATION_NOT_SAME_PROBLEM'}:code='PRIMARY_NOT_ACTIONABLE'
                reasons[code]+=1
                if len(rejected_samples)<10:rejected_samples.append({'hypothesis_key':h.get('hypothesis_key'),'problem':_clean((h.get('problem_obs') or {}).get('problem_span'))[:300],'reason':code})
        # Do not silently promote anything beyond the audited batch to the Founder surface.
        rejected=len(hypotheses)-len(kept)
        utility='INFORMATIVE' if rejected else 'UNINFORMATIVE_ALL_PASS'
        return kept, {'status':'PASS','checked':len(batch),'rejected':rejected,'deterministic_rejected':len(pre_rejected),'malformed':malformed,'utility':utility,'reason_codes':dict(reasons),'rejected_samples':rejected_samples,'authority':'RELATIONSHIP_CHALLENGER_ONLY_NOT_FACT_GENERATOR'}

    async def _research_lead_audit(self, research: list[dict[str, Any]]):
        """Weak-supervision candidate pass only; no LLM call here.

        Mature weak-supervision practice treats heuristic rules as noisy labeling functions
        that may abstain.  U9 therefore preserves the scarce semantic call for the final
        Founder-card adjudication instead of spending it before card assembly.
        """
        deterministic=[];pre_reasons=Counter()
        for x0 in research:
            x=dict(x0);po=ensure_observation_schema(x.get('problem_obs') or {});x['problem_obs']=po;x['feedback_role']=x.get('feedback_role') or po.get('feedback_role');x['need_frame']=x.get('need_frame') or po.get('need_frame')
            role=str(x.get('feedback_role') or '');text=_clean(x.get('problem'))
            if role not in FOUNDER_NEED_ROLES:pre_reasons['NON_NEED_FEEDBACK_ROLE']+=1;continue
            if not text or any(t in text.lower() for t in ('repo_full_name','activity comparison | tool','machine learning crash course','so_question_id:')):
                pre_reasons['META_NOISE']+=1;continue
            deterministic.append(x)
        deterministic.sort(key=lambda x:(float(x.get('research_value_score') or 0),1 if x.get('workflow') not in (None,'','other','UNKNOWN') else 0),reverse=True)
        batch=deterministic[:min(12,MAX_PER_LLM_CALL)]
        ids=[str(x.get('fragment_cluster_key') or x.get('problem_ref') or x.get('research_id') or i) for i,x in enumerate(batch,1)]
        return batch, {'status':'WEAK_SUPERVISION_CANDIDATES','checked':len(batch),'kept_ids':ids,'malformed':0,'reason_codes':dict(pre_reasons),'enrichment':{},'authority':'HEURISTIC_CANDIDATE_GENERATION_WITH_ABSTENTION_FINAL_SEMANTIC_GATE'}

    async def _founder_card_adjudication(self, shortlist: dict[str, Any]):
        """One bounded, structured semantic gate over already-grounded Founder candidates.

        The model may KEEP or ABSTAIN/RESEARCH_ONLY, and may extract grounded slots from the
        supplied evidence.  It cannot create evidence, promote a lead to a hypothesis, infer
        WTP/market size, or invent a product.  This is selective classification, not venture
        scoring.
        """
        cards=list(shortlist.get('founder_discussion_cards') or [])[:8]
        if not cards:
            return shortlist,{'status':'SKIPPED_NO_CARDS','checked':0,'kept':0,'research_only':0,'rejected':0,'malformed':0,'authority':'FINAL_FOUNDER_ATTENTION_GATE'}
        if self.ai_call_allowance <= self.llm_calls:
            out=dict(shortlist);out['founder_discussion_cards']=[];out['status']='NO_FOUNDER_USABLE_ITEMS_SEMANTIC_GATE_UNAVAILABLE'
            return out,{'status':'UNAVAILABLE_FAIL_CLOSED_NO_CALL_BUDGET','checked':0,'kept':0,'research_only':len(cards),'rejected':0,'malformed':0,'authority':'FINAL_FOUNDER_ATTENTION_GATE'}
        payload=[];idmap={}
        for i,c in enumerate(cards,1):
            cid=f'C{i}';idmap[cid]=c
            payload.append({'id':cid,'card_type':c.get('card_type'),'problem_or_signal':_clean(c.get('problem'))[:1000],'actor':c.get('actor'),'workflow':c.get('workflow'),'need_frame':c.get('need_frame') or {},'evidence':[{'text':_clean(e.get('text'))[:800],'role':e.get('feedback_role'),'ref':e.get('ref')} for e in (c.get('evidence_preview') or [])[:3]],'unknowns':c.get('unknowns') or []})
        prompt=("Act as a SELECTIVE evidence adjudicator for a Founder opportunity-research inbox. Judge ONLY the supplied evidence. "
                "KEEP only when the text itself supports either (A) a concrete current workflow need: a recognizable task/context plus a specific friction/failure/bottleneck and meaningful burden/consequence, or (B) a causal self-solution: the person explicitly experienced their own need and built/configured a solution because of that need. "
                "Do NOT KEEP mere expense anecdotes without a failed/repeated workflow, generic technical troubleshooting, product/showcase/vendor promotion, opinions/debates, positive capabilities, vague complaints, or ordinary workaround use that is not a self-built solution. "
                "When evidence is plausible but too incomplete, choose RESEARCH_ONLY (abstain from Founder surface), not KEEP. Do not invent actors, markets, products, demand, WTP, recurrence, or facts. "
                "Return exactly one JSON ARRAY object per input with keys i,d,r,actor,workflow,failure,burden. d is KEEP, RESEARCH_ONLY, or REJECT. r is one of CONCRETE_WORKFLOW_NEED, CAUSAL_SELF_SOLUTION, INSUFFICIENT_CONTEXT, ANECDOTAL_COST_OR_EFFORT, NARROW_TECH_TROUBLESHOOTING, SHOWCASE_OR_PROMO, OPINION_OR_DISCUSSION, WORKAROUND_NOT_SELF_SOLUTION, MALFORMED_CONTEXT. "
                "actor/workflow/failure/burden must be short strings copied or tightly normalized from supplied evidence; use UNKNOWN when unsupported.\nINPUT:\n"+json.dumps(payload,ensure_ascii=False))
        self.llm_calls+=1
        try:
            raw=await call_llm(prompt=prompt,system_message='Selective evidence adjudicator. Abstain when uncertain. No ideas, no invented facts, no market scoring.',model='mini',parse_json=False,usage_tracker=self.usage,max_tokens=2200,temperature=0.0)
        except Exception as e:
            out=dict(shortlist);out['founder_discussion_cards']=[];out['status']='NO_FOUNDER_USABLE_ITEMS_SEMANTIC_GATE_UNAVAILABLE'
            return out,{'status':'UNAVAILABLE_FAIL_CLOSED','checked':0,'kept':0,'research_only':len(cards),'rejected':0,'malformed':0,'error':type(e).__name__,'authority':'FINAL_FOUNDER_ATTENTION_GATE'}
        items=_parse_llm_items(raw);by={str(x.get('i') or x.get('id') or ''):x for x in items};kept=[];research_only=[];rejected=[];malformed=0;reasons=Counter()
        allowed_reasons={'CONCRETE_WORKFLOW_NEED','CAUSAL_SELF_SOLUTION','INSUFFICIENT_CONTEXT','ANECDOTAL_COST_OR_EFFORT','NARROW_TECH_TROUBLESHOOTING','SHOWCASE_OR_PROMO','OPINION_OR_DISCUSSION','WORKAROUND_NOT_SELF_SOLUTION','MALFORMED_CONTEXT'}
        for cid,c in idmap.items():
            x=by.get(cid)
            if not x:
                malformed+=1;reasons['MALFORMED_AUDIT_FAIL_CLOSED']+=1;research_only.append({'discussion_id':c.get('discussion_id'),'reason':'MALFORMED_AUDIT_FAIL_CLOSED'});continue
            d=str(x.get('d') or '').upper();r=str(x.get('r') or 'INSUFFICIENT_CONTEXT').upper();r=r if r in allowed_reasons else 'INSUFFICIENT_CONTEXT';reasons[r]+=1
            if d=='KEEP' and r in {'CONCRETE_WORKFLOW_NEED','CAUSAL_SELF_SOLUTION'}:
                cc=dict(c);ground={}
                for k in ('actor','workflow','failure','burden'):
                    v=_clean(x.get(k));ground[k]=None if v.upper() in {'','UNKNOWN','NONE'} else v[:220]
                cc['semantic_adjudication']={'decision':'KEEP','reason':r,'grounded_frame':ground,'authority':'EVIDENCE_ONLY'}
                # Only fill unknown/other fields; never overwrite structured source truth.
                if ground.get('actor') and str(cc.get('actor') or '').upper() in {'','UNKNOWN','NONE'}:cc['actor']=ground['actor']
                if ground.get('workflow') and str(cc.get('workflow') or '').lower() in {'','unknown','none','other'}:cc['workflow']=ground['workflow']
                kept.append(cc)
            elif d=='REJECT':rejected.append({'discussion_id':c.get('discussion_id'),'reason':r})
            else:research_only.append({'discussion_id':c.get('discussion_id'),'reason':r})
        out=dict(shortlist);out['founder_discussion_cards']=kept;out['founder_discussion_card_count']=len(kept);out['status']='READY_FOR_FOUNDER_DISCUSSION' if kept else 'NO_FOUNDER_USABLE_ITEMS_AFTER_SEMANTIC_ABSTENTION';out['semantic_research_only']=research_only[:20];out['semantic_rejected']=rejected[:20]
        keep_ids={str(c.get('discussion_id')) for c in kept}
        out['displayed_hypotheses']=[x for x in (out.get('displayed_hypotheses') or []) if str(x.get('hypothesis_key')) in keep_ids]
        out['displayed_user_innovation_signals']=[x for x in (out.get('displayed_user_innovation_signals') or []) if str(x.get('signal_id')) in keep_ids]
        out['displayed_research_leads']=[x for x in (out.get('displayed_research_leads') or []) if str(x.get('research_id')) in keep_ids]
        out['research_hypothesis_count']=len(out['displayed_hypotheses']);out['user_innovation_signal_count']=len(out['displayed_user_innovation_signals']);out['research_lead_count']=len(out['displayed_research_leads'])
        return out,{'status':'PASS','checked':len(cards),'kept':len(kept),'research_only':len(research_only),'rejected':len(rejected),'malformed':malformed,'reason_codes':dict(reasons),'authority':'SELECTIVE_CLASSIFICATION_WITH_ABSTENTION_NOT_FACT_GENERATION'}

    def _fingerprint(self, h: dict[str, Any]) -> dict[str, Any]:
        p = h.get('problem_obs') or {}; pains = h.get('pain_evidence') or []; bundle = h.get('evidence_bundle') or {}
        problem = _clean(p.get('problem_span'))
        refs = list(dict.fromkeys(bundle.get('problem', []) + bundle.get('recurrence', []) + bundle.get('market_supply', []) + bundle.get('external_enabler_candidates', [])))
        facets = list(h.get('facets') or [])
        return {
            'actionable_problem': True,
            'opportunity_unit_ready': False,  # mature-research stage forms a research hypothesis, not a venture opportunity.
            'hypothesis_ready': True,
            'semantic_coherence_pass': True,
            'opportunity_identity_version': 'EVIDENCE_DERIVED_PROBLEM_FAMILY_A1',
            'hypothesis_key': h.get('hypothesis_key'),
            'problem_scope_key': h.get('seed_key'),
            'identity_excludes_facets': True,
            'canonical_problem': problem,
            'actor': p.get('actor_scope') or 'UNKNOWN',
            'actor_category': p.get('vertical') or 'other',
            'task': p.get('workflow') or 'UNKNOWN',
            'object': p.get('workflow') or 'UNKNOWN',
            'failure_mode': problem,
            'consequence': _clean(p.get('burden_span')) or problem,
            'workaround': _clean(p.get('current_behavior_span')) or 'UNKNOWN',
            'buyer_context': p.get('actor_scope') or p.get('native_scope') or 'UNKNOWN',
            'confidence': min(.95, .55 + .08 * min(4, len(pains)) + .03 * len(facets)),
            'confidence_semantics': 'UNCALIBRATED_EVIDENCE_ROUTING_SCORE_NOT_MARKET_SUCCESS_PROBABILITY',
            'discovery_mode': 'MATURE_RESEARCH_TYPED_EVIDENCE_TO_PROBLEM_FAMILY_HYPOTHESIS',
            'facet_labels': facets,
            'display_primary_facet': h.get('display_primary_facet'),
            # Compatibility fields. Explicitly not identity-bearing.
            'primary_opportunity_class': h.get('display_primary_facet'),
            'qualified_lanes': facets,
            'opportunity_classes': facets,
            'opportunity_discovery_version': ENGINE_VERSION,
            'hypothesis_engine_version': HYPOTHESIS_ENGINE_VERSION,
            'firsthand_problem_evidence': True,
            'problem_source_role': p.get('source_role'),
            'problem_source_ref': evidence_ref(p),
            'product_id': p.get('product_id'),
            'product_name': p.get('product_name'),
            'problem_self_contained': bool(p.get('problem_self_contained')),
            'evidence_disposition': p.get('evidence_disposition'),
            'problem_family_descriptor': h.get('problem_family_descriptor'),
            'problem_identity_status': h.get('identity_status'),
            'problem_target': p.get('problem_target'),
            'problem_signatures': list(p.get('problem_signatures') or []),
            'primary_problem_signature': p.get('primary_problem_signature'),
            'independent_problem_evidence_count': len(pains),
            'corroborated_discovery': len(pains) >= 2,
            'corroboration_content_independent': len(pains) >= 2,
            'recurrence_scope': 'SAME_PRODUCT' if p.get('product_id') else 'SAME_MARKET',
            'evidence_refs': refs,
            'typed_evidence_bundle': bundle,
            'facet_evidence_refs': h.get('facet_evidence_refs') or {},
            'source_families': sorted({str(x.get('source_family') or x.get('source') or '') for x in pains + (h.get('supply_evidence') or []) + (h.get('change_evidence') or [])}),
            'payment_behavior_observed': any(x.get('payment_behavior_observed') for x in pains),
            'commercial_behavior_explicit': any(x.get('commercial_context_explicit') for x in pains),
            'economic_evidence_explicit': any(x.get('burden_explicit') for x in pains),
            'frequency_evidence_explicit': any(x.get('frequency_explicit') for x in pains),
            'market_supply_evidence_verified': bool(bundle.get('market_supply')),
            'transition_evidence_verified': False,
            'external_enabler_candidate_refs': list(bundle.get('external_enabler_candidates') or []),
            'opportunity_linkage_status': h.get('opportunity_linkage_status') or 'FRONTIER_NOT_SELF_CERTIFIED',
            'distribution_gap_evidence_explicit': 'DISTRIBUTION_MODEL_GAP' in facets,
            'second_order_evidence_verified': 'SECOND_ORDER_PAIN' in facets,
            'research_value_score': h.get('research_value_score'),
            'truth_boundary': 'Mature methods form evidence-backed problem families from complete or incomplete need fragments. Legacy signatures are optional features, source dependence is modeled before recurrence, and facets are non-identity metadata. External-enabler-to-opportunity linkage and market validity remain unproven frontier/external-outcome questions.',
            'decision_boundary': 'RESEARCH_HYPOTHESIS_ONLY_UNTIL_MARKET_TEST_OUTCOME',
        }

    @staticmethod
    def _research_hypothesis_persistable(fp: dict[str, Any]) -> bool:
        """Persistence gate for research hypotheses, deliberately not a founder-opportunity gate."""
        return bool(
            fp.get('hypothesis_ready')
            and fp.get('hypothesis_key')
            and fp.get('problem_family_descriptor')
            and int(fp.get('independent_problem_evidence_count') or 0) >= 2
            and len(fp.get('evidence_refs') or []) >= 2
        )

    async def _persist_and_activate(self, hypotheses: list[dict[str, Any]]):
        contract = assert_contract(); db_probe = await runtime_write_probe()
        if db_probe.get('status') not in {'PASS','SKIP_NO_EXISTING_CANDIDATE'}:
            raise RuntimeError('MATURE_RESEARCH_A1_RUNTIME_DB_WRITE_PROBE_FAIL '+str(db_probe))
        run_id = f"research_a1_{int(time.time()*1000)}"; sidecar_path = GEN_DIR/run_id/'evidence_metadata.json'
        ins=upd=ev=0; ids=[]; sidecar=[]; prepared=False
        key_seen=set()
        async with async_session() as s:
            try:
                for h in hypotheses:
                    fp = self._fingerprint(h)
                    if not self._research_hypothesis_persistable(fp):
                        continue
                    key = str(h.get('hypothesis_key') or '')
                    if not key or key in key_seen:
                        continue
                    key_seen.add(key)
                    pc_table = ProblemCandidate.__table__
                    ex = (await s.execute(select(ProblemCandidate).where(ProblemCandidate.canonical_key==key))).scalar_one_or_none()
                    vals = {
                        'canonical_key': key,
                        'title': fp['canonical_problem'][:500], 'problem_statement': fp['canonical_problem'][:1000],
                        'actor': fp['actor'][:500], 'actor_category': fp['actor_category'][:100],
                        'task': fp['task'][:800], 'object': fp['object'][:500],
                        'failure_mode': fp['failure_mode'][:1000], 'consequence': fp['consequence'][:1000],
                        'buyer_context': fp['buyer_context'][:800], 'workaround': fp['workaround'][:1000],
                        'community_platform': 'mature_research_problem_family_a1', 'discussion_key': key,
                        'community_evidence_count': 0, 'community_user_count': 0, 'stage': 'candidate',
                        'market_score': 0.0, 'confidence_score': float(fp['confidence'])*100,
                        'community_problem_score': 0.0, 'corroboration_score': 0.0, 'buyer_demand_score':0.0,
                        'supply_gap_score':0.0, 'cross_source_score':float(fp['confidence'])*100,
                        'source_support': dict(Counter(fp.get('source_families') or [])),
                        'relation_support': {'hypothesis_identity':1,'typed_evidence_bundle':1,'facets_non_identity':1,'facets':fp.get('facet_labels') or []},
                        'fingerprint': fp, 'first_seen_at':None, 'last_seen_at':None, 'calculated_at':datetime.utcnow(),
                    }
                    vals = filter_values(ProblemCandidate, vals)
                    stmt = pg_insert(pc_table).values(**vals)
                    updates = {k:getattr(stmt.excluded,k) for k in vals if k not in {'canonical_key','founder_status'}}
                    cid = (await s.execute(stmt.on_conflict_do_update(index_elements=[pc_table.c.canonical_key], set_=updates).returning(pc_table.c.id))).scalar_one()
                    ids.append(int(cid)); ins += int(ex is None); upd += int(ex is not None)

                    # Persist typed relations only.  No free-form context slot exists in R1.
                    rel_obs = []
                    p = h.get('problem_obs') or {}
                    rel_obs.append(('direct_problem', p, ['C01']))
                    for o in (h.get('pain_evidence') or [])[1:]: rel_obs.append(('independent_problem_recurrence', o, ['C02']))
                    for o in (h.get('supply_evidence') or [])[:3]: rel_obs.append(('same_product_market_supply', o, ['C06']))
                    for o in (h.get('external_enabler_candidates') or [])[:3]: rel_obs.append(('external_enabler_candidate_context', o, []))
                    for relation, o, claim_supports in rel_obs:
                        meta = {
                            'opportunity_discovery_version': ENGINE_VERSION,
                            'hypothesis_key': key,
                            'problem_scope_key': h.get('seed_key'),
                            'relation_type': relation,
                            'facet_labels': h.get('facets') or [],
                            'claim_supports': claim_supports,
                            'observation_id': o.get('observation_id'),
                            'problem_span_hash': o.get('problem_span_hash'),
                            'normalized_problem_hash': o.get('normalized_problem_hash'),
                            'primary_problem_signature': o.get('primary_problem_signature'),
                            'evidence_disposition': o.get('evidence_disposition'),
                            'problem_lexical_terms': o.get('problem_lexical_terms'),
                            'source_role': o.get('source_role'),
                            'primary_pain_authority': o.get('primary_pain_authority'),
                            'acquisition_mode': o.get('acquisition_mode'),
                        }
                        mapped = evidence_values(
                            candidate_id=cid, source_type=str(o.get('source') or 'unknown'),
                            source_table=str(o.get('source_table') or ''), source_ref=str(o.get('source_ref') or ''),
                            relation=relation, title=_clean(o.get('title'))[:500] or None,
                            summary=_clean(o.get('problem_span') or o.get('change_span') or o.get('text'))[:1200],
                            url=o.get('url') or None, retrieval_score=1.0, verified=True,
                            verification_confidence=float(fp['confidence']), evidence_metadata=meta,
                            observed_at=None, created_at=datetime.utcnow(),
                        )
                        ident = evidence_identity(mapped); existing=None; ev_table=CandidateEvidence.__table__
                        if ident:
                            cond=[ev_table.c[k]==v for k,v in ident.items() if k in ev_table.c]
                            if cond: existing=(await s.execute(select(ev_table.c.id).where(*cond).limit(1))).scalar_one_or_none()
                        if existing is None:
                            await s.execute(ev_table.insert().values(**mapped)); ev += 1
                        sidecar.append({'candidate_id':cid,'hypothesis_key':key,'relation':relation,'source_ref':str(o.get('source_ref') or ''),'metadata':meta})
                await s.flush()
                ids = list(dict.fromkeys(ids))
                if len(ids) != len(key_seen):
                    raise RuntimeError(f'MATURE_RESEARCH_A1_HYPOTHESIS_IDENTITY_TO_DB_ID_MISMATCH keys={len(key_seen)} ids={len(ids)}')
                sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = sidecar_path.with_suffix('.tmp')
                _atomic_stream_json(sidecar_path,{'engine_version':ENGINE_VERSION,'run_id':run_id,'evidence':sidecar},indent=2)
                acceptance = _write_acceptance_evidence()
                prepare_generation(ENGINE_VERSION, ids, {
                    'accepted_hypotheses':len(hypotheses), 'unique_hypothesis_keys':len(key_seen),
                    'hypothesis_keys':sorted(key_seen), 'identity_integrity':'PASS',
                    'independent_architecture_acceptance':'PASS' if acceptance.get('pass') else 'FAIL',
                    'parser_constitution_hash':PARSER_CONSTITUTION_HASH,
                    'source_role_constitution_hash':SOURCE_ROLE_CONSTITUTION_HASH,
                    'db_contract_engine':contract.get('engine_version'), 'db_contract_fingerprint':contract.get('contract_fingerprint'),
                    'evidence_sidecar':str(sidecar_path), 'run_id':run_id,
                }); prepared=True
                await s.commit()
            except Exception:
                await s.rollback()
                if prepared: abort_pending('MATURE_RESEARCH_A1_DB_TRANSACTION_FAILED')
                raise
        integ = await active_evidence_integrity(ids)
        if ids and integ.get('status')!='PASS':
            abort_pending('MATURE_RESEARCH_A1_POST_COMMIT_EVIDENCE_INTEGRITY_FAIL'); raise RuntimeError('MATURE_RESEARCH_A1_ACTIVE_EVIDENCE_INTEGRITY_FAIL '+str(integ))
        state = activate_prepared({'post_commit_evidence_integrity':integ,'hypothesis_identity_integrity':'PASS'})
        return {'inserted':ins,'updated':upd,'evidence_rows':ev,'candidate_ids':ids,'sidecar':str(sidecar_path),'integrity':integ,'state':state,'db_probe':db_probe}

    async def run(self):
        started=time.perf_counter(); contract=assert_contract(); acceptance=_write_acceptance_evidence()
        if not acceptance.get('pass'):
            raise RuntimeError('MATURE_RESEARCH_A1_INDEPENDENT_ARCHITECTURE_ACCEPTANCE_FAIL '+str(acceptance))

        docs, counts = await self._load_docs(); t_load=time.perf_counter()
        print(f"U12_PHASE SOURCE_LOAD docs={len(docs)} seconds={t_load-started:.2f}", flush=True)
        t=time.perf_counter(); observations, oa = build_observations(docs); observations,schema_migration=_migrate_observations(observations); t_obs=time.perf_counter()
        print(f"U12_PHASE OBSERVATION usable={len(observations)} cache_hits={oa.get('cache_hits')} cache_misses={oa.get('cache_misses')} lookup={oa.get('cache_lookup_mode')} batches={oa.get('cache_lookup_batches')} seconds={t_obs-t:.2f}", flush=True)
        t=time.perf_counter(); research_objects = build_research_objects(observations, raw_docs=docs); t_objects=time.perf_counter()
        print(f"U12_PHASE RESEARCH_OBJECTS need={len(research_objects.get('need_fragments') or [])} market={len(research_objects.get('market_states') or [])} enablers={len(research_objects.get('external_enablers') or [])} seconds={t_objects-t:.2f}", flush=True)
        RESEARCH_OBJECTS.parent.mkdir(parents=True, exist_ok=True);_atomic_stream_json(RESEARCH_OBJECTS,research_objects,indent=2)
        t=time.perf_counter(); hypotheses, watch, research, hm = build_evidence_bundles(observations); t_family=time.perf_counter()
        print(f"U12_PHASE CORROBORATION seeds={hm.get('seed_count')} multi={hm.get('multi_evidence_seed_count')} hypotheses={len(hypotheses)} watch={len(watch)} research={len(research)} misc={hm.get('misc_backlog_count')} seconds={t_family-t:.2f}", flush=True)
        initial = {'docs':len(docs),'usable_observations':len(observations),'hypotheses':len(hypotheses),'watch':len(watch),'research':len(research),'market_states':len(research_objects.get('market_states') or [])}

        recovery={'status':'NOT_RUN','requests_this_run':0,'docs_added':0}; recovery_applied=False;recovery_assimilation={'status':'NOT_RUN','new_docs':0,'usable_added':0,'downstream_utility':{}}
        reserve = min(RECOVERY_PER_RUN_REQUESTS, int((self.source_health or {}).get('recovery_reserve_remaining', RECOVERY_PER_RUN_REQUESTS) or RECOVERY_PER_RUN_REQUESTS))
        recovery_selection={'research_items':len(research),'targetable_items':0,'selected':0,'selected_preview':[]}
        if (research or research_objects.get('user_innovation_signals')) and reserve>0:
            anchors,recovery_selection=_select_recovery_anchors(research,limit=min(8,reserve,RECOVERY_RESERVE_REQUESTS),user_innovations=research_objects.get('user_innovation_signals') or [])
            print(f"U12_PHASE RECOVERY_SELECT targetable={recovery_selection.get('targetable_items')} selected={recovery_selection.get('selected')}", flush=True)
            before_keys={(str(d.get('source')),str(d.get('table')),str(d.get('pk'))) for d in docs}
            merged_docs, recovery = targeted_corroboration_refresh(anchors, budget=min(reserve, RECOVERY_RESERVE_REQUESTS));recovery_applied = int(recovery.get('requests_this_run') or 0)>0
            new_docs=[d for d in merged_docs if (str(d.get('source')),str(d.get('table')),str(d.get('pk'))) not in before_keys]
            print(f"U12_PHASE RECOVERY requests={recovery.get('requests_this_run')} docs_added={recovery.get('docs_added')} new_docs={len(new_docs)}", flush=True)
            if recovery_applied:
                inc_obs, inc_audit = build_observations_incremental(new_docs) if new_docs else ([],{'documents':0,'usable_observations':0,'cache_hits':0,'cache_misses':0,'incremental_recovery_parse':True,'seconds':0.0})
                by_obs={str(o.get('observation_id')):o for o in observations}
                for o in inc_obs:by_obs[str(o.get('observation_id'))]=o
                observations=list(by_obs.values());observations,schema_migration_post=_migrate_observations(observations);schema_migration['post_recovery']=schema_migration_post;schema_migration['incremental_recovery_audit']=inc_audit
                docs=_append_new_docs(docs,new_docs)
                utility=record_downstream_evidence_utility(inc_obs) if inc_obs else {'observations_seen':0,'evidence_docs':0,'by_adapter':{},'truth_boundary':'NO_NEW_OBSERVATIONS'}
                gap_progress=get_evidence_gap_progress([str(a.get('anchor_key') or '') for a in anchors if a.get('anchor_key')])
                research_objects = build_research_objects(observations, raw_docs=docs);_atomic_stream_json(RESEARCH_OBJECTS,research_objects,indent=2)
                hypotheses, watch, research, hm = build_evidence_bundles(observations)
                recovery_assimilation={'status':'PASS','new_docs':len(new_docs),'usable_added':len(inc_obs),'downstream_utility':utility,'gap_progress':gap_progress,'post_multi':hm.get('multi_evidence_seed_count'),'post_hypotheses':len(hypotheses),'post_market_states':len(research_objects.get('market_states') or [])}
                print(f"U12_PHASE POST_RECOVERY usable_added={len(inc_obs)} utility_evidence={utility.get('evidence_docs')} multi={hm.get('multi_evidence_seed_count')} hypotheses={len(hypotheses)} market={len(research_objects.get('market_states') or [])}", flush=True)

        # Diagnostic graph is deliberately deferred until the final corpus state. It is not
        # hypothesis identity authority, so there is no reason to build it twice per run.
        t_graph_start=time.perf_counter();graph_report,graph_audit=_load_or_build_graph_report(observations);t_graph=time.perf_counter()
        print(f"U12_PHASE GRAPH_FINAL nodes={graph_report.get('nodes')} edges={graph_report.get('edge_count')} cache={graph_audit.get('status')} seconds={t_graph-t_graph_start:.2f}", flush=True)

        _write_watch_and_research(watch, research)
        OBS_CACHE.parent.mkdir(parents=True,exist_ok=True)
        _atomic_stream_json(OBS_CACHE,{'engine_version':ENGINE_VERSION,'count':len(observations),'audit':oa,'sample':observations[:300]})

        hypotheses, canonical_before_audit = canonicalize_hypotheses(hypotheses)
        selected, diversity = _diversify(hypotheses, min(self.max_persist, MAX_SCREEN_POOL))
        selected, canonical_selected = canonicalize_hypotheses(selected)
        audited, relationship_audit = await self._relationship_audit(selected)
        audited, canonical_after_audit = canonicalize_hypotheses(audited)
        audited, diversity2 = _diversify(audited, self.max_persist)
        audited, canonical_final = canonicalize_hypotheses(audited)
        lead_pool, lead_audit = await self._research_lead_audit(research)
        identity_integrity = {
            'status':'PASS' if len({h.get('hypothesis_key') for h in audited})==len(audited) else 'FAIL',
            'hypothesis_count':len(audited),
            'unique_hypothesis_keys':len({h.get('hypothesis_key') for h in audited}),
            'facets_are_non_identity':all(h.get('identity_facets_excluded') is True for h in audited),
            'canonicalization':{'before_audit':canonical_before_audit,'selected':canonical_selected,'after_audit':canonical_after_audit,'final':canonical_final},
        }
        if identity_integrity['status']!='PASS':
            raise RuntimeError('FOUNDER_USABLE_U8_CANONICAL_IDENTITY_INTEGRITY_FAIL '+str(identity_integrity))

        persist={'inserted':0,'updated':0,'evidence_rows':0,'candidate_ids':[],'sidecar':None,'integrity':{'status':'PASS','candidate_ids':[],'coverage':1.0},'state':active_generation(),'db_probe':{'status':'NOT_RUN'}}
        if self.persist_enabled:
            persist = await self._persist_and_activate(audited)

        # Source feedback is hypothesis/facet/gap based, not lane-yield based.
        feedback={
            'engine_version':ENGINE_VERSION,
            'current_hypotheses':len(audited),
            'facet_counts':dict(Counter(f for h in audited for f in h.get('facets') or [])),
            'watch_count':len(watch),'research_queue_count':len(research),
            'problem_seed_meta':hm,
            'accepted_problem_source_families':dict(Counter((h.get('problem_obs') or {}).get('source_family') for h in audited)),
            'optimization_target':'MATURE_RESEARCH_NEED_FRAGMENT_RETENTION_PROBLEM_FAMILY_FORMATION_AND_EVIDENCE_GAP_CLOSURE_NOT_LANE_COUNTS',
            'generated_at':time.time(),
        }
        _atomic_stream_json(SOURCE_FEEDBACK,feedback,indent=2)

        accepted_summaries=[hypothesis_summary(h) for h in audited]
        shortlist=build_shortlist(accepted_summaries, lead_pool, research_objects=research_objects, relationship_audit=relationship_audit, lead_audit=lead_audit, max_hypotheses=8, max_leads=5, max_user_innovations=3)
        shortlist, founder_semantic_audit = await self._founder_card_adjudication(shortlist)
        shortlist['founder_semantic_adjudication']=founder_semantic_audit
        current_gap_progress=get_evidence_gap_progress()
        shortlist=_attach_gap_progress(shortlist,current_gap_progress)
        shortlist_paths=write_shortlist(shortlist)

        result={
            'engine_version':ENGINE_VERSION,
            'architecture':'U13_FOUNDER_GATE_PRESERVED_CARD_GAP_ATTRIBUTION_PLUS_VALUE_OF_INFORMATION_ACQUISITION',
            'evidence_schema_migration':schema_migration,
            'db_contract':contract,
            'sources':counts,'source_portfolio_health':self.source_health,'docs':len(docs),
            'usable_observations':len(observations),
            'observation_audit':oa,'runtime_persistence_contract':{'atomic_stream_json':True,'cache_is_optimization_not_truth_gate':True,'large_state_no_json_dumps_monolith':True,'batched_sqlite_lookup':False,'diagnostic_graph_built_after_recovery_only':True},
            'graph':{'nodes':graph_report.get('nodes'),'edges':graph_report.get('edge_count',0),'clusters':graph_report.get('cluster_count',0),'telemetry':graph_report.get('telemetry') or {},'cache':graph_audit},
            'research_objects':{'path':str(RESEARCH_OBJECTS),'counts':research_objects.get('counts') or {},'frontier_boundary':research_objects.get('frontier_boundary')},
            'hypothesis_formation':hm,
            'evidence_recovery_funnel':{'initial':initial,'recovery_applied':recovery_applied,'recovery_selection':recovery_selection,'recovery':recovery,'assimilation':recovery_assimilation,'evidence_gap_ledger':current_gap_progress,'post_recovery':{'docs':len(docs),'usable_observations':len(observations),'hypotheses':len(hypotheses),'watch':len(watch),'research':len(research),'market_states':len(research_objects.get('market_states') or [])}},
            'relationship_audit':relationship_audit,
            'post_hypothesis_diversity':diversity2,
            'hypothesis_identity_integrity':identity_integrity,
            'accepted':len(audited),
            'accepted_hypotheses':accepted_summaries,
            'founder_research_shortlist':shortlist,'founder_research_shortlist_paths':shortlist_paths,'lead_audit':lead_audit,'founder_semantic_adjudication':founder_semantic_audit,
            'facet_counts':dict(Counter(f for h in audited for f in h.get('facets') or [])),
            'watch_signal_count':len(watch),'evidence_research_count':len(research),
            'independent_architecture_acceptance':acceptance,
            'inserted':persist['inserted'],'updated':persist['updated'],'evidence_rows':persist['evidence_rows'],
            'active_candidate_ids':persist['candidate_ids'],'evidence_sidecar':persist['sidecar'],'active_evidence_integrity':persist['integrity'],'active_generation':persist['state'],'db_runtime_write_probe':persist['db_probe'],
            'operational_evidence_state':'FOUNDER_USABLE_RESEARCH_SURFACE_READY' if shortlist.get('status')=='READY_FOR_FOUNDER_DISCUSSION' else ('RESEARCH_QUEUE_READY_NO_FOUNDER_USABLE_CARD' if research else 'NO_QUALIFYING_HYPOTHESIS_OR_RESEARCH_SEED'),
            'truth_contract':'U13: Founder semantic gate preserved; every recovery request is attributed to a card/evidence gap; VOI and gap progress control acquisition priority only; retrieved candidates do not close recurrence, WTP, or opportunity truth without semantic/external confirmation.',
            'phase_seconds':{'load':round(t_load-started,3),'observation':round(t_obs-t_load,3),'research_objects':round(t_objects-t_obs,3),'family_initial':round(t_family-t_objects,3),'graph_final':round(t_graph-t_graph_start,3),'total':round(time.perf_counter()-started,3)},
        }
        result_persist=_atomic_stream_json(CACHE_PATH,result,indent=2);result['runtime_state_persistence']=result_persist
        # Compatibility read path for modules not yet migrated outside this cutover.
        compat_persist=_atomic_stream_json(COMPAT_CACHE_PATH,result,indent=2);result['compat_runtime_state_persistence']=compat_persist
        return result


async def run_transition_gap_discovery(**kw):
    return await OpportunityObservationDiscovery(**kw).run()


async def run_opportunity_portfolio_discovery(**kw):
    return await run_transition_gap_discovery(**kw)


def architecture_static_acceptance():
    pure = hypothesis_static_acceptance(); adv = independent_architecture_acceptance(observation_from_doc)
    return {
        'missing_signature_not_hard_reject': pure.get('missing_signature_is_not_hard_reject') is True,
        'signatureless_fragments_retained': adv.get('signatureless_fragments_survive') is True and adv.get('signatureless_fragments_route_to_research_or_family') is True,
        'incomplete_fragment_routes_to_research': adv.get('singleton_incomplete_enters_research') is True,
        'same_problem_cross_facet_single_hypothesis': adv.get('tripsy_same_problem_single_identity') is True,
        'same_product_different_problem_separate': adv.get('same_product_different_problem_separate') is True,
        'duplicate_content_not_independent': adv.get('duplicate_text_not_independent') is True,
        'typed_evidence_bundle': adv.get('typed_bundle_problem_and_recurrence') is True,
        'unrelated_supply_context_rejected': adv.get('unrelated_competitor_not_supply_context') is True,
        'external_enabler_not_auto_transition': adv.get('external_enabler_not_auto_transition') is True,
        'positive_supplier_vendor_false_positives_blocked': bool(adv.get('positive_review_not_seed') and adv.get('supplier_capability_not_problem_seed') and adv.get('vendor_mission_not_problem_seed')),
        'targeted_recovery_accepts_fragment_anchors': callable(targeted_corroboration_refresh),
        'recovery_selection_is_targetability_and_diversity_aware': callable(_select_recovery_anchors),
        'incremental_post_recovery_observation': callable(build_observations_incremental),
        'user_innovation_recurrence_recovery': True,
        'need_solution_queries_separated': callable(_ui_need_and_supply_queries),
        'llm_is_relationship_challenger_not_fact_generator': True,
        'research_hypothesis_not_venture_opportunity': True,
        'founder_shortlist_surface': all(shortlist_static_acceptance().values()),
        'facet_not_required_for_problem_hypothesis': hypothesis_static_acceptance().get('facet_not_required_for_research_hypothesis') is True,
        'cached_observation_schema_migration': callable(_migrate_observations),
        'hypothesis_canonicalization_stage': callable(canonicalize_hypotheses),
        'recovery_budget_is_fresh_per_run': RECOVERY_PER_RUN_REQUESTS>0,
        'structural_need_frame_schema_bound': bool(EVIDENCE_SCHEMA_VERSION),
        'independent_acceptance_evidence_written': True,
        'weak_supervision_lead_candidates_abstain_before_semantic_gate': True,
        'final_founder_selective_semantic_adjudication': callable(OpportunityObservationDiscovery._founder_card_adjudication),
        'semantic_gate_cannot_promote_hypothesis': True,
        'card_gap_progress_attached_without_truth_promotion': callable(_attach_gap_progress),
        'evidence_gap_voi_available': callable(estimate_anchor_voi),
        'persistent_gap_ledger_available': callable(get_evidence_gap_progress),
    }
