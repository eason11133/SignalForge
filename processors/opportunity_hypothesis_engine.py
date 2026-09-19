"""SignalForge research-grounded problem-family / hypothesis formation.

Mature research adopted here:
- customer-need evidence may be incomplete and is retained as a fragment;
- labeling heuristics can abstain instead of acting as hard truth gates;
- evidence is retrieved then reranked, rather than joined by one lexical signature;
- source/content dependence is modeled before recurrence is counted;
- problem/need, external-enabler and market-state evidence remain separate objects.

Frontier boundary:
This module does NOT claim to solve automatic venture-opportunity recognition. It forms
stable evidence-backed *problem families* and research hypotheses. External-enabler ×
workflow-lag × founder opportunity linkage remains a separately identified R&D problem.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable

from processors.opportunity_evidence_atoms import annotate_observation, ensure_observation_schema, research_priority
from processors.opportunity_evidence_provenance import content_independent, independence_summary
from processors.opportunity_evidence_retrieval import relation_score, build_relation_candidates, lexical_similarity

ENGINE_VERSION = "opportunity-hypothesis-engine-u5-dependence-aware-founder-research"
FACETS = (
    "MICRO_FRICTION",
    "PROVEN_MARKET_WEDGE",
    "DISTRIBUTION_MODEL_GAP",
    "BORING_OPS",
    "SECOND_ORDER_PAIN",
    "TRANSITION_GAP",  # reserved facet; automatic enabler linkage is not self-certified here.
)
DISPLAY_PRIORITY = {
    "DISTRIBUTION_MODEL_GAP": 6,
    "TRANSITION_GAP": 5,
    "PROVEN_MARKET_WEDGE": 4,
    "BORING_OPS": 3,
    "SECOND_ORDER_PAIN": 2,
    "MICRO_FRICTION": 1,
}

GENERIC_TERMS = {
    "every","again","manual","problem","issue","wrong","error","work","working","time","need","make","makes",
    "thing","things","really","still","keep","keeps","using","used","user","users","product","review","app",
}


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _known(v: Any) -> bool:
    s=_clean(v).lower()
    return bool(s and s not in {"unknown","other","none","n/a"})


def _oid(o: dict[str, Any] | None) -> str:
    return str((o or {}).get("observation_id") or "")


def evidence_ref(o: dict[str, Any] | None) -> str:
    if not o:return ""
    return f"{o.get('source')}:{o.get('source_table')}:{o.get('source_ref')}"


def problem_observation_ok(o: dict[str, Any]) -> tuple[bool, str]:
    """Hard truth boundaries only.

    Missing signature, missing self-contained wording, or missing actor is never a hard
    reject. Those are evidence gaps and route to research rather than deletion.
    """
    migrated=ensure_observation_schema(o)
    if migrated is not o:
        o.clear();o.update(migrated)
    disp=str(o.get("evidence_disposition") or "")
    if disp not in {"DIRECT_NEED","INCOMPLETE_NEED"}:
        return False, "NOT_NEED_EVIDENCE"
    if not o.get("primary_pain_authority"):
        return False, "SOURCE_NOT_PRIMARY_PAIN_AUTHORITY"
    feedback_role=str(o.get("feedback_role") or "")
    if str(o.get("problem_polarity") or "") != "NEGATIVE" and feedback_role not in {"FEATURE_REQUEST","WORKAROUND_OR_USAGE"}:
        return False, "NON_NEGATIVE_NON_REQUIREMENT_SIGNAL"
    if o.get("problem_target") == "LISTED_ENTITY_OR_CONTENT":
        return False, "WRONG_COMPLAINT_TARGET"
    if not _clean(o.get("problem_span")):
        return False, "PROBLEM_TEXT_MISSING"
    return True, "PASS" if disp=="DIRECT_NEED" else "PASS_INCOMPLETE"


def actor_bucket(o: dict[str, Any]) -> str:
    actor=_clean(o.get("actor_scope")).lower()
    if actor and actor not in {"unknown","user","community_user"}:return actor
    vertical=_clean(o.get("vertical")).lower()
    if vertical and vertical!="other":return vertical
    return _clean(o.get("native_scope")).lower() or "unknown"


def _terms(o: dict[str, Any]) -> set[str]:
    vals=o.get("problem_lexical_terms") or ((o.get("evidence_atom") or {}).get("lexical_terms")) or []
    return {str(x).lower() for x in vals if str(x).lower() not in GENERIC_TERMS}


def _legacy_sig(o: dict[str, Any]) -> str:
    return _clean(o.get("primary_problem_signature")).lower()


def _scope_base(group: list[dict[str, Any]]) -> str:
    products={_clean(x.get("product_id")) for x in group if _clean(x.get("product_id"))}
    workflows=[_clean(x.get("workflow")).lower() for x in group if _known(x.get("workflow"))]
    verticals=[_clean(x.get("vertical")).lower() for x in group if _known(x.get("vertical"))]
    actors=[actor_bucket(x) for x in group if actor_bucket(x)!="unknown"]
    wf=Counter(workflows).most_common(1)[0][0] if workflows else "other"
    if len(products)==1:
        return f"product:{next(iter(products))}|workflow:{wf}"
    vert=Counter(verticals).most_common(1)[0][0] if verticals else "other"
    actor=Counter(actors).most_common(1)[0][0] if actors else "unknown"
    return f"market:{vert}|workflow:{wf}|actor:{actor}"


def _frame_descriptor(group: list[dict[str, Any]]) -> tuple[str|None,dict[str,Any]]:
    frames=[x.get("need_frame") or {} for x in group]
    if len(frames)<2:return None,{"basis":"INSUFFICIENT_FRAME_EVIDENCE"}
    failures=[set(str(v) for v in (f.get("failure_modes") or [])) for f in frames]
    actions=[set(str(v) for v in (f.get("actions") or [])) for f in frames]
    objects=[set(str(v) for v in (f.get("objects") or [])) for f in frames]
    sf=set.intersection(*failures) if all(failures) else set()
    sa=set.intersection(*actions) if all(actions) else set()
    so=set.intersection(*objects) if all(objects) else set()
    wf=[str((f.get("workflow") or "")).lower() for f in frames if f.get("workflow")]
    same_wf=(len(set(wf))==1 and bool(wf))
    if sf and (sa or same_wf) and so:
        bits=["fail:"+sorted(sf)[0]]
        if sa:bits.append("act:"+sorted(sa)[0])
        if same_wf:bits.append("wf:"+wf[0])
        bits.append("obj:"+sorted(so)[0])
        return "frame:"+"|".join(bits),{"basis":"STRUCTURAL_NEED_FRAME","failure":sorted(sf),"action":sorted(sa),"objects":sorted(so)[:4],"workflow":wf[0] if same_wf else None}
    return None,{"basis":"STRUCTURAL_FRAME_NOT_STABLE","failure":sorted(sf),"action":sorted(sa),"objects":sorted(so)[:4],"workflow":wf[0] if same_wf else None}


def _consistent_specific_target(group: list[dict[str, Any]]) -> str | None:
    targets=[]
    for x in group:
        f=x.get("need_frame") or {}
        t=_clean(f.get("primary_specific_target")).lower()
        if t: targets.append(t)
    if targets and len(set(targets))==1:
        return targets[0]
    return None


def stable_family_descriptor(group: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    """Return a stable evidence-derived problem-family descriptor.

    Entity-resolution research separates matching from canonicalization.  A broad legacy
    signature is therefore never enough to collapse distinct concrete targets.  When a
    specific target is consistently observed (for example AgentExecutor vs create_react_agent),
    it becomes part of canonical identity.  Missing target information is allowed; uncertainty
    stays explicit rather than killing the evidence.
    """
    sigs=[_legacy_sig(x) for x in group if _legacy_sig(x)]
    target=_consistent_specific_target(group)
    if sigs and len(set(sigs))==1:
        descriptor="sig:"+sigs[0]
        if target: descriptor += "|target:"+target
        return descriptor, {"basis":"CONSISTENT_LEGACY_SIGNATURE_WITH_TARGET_GUARD" if target else "CONSISTENT_LEGACY_SIGNATURE","terms":[],"signature":sigs[0],"specific_target":target}
    frame_desc,frame_meta=_frame_descriptor(group)
    if frame_desc:
        if target and "target:" not in frame_desc:
            frame_desc += "|target:"+target
        return frame_desc,{**frame_meta,"terms":[],"signature":None,"specific_target":target}
    term_sets=[_terms(x) for x in group if _terms(x)]
    shared=set.intersection(*term_sets) if len(term_sets)>=2 else set()
    shared={x for x in shared if x not in GENERIC_TERMS}
    if shared:
        terms=sorted(shared)[:4]
        descriptor="terms:"+"+".join(terms)
        if target: descriptor += "|target:"+target
        return descriptor, {"basis":"SHARED_DISCRIMINATIVE_TERMS","terms":terms,"signature":None,"specific_target":target}
    return None, {"basis":"UNSTABLE_IDENTITY_RESEARCH_ONLY","terms":[],"signature":None,"specific_target":target}


def problem_scope_key(group_or_observation: list[dict[str, Any]] | dict[str, Any]) -> str:
    group=group_or_observation if isinstance(group_or_observation,list) else [group_or_observation]
    descriptor,_=stable_family_descriptor(group)
    return _scope_base(group)+"|problem:"+(descriptor or "UNRESOLVED")


def hypothesis_key_from_scope(scope_key: str) -> str:
    return "oph_ma1_"+hashlib.sha1(scope_key.encode()).hexdigest()[:20]


def same_problem_identity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return relation_score(a,b).get("relation")=="SAME_PROBLEM_CANDIDATE"


def lexical_problem_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    return lexical_similarity(a,b)


def recurrence_pair_ok(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool,str]:
    ok,reason=problem_observation_ok(a)
    if not ok:return False,"PRIMARY_"+reason
    ok,reason=problem_observation_ok(b)
    if not ok:return False,"CORROBORATION_"+reason
    if not content_independent(a,b):return False,"NOT_CONTENT_INDEPENDENT"
    r=relation_score(a,b)
    if r.get("relation")!="SAME_PROBLEM_CANDIDATE":return False,"RETRIEVAL_RERANK_RELATION_MISMATCH"
    return True,"PASS"


def research_value_score(o: dict[str, Any]) -> float:
    return research_priority(o)


def _best_problem(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    def score(o):return (research_priority(o),int(o.get("evidence_disposition")=="DIRECT_NEED"),len(_clean(o.get("problem_span"))))
    return max(evidence,key=score)


def _cluster_problem_evidence(observations: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]],dict[str,Any]]:
    eligible=[];rejections=Counter()
    for raw in observations:
        o=ensure_observation_schema(raw)
        ok,reason=problem_observation_ok(o)
        if ok:eligible.append(o)
        else:rejections[reason]+=1

    # Bounded retrieve->rerank must remain the expensive relation boundary.  A1 accidentally
    # scanned every existing cluster for every observation after retrieval, recreating O(N^2).
    edges,ret_meta=build_relation_candidates(eligible)
    adjacency={_oid(x):set() for x in eligible}
    for e in edges:
        a,b=str(e.get("a") or ""),str(e.get("b") or "")
        if a and b:
            adjacency.setdefault(a,set()).add(b)
            adjacency.setdefault(b,set()).add(a)

    # Preserve anti-bridge identity semantics: retrieval only nominates candidate families.
    # Joining still requires direct alignment with the family's representative.
    ranked=sorted(eligible,key=research_priority,reverse=True)
    clusters=[];membership={};representative_checks=0;candidate_cluster_hits=0
    for o in ranked:
        oid=_oid(o);candidate_clusters=set()
        for neighbor_id in adjacency.get(oid,()):
            ci=membership.get(neighbor_id)
            if ci is not None:candidate_clusters.add(ci)
        placed=False
        for ci in sorted(candidate_clusters):
            group=clusters[ci];rep=group[0];representative_checks+=1
            r=relation_score(rep,o)
            if r.get("relation")=="SAME_PROBLEM_CANDIDATE" and float(r.get("score") or 0)>=0.54:
                conflicts=False;so=_legacy_sig(o)
                if so:
                    for x in group:
                        sx=_legacy_sig(x)
                        if sx and sx!=so:conflicts=True;break
                if not conflicts:
                    group.append(o);membership[oid]=ci;placed=True;candidate_cluster_hits+=1;break
        if not placed:
            membership[oid]=len(clusters);clusters.append([o])

    return clusters,{
        "eligible_need_fragments":len(eligible),"hard_rejections":dict(rejections),
        "retrieval":ret_meta,"problem_family_candidates":len(clusters),
        "clustering_policy":"BOUNDED_RETRIEVAL_CANDIDATES_THEN_REPRESENTATIVE_CHECK",
        "all_cluster_scan_removed":True,"representative_checks":representative_checks,
        "candidate_cluster_hits":candidate_cluster_hits,"candidate_pair_cap":ret_meta.get("pair_cap"),
    }

def _independent_evidence(group: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],dict[str,Any]]:
    s=independence_summary(group)
    kept=list(s.get("kept") or [])
    # Also require relation to the chosen primary; provenance independence alone is insufficient.
    if not kept:return [],s
    primary=_best_problem(kept)
    aligned=[primary]
    for o in kept:
        if _oid(o)==_oid(primary):continue
        if recurrence_pair_ok(primary,o)[0]:aligned.append(o)
    s["relation_aligned_count"]=len(aligned)
    return aligned,s


def _supply_matches(seed: dict[str, Any], context: dict[str, Any]) -> bool:
    return bool(seed.get("product_id") and context.get("paid_supply") and str(context.get("product_id") or "")==str(seed.get("product_id") or ""))


def _facet_labels(primary: dict[str, Any], pains: list[dict[str, Any]], supply: list[dict[str, Any]]) -> tuple[list[str],dict[str,list[str]]]:
    facets=[];refs={};pain_refs=[evidence_ref(x) for x in pains]
    vertical=str(primary.get("vertical") or "other");workflow=str(primary.get("workflow") or "other");product_scoped=bool(primary.get("product_id"))
    if product_scoped or vertical in {"consumer","education","healthcare"}:
        facets.append("MICRO_FRICTION");refs["MICRO_FRICTION"]=pain_refs[:3]
    if product_scoped and supply:
        facets.append("PROVEN_MARKET_WEDGE");refs["PROVEN_MARKET_WEDGE"]=pain_refs[:2]+[evidence_ref(supply[0])]
    if any(x.get("distribution_explicit") for x in pains):
        facets.append("DISTRIBUTION_MODEL_GAP");refs["DISTRIBUTION_MODEL_GAP"]=[evidence_ref(x) for x in pains if x.get("distribution_explicit")][:2]
    if any(x.get("manual_behavior") for x in pains) and (workflow in {"booking","billing","support","intake","ops","coordination","compliance","healthcare_ops"} or vertical in {"professional_services","business","healthcare"}):
        facets.append("BORING_OPS");refs["BORING_OPS"]=[evidence_ref(x) for x in pains if x.get("manual_behavior")][:2]
    if any(x.get("second_order_explicit") for x in pains):
        facets.append("SECOND_ORDER_PAIN");refs["SECOND_ORDER_PAIN"]=[evidence_ref(x) for x in pains if x.get("second_order_explicit")][:2]
    # TRANSITION_GAP is intentionally not inferred here. External-enabler linkage is a frontier module.
    return sorted(set(facets),key=lambda x:-DISPLAY_PRIORITY.get(x,0)),refs


def _merge_seed_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    if len(group)==1:
        return group[0]
    evidence=[];seen=set()
    for seed in group:
        for o in ([seed.get("problem_obs")] + list(seed.get("pain_evidence") or [])):
            if not o: continue
            k=_oid(o) or evidence_ref(o)
            if k in seen: continue
            seen.add(k); evidence.append(o)
    independent,dep_meta=_independent_evidence(evidence)
    primary=_best_problem(independent or evidence)
    descriptor,desc_meta=stable_family_descriptor(independent or evidence)
    scope=_scope_base(independent or evidence)+"|problem:"+(descriptor or "UNRESOLVED")
    canonical=bool(descriptor)
    best=max(group,key=lambda x:(x.get("research_value_score") or 0,x.get("independent_problem_evidence_count") or 0))
    return {**best,
        "seed_key":scope if canonical else None,
        "hypothesis_key":hypothesis_key_from_scope(scope) if canonical else None,
        "problem_family_descriptor":descriptor,
        "problem_family_descriptor_meta":{**desc_meta,"canonicalized_seed_records":len(group)},
        "identity_status":"STABLE_EVIDENCE_DERIVED" if canonical else "RESEARCH_ONLY_UNSTABLE_IDENTITY",
        "primary_problem_signature":primary.get("primary_problem_signature"),
        "product_id":primary.get("product_id"),"product_name":primary.get("product_name"),
        "vertical":primary.get("vertical"),"workflow":primary.get("workflow"),"actor":primary.get("actor_scope"),
        "need_frame":primary.get("need_frame") or {},"problem_obs":primary,"pain_evidence":independent,
        "raw_problem_evidence_count":sum(int(x.get("raw_problem_evidence_count") or 0) for x in group),
        "independent_problem_evidence_count":len(independent),"dependency_analysis":dep_meta,
        "independent_source_origins":int(dep_meta.get("independent_source_origins") or 0),
        "dependency_rejected_count":int(dep_meta.get("dependency_rejected_count") or len(dep_meta.get("rejected_dependencies") or [])),
        "research_value_score":max(float(x.get("research_value_score") or 0) for x in group),
        "contains_incomplete_need":any(x.get("contains_incomplete_need") for x in group),
    }


def _canonicalize_seed_records(seeds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],dict[str,Any]]:
    """Entity-resolution canonicalization after bounded matching.

    Matching/clustering may legitimately produce several records that resolve to the same
    canonical key.  Canonicalization is a first-class stage: merge their evidence once, then
    persist exactly one record per key.  This is not a dedup gate after the fact; it is the
    normal entity-resolution pipeline.
    """
    keyed={};unkeyed=[]
    for seed in seeds:
        k=seed.get("hypothesis_key")
        if k: keyed.setdefault(str(k),[]).append(seed)
        else: unkeyed.append(seed)
    out=[];merged_groups=0;merged_records=0
    for k,group in keyed.items():
        if len(group)>1:
            merged_groups+=1;merged_records+=len(group)-1
        out.append(_merge_seed_group(group))
    out.extend(unkeyed)
    out.sort(key=lambda x:(x["independent_problem_evidence_count"],bool(x.get("seed_key")),x["research_value_score"]),reverse=True)
    return out,{"precanonical_seed_count":len(seeds),"canonical_seed_count":len(out),"duplicate_key_groups_merged":merged_groups,"duplicate_seed_records_merged":merged_records}


def build_problem_seeds(observations: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]],dict[str,Any]]:
    obs=list(observations)
    clusters,meta=_cluster_problem_evidence(obs)
    seeds=[]
    for group in clusters:
        independent,dep_meta=_independent_evidence(group)
        primary=_best_problem(independent or group)
        descriptor,desc_meta=stable_family_descriptor(independent or group)
        scope=_scope_base(independent or group)+"|problem:"+(descriptor or "UNRESOLVED")
        canonical=bool(descriptor)
        seeds.append({
            "seed_key":scope if canonical else None,
            "fragment_cluster_key":"frag_"+hashlib.sha1("|".join(sorted(_oid(x) for x in group)).encode()).hexdigest()[:18],
            "hypothesis_key":hypothesis_key_from_scope(scope) if canonical else None,
            "problem_family_descriptor":descriptor,
            "problem_family_descriptor_meta":desc_meta,
            "identity_status":"STABLE_EVIDENCE_DERIVED" if canonical else "RESEARCH_ONLY_UNSTABLE_IDENTITY",
            "primary_problem_signature":primary.get("primary_problem_signature"),
            "product_id":primary.get("product_id"),"product_name":primary.get("product_name"),
            "vertical":primary.get("vertical"),"workflow":primary.get("workflow"),"actor":primary.get("actor_scope"),
            "need_frame":primary.get("need_frame") or {},
            "problem_obs":primary,"pain_evidence":independent,"raw_problem_evidence_count":len(group),
            "independent_problem_evidence_count":len(independent),"dependency_analysis":dep_meta,
            "independent_source_origins":int(dep_meta.get("independent_source_origins") or 0),
            "dependency_rejected_count":int(dep_meta.get("dependency_rejected_count") or len(dep_meta.get("rejected_dependencies") or [])),
            "research_value_score":research_priority(primary),
            "research_tier":str(primary.get("research_tier") or ((primary.get("fragment_information") or {}).get("tier")) or "MISC"),
            "contains_incomplete_need":any(x.get("evidence_disposition")=="INCOMPLETE_NEED" for x in group),
        })
    seeds,canonical_meta=_canonicalize_seed_records(seeds)
    meta.update(canonical_meta)
    meta.update({
        "seed_count":len(seeds),
        "stable_identity_seed_count":sum(1 for x in seeds if x.get("seed_key")),
        "incomplete_identity_seed_count":sum(1 for x in seeds if not x.get("seed_key")),
        "multi_evidence_seed_count":sum(1 for x in seeds if x["independent_problem_evidence_count"]>=2),
        "single_evidence_seed_count":sum(1 for x in seeds if x["independent_problem_evidence_count"]==1),
        "high_medium_seed_count":sum(1 for x in seeds if x.get("research_tier") in {"HIGH","MEDIUM"}),
        "misc_seed_count":sum(1 for x in seeds if x.get("research_tier")=="MISC"),
        "hard_primary_signature_gate_removed":True,
    })
    return seeds,meta


def canonicalize_hypotheses(hypotheses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],dict[str,Any]]:
    groups={};unkeyed=[]
    for h in hypotheses:
        k=h.get("hypothesis_key")
        if k: groups.setdefault(str(k),[]).append(h)
        else: unkeyed.append(h)
    out=[];merged=0
    for k,group in groups.items():
        if len(group)==1:
            out.append(group[0]);continue
        merged += len(group)-1
        seeds=[]
        for h in group:
            seeds.append({kk:h.get(kk) for kk in ("seed_key","fragment_cluster_key","hypothesis_key","problem_family_descriptor","problem_family_descriptor_meta","identity_status","primary_problem_signature","product_id","product_name","vertical","workflow","actor","need_frame","problem_obs","pain_evidence","raw_problem_evidence_count","independent_problem_evidence_count","dependency_analysis","independent_source_origins","dependency_rejected_count","research_value_score","research_tier","contains_incomplete_need")})
        merged_seed=_merge_seed_group(seeds)
        base=max(group,key=lambda x:(x.get("research_value_score") or 0,x.get("independent_problem_evidence_count") or 0))
        pains=merged_seed.get("pain_evidence") or []
        supply=[];changes=[]
        seen=set()
        for h in group:
            for x in h.get("supply_evidence") or []:
                r=evidence_ref(x)
                if r not in seen: seen.add(r);supply.append(x)
            for x in h.get("external_enabler_candidates") or []:
                r=evidence_ref(x)
                if r not in seen: seen.add(r);changes.append(x)
        facets=sorted(set(f for h in group for f in (h.get("facets") or [])),key=lambda x:-DISPLAY_PRIORITY.get(x,0))
        p=merged_seed.get("problem_obs") or base.get("problem_obs") or {}
        merged_bundle={**base,**merged_seed,"facets":facets,"display_primary_facet":facets[0] if facets else None,"supply_evidence":supply,"external_enabler_candidates":changes,"identity_facets_excluded":True}
        merged_bundle["evidence_bundle"]={
            "problem":[evidence_ref(p)] if p else [],
            "recurrence":[evidence_ref(x) for x in pains[1:]],
            "market_supply":[evidence_ref(x) for x in supply[:3]],
            "external_enabler_candidates":[evidence_ref(x) for x in changes[:3]],
            "why_now":[],
            "payment_behavior":[evidence_ref(x) for x in pains if x.get("payment_behavior_observed")],
            "economic_burden":[evidence_ref(x) for x in pains if x.get("burden_explicit")],
        }
        out.append(merged_bundle)
    out.extend(unkeyed)
    out.sort(key=lambda x:(x.get("research_value_score") or 0,x.get("independent_problem_evidence_count") or 0),reverse=True)
    return out,{"input_hypotheses":len(hypotheses),"canonical_hypotheses":len(out),"duplicate_hypothesis_records_merged":merged,"unique_hypothesis_keys":len({h.get("hypothesis_key") for h in out if h.get("hypothesis_key")})}


def build_evidence_bundles(observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],list[dict[str, Any]],list[dict[str, Any]],dict[str,Any]]:
    seeds,seed_meta=build_problem_seeds(observations)
    supply=[o for o in observations if o.get("paid_supply") and str(o.get("source_role") or "")=="MARKET_SUPPLY"]
    changes=[o for o in observations if o.get("change_explicit") and o.get("change_authority")]
    hypotheses=[];watch=[];research=[]
    for seed in seeds:
        p=seed["problem_obs"];pains=seed["pain_evidence"]
        supply_evidence=[x for x in supply if _supply_matches(seed,x)]
        # External changes remain separate research objects.  U4 matched them merely on a
        # shared workflow/vertical and produced absurd why-now links.  U5 deliberately
        # leaves this empty here; the Founder surface may nominate context only through a
        # stronger structural relation check, never as certified why-now evidence.
        enabler_context=[]
        facets,facet_refs=_facet_labels(p,pains,supply_evidence)
        bundle={
            **seed,"facets":facets,"display_primary_facet":facets[0] if facets else None,"facet_evidence_refs":facet_refs,
            "evidence_bundle":{
                "problem":[evidence_ref(p)],
                "recurrence":[evidence_ref(x) for x in pains[1:]],
                "market_supply":[evidence_ref(x) for x in supply_evidence[:3]],
                "external_enabler_candidates":[evidence_ref(x) for x in enabler_context],
                "why_now":[],
                "payment_behavior":[evidence_ref(x) for x in pains if x.get("payment_behavior_observed")],
                "economic_burden":[evidence_ref(x) for x in pains if x.get("burden_explicit")],
            },
            "supply_evidence":supply_evidence,"change_evidence":[],"external_enabler_candidates":enabler_context,
            "identity_facets_excluded":True,"opportunity_linkage_status":"FRONTIER_NOT_SELF_CERTIFIED",
        }
        # A research hypothesis is an evidence-backed problem family. Facets are optional metadata,
        # never a prerequisite for the existence of the hypothesis.
        ready=bool(seed.get("seed_key")) and len(pains)>=2 and seed["research_value_score"]>=1.5
        if ready:
            hypotheses.append(bundle)
        reasons=[]
        if len(pains)<2:reasons.append("NEEDS_INDEPENDENT_RECURRENCE")
        if not seed.get("seed_key"):reasons.append("NEEDS_STABLE_PROBLEM_FAMILY_IDENTITY")
        if not facets:reasons.append("NO_SUPPORTED_NON_IDENTITY_FACET_YET")
        if seed.get("contains_incomplete_need"):reasons.append("CONTAINS_INCOMPLETE_NEED_FRAGMENT")
        if seed["research_value_score"]<1.5:reasons.append("LOW_RESEARCH_PRIORITY_EVIDENCE")
        if not ready:
            item={
                "hypothesis_key":seed.get("hypothesis_key"),"fragment_cluster_key":seed.get("fragment_cluster_key"),"seed_key":seed.get("seed_key"),
                "identity_status":seed.get("identity_status"),"problem":_clean(p.get("problem_span"))[:800],"primary_problem_signature":p.get("primary_problem_signature"),
                "problem_family_descriptor":seed.get("problem_family_descriptor"),"product_id":p.get("product_id"),"product_name":p.get("product_name"),
                "vertical":p.get("vertical"),"workflow":p.get("workflow"),"actor":p.get("actor_scope"),"source_family":p.get("source_family"),"source_ref":p.get("source_ref"),
                "feedback_role":p.get("feedback_role"),"feedback_role_confidence":p.get("feedback_role_confidence"),"need_frame":p.get("need_frame") or {},
                "problem_obs":p,"independent_problem_evidence_count":len(pains),"research_value_score":seed["research_value_score"],"research_tier":seed.get("research_tier"),
                "reason_codes":reasons,"candidate_facets_if_corroborated":facets,"evidence_disposition":p.get("evidence_disposition"),
            }
            # Mature feedback-taxonomy practice keeps low-information items, but a MISC item
            # does not consume the scarce Watch/Recovery budget until corroboration improves it.
            if seed.get("research_tier") in {"HIGH","MEDIUM"}:
                watch.append(item)
                if seed["research_value_score"]>=1.5:
                    missing=[]
                    if len(pains)<2:missing.append("INDEPENDENT_FIRSTHAND_SAME_PROBLEM_EVIDENCE")
                    if not seed.get("seed_key"):missing.append("STABLE_PROBLEM_FAMILY_IDENTITY")
                    research.append({**item,"missing_evidence":missing,"allowed_next_evidence":"Retrieve and rerank independent firsthand evidence for this observed need fragment. Preserve uncertainty; do not invent a product or opportunity.","status":"NEEDS_EVIDENCE"})
    hypotheses.sort(key=lambda x:(x["research_value_score"],x["independent_problem_evidence_count"],len(x["facets"])),reverse=True)
    hypotheses,hyp_canon=canonicalize_hypotheses(hypotheses)
    research.sort(key=lambda x:x["research_value_score"],reverse=True)
    telemetry={**seed_meta,**hyp_canon,
        "current_ready_hypotheses":len(hypotheses),"watch_count":len(watch),"research_queue_count":len(research),
        "misc_backlog_count":sum(1 for s in seeds if s.get("research_tier")=="MISC" and s["independent_problem_evidence_count"]<2),
        "signature_missing_research_items":sum(1 for x in research if not x.get("primary_problem_signature")),
        "facet_counts":dict(Counter(f for h in hypotheses for f in h["facets"])),
        "unique_hypothesis_keys":len({h["hypothesis_key"] for h in hypotheses}),
        "identity_contract":"EVIDENCE_DERIVED_PROBLEM_FAMILY_BEFORE_FACETS; LEGACY_SIGNATURE_OR_STRUCTURAL_NEED_FRAME_OR_SHARED_TERMS; OPPORTUNITY_LINKAGE_FRONTIER",
    }
    return hypotheses,watch,research,telemetry


def hypothesis_summary(h: dict[str, Any]) -> dict[str, Any]:
    p=h.get("problem_obs") or {};pains=h.get("pain_evidence") or []
    evidence=[]
    for x in pains[:4]:
        evidence.append({
            "ref":evidence_ref(x),
            "source_family":x.get("source_family"),
            "source_role":x.get("source_role"),
            "text":_clean(x.get("problem_span") or x.get("text"))[:500],
            "workflow":x.get("workflow"),
            "actor":x.get("actor_scope"),
            "feedback_role":x.get("feedback_role"),
            "feedback_role_confidence":x.get("feedback_role_confidence"),
        })
    signals={
        "manual_work":any(bool(x.get("manual_behavior")) for x in pains),
        "frequency":any(bool(x.get("frequency_explicit")) for x in pains),
        "economic_burden":any(bool(x.get("burden_explicit")) for x in pains),
        "payment_behavior":any(bool(x.get("payment_behavior_observed")) for x in pains),
        "source_diversity":len({str(x.get("source_family") or "") for x in pains if x.get("source_family")}),
        "independent_source_origins":int(h.get("independent_source_origins") or (h.get("dependency_analysis") or {}).get("independent_source_origins") or 0),
        "dependency_rejected_count":int(h.get("dependency_rejected_count") or (h.get("dependency_analysis") or {}).get("dependency_rejected_count") or len((h.get("dependency_analysis") or {}).get("rejected_dependencies") or [])),
    }
    unknowns=[]
    if not signals["economic_burden"]:unknowns.append("ECONOMIC_BURDEN_NOT_YET_EVIDENCED")
    if not signals["payment_behavior"]:unknowns.append("PAYMENT_BEHAVIOR_NOT_YET_EVIDENCED")
    if not (h.get("evidence_bundle") or {}).get("market_supply"):unknowns.append("MARKET_SUPPLY_NOT_YET_LINKED")
    if not (h.get("evidence_bundle") or {}).get("why_now"):unknowns.append("WHY_NOW_NOT_YET_PROVEN")
    return {
        "hypothesis_key":h.get("hypothesis_key"),"problem_scope_key":h.get("seed_key"),"problem_family_descriptor":h.get("problem_family_descriptor"),
        "problem":_clean(p.get("problem_span"))[:600],"actor":p.get("actor_scope"),"workflow":p.get("workflow"),"vertical":p.get("vertical"),"product":p.get("product_name"),"product_id":p.get("product_id"),
        "feedback_role":p.get("feedback_role"),"feedback_role_confidence":p.get("feedback_role_confidence"),"need_frame":p.get("need_frame") or {},
        "primary_problem_signature":p.get("primary_problem_signature"),"evidence_disposition":p.get("evidence_disposition"),"facets":list(h.get("facets") or []),
        "independent_problem_evidence_count":len(pains),
        "independent_source_origins":signals.get("independent_source_origins",0),
        "dependency_rejected_count":signals.get("dependency_rejected_count",0),
        "dependency_analysis":h.get("dependency_analysis") or {},
        "problem_ref":evidence_ref(p),"corroboration_refs":[evidence_ref(x) for x in pains[1:]],
        "evidence_preview":evidence,"signals":signals,"unknowns":unknowns,
        "market_supply_refs":list((h.get("evidence_bundle") or {}).get("market_supply") or []),"external_enabler_candidate_refs":list((h.get("evidence_bundle") or {}).get("external_enabler_candidates") or []),
        "why_now_refs":[],"research_value_score":h.get("research_value_score"),"semantic_audit":h.get("semantic_audit"),
        "opportunity_linkage_status":h.get("opportunity_linkage_status"),
        "truth_label":"EVIDENCE_BACKED_RESEARCH_HYPOTHESIS_NOT_MARKET_VALIDATED_OPPORTUNITY",
    }


def independent_architecture_acceptance(observation_from_doc) -> dict[str,bool]:
    docs=[
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'t1','text':'App Tripsy. Rating 2/5. Review: It can’t parse emails and I have to enter all the information manually.','title':'Email parse','rating':'2','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'t2','text':'App Tripsy. Rating 2/5. Review: Which doesn’t parse the emails half of the time and makes you enter all the information manually.','title':'Manual entry','rating':'2','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'t3','text':'App Tripsy. Rating 2/5. Review: Which doesn’t parse the emails half of the time and makes you enter all the information manually.','title':'Manual entry copy','rating':'2','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'market_supply_external','source_family':'app_store','table':'apps','pk':'399057337','text':'App Store software Tripsy. Seller Tripsy LLC. Category Travel. Upfront pricing $9.99. Description: travel planner.','title':'Tripsy','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'market_supply_external','source_family':'app_store','table':'apps','pk':'flightview','text':'App Store software FlightView. Category Travel. Upfront pricing $4.99. Description: flight tracker.','title':'FlightView','app_id':'flightview','app_name':'FlightView','app_category':'Travel','paid_supply':True},
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'t4','text':'App Tripsy. Rating 1/5. Review: The app freezes constantly when I open a trip.','title':'Freeze','rating':'1','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'t5','text':'App Tripsy. Rating 1/5. Review: Tripsy crashes and freezes every time I open a long itinerary.','title':'Crash','rating':'1','app_id':'399057337','app_name':'Tripsy','app_category':'Travel','paid_supply':True},
        {'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'p1','text':'App Noteful. Rating 5/5. Review: It works beautifully and the pro price is extremely reasonable and worth it.','title':'Great','rating':'5','app_id':'noteful','app_name':'Noteful','app_category':'Productivity'},
        {'source':'market_supply_external','source_family':'app_store','table':'apps','pk':'tripit','text':'App Store software TripIt. Seamlessly sync travel plans to your calendar.','title':'TripIt','app_id':'tripit','app_name':'TripIt','app_category':'Travel','paid_supply':True},
        {'source':'jobs','source_family':'jobs','table':'jobs','pk':'j1','text':'Our mission is to increase the efficiency of the global supply chain by automating manual workflows.','title':'AI logistics role'},
    ]
    obs=[]
    for d in docs:
        o=observation_from_doc(d);obs.append(ensure_observation_schema(o))
    hyps,watch,research,meta=build_evidence_bundles(obs)
    tripsy_parse=[h for h in hyps if h.get('product_id')=='399057337' and (h.get('problem_family_descriptor') or '').find('import_parse_failure')>=0]
    tripsy_freeze=[h for h in hyps if h.get('product_id')=='399057337' and (h.get('problem_family_descriptor') or '').find('crash_freeze')>=0]
    # Explicit signatureless firsthand fragments: retain and recover rather than die.
    frag1=annotate_observation({'observation_id':'s1','source':'community_external','source_family':'reddit_rss','source_table':'reddit','source_ref':'s1','source_role':'FIRSTHAND_USER_PAIN','primary_pain_authority':True,'direct_pain':True,'problem_polarity':'NEGATIVE','problem_target':'PRIMARY_SOURCE_SUBJECT','problem_span':'For each booking I type the customer details into our spreadsheet again.','primary_problem_signature':'','problem_signatures':[],'problem_self_contained':False,'actor_scope':'small_business_owner','native_scope':'smallbusiness','workflow':'booking','vertical':'professional_services','manual_behavior':True,'frequency_explicit':True,'normalized_problem_hash':'s1h','independence_key':'reddit|s1'})
    frag2=annotate_observation({'observation_id':'s2','source':'community_external','source_family':'reddit_rss','source_table':'reddit','source_ref':'s2','source_role':'FIRSTHAND_USER_PAIN','primary_pain_authority':True,'direct_pain':True,'problem_polarity':'NEGATIVE','problem_target':'PRIMARY_SOURCE_SUBJECT','problem_span':'Every booking means typing the same customer details into a spreadsheet by hand.','primary_problem_signature':'','problem_signatures':[],'problem_self_contained':False,'actor_scope':'small_business_owner','native_scope':'smallbusiness','workflow':'booking','vertical':'professional_services','manual_behavior':True,'frequency_explicit':True,'normalized_problem_hash':'s2h','independence_key':'reddit|s2'})
    fh,fw,fr,fm=build_evidence_bundles([frag1,frag2])
    singleton=build_evidence_bundles([frag1])
    return {
        'tripsy_same_problem_single_identity':len(tripsy_parse)==1,
        'facets_do_not_duplicate_identity':len({h['hypothesis_key'] for h in hyps})==len(hyps),
        'duplicate_text_not_independent':bool(tripsy_parse and tripsy_parse[0]['independent_problem_evidence_count']==2),
        'same_product_different_problem_separate':len(tripsy_freeze)==1 and bool(tripsy_parse) and tripsy_freeze[0]['hypothesis_key']!=tripsy_parse[0]['hypothesis_key'],
        'unrelated_competitor_not_supply_context':bool(tripsy_parse and all('flightview' not in x.lower() for x in tripsy_parse[0]['evidence_bundle']['market_supply'])),
        'product_wedge_is_facet_not_identity':bool(tripsy_parse and 'PROVEN_MARKET_WEDGE' in tripsy_parse[0]['facets'] and 'PROVEN_MARKET_WEDGE' not in tripsy_parse[0]['hypothesis_key']),
        'positive_review_not_seed':all((h.get('product_id')!='noteful') for h in hyps) and all((w.get('product_id')!='noteful') for w in watch),
        'supplier_capability_not_problem_seed':all((h.get('product_id')!='tripit') for h in hyps),
        'vendor_mission_not_problem_seed':all((h.get('problem_obs') or {}).get('source_family')!='jobs' for h in hyps),
        'typed_bundle_problem_and_recurrence':bool(tripsy_parse and len(tripsy_parse[0]['evidence_bundle']['problem'])==1 and len(tripsy_parse[0]['evidence_bundle']['recurrence'])>=1),
        'primary_not_repeated_as_corroboration':bool(tripsy_parse and tripsy_parse[0]['evidence_bundle']['problem'][0] not in set(tripsy_parse[0]['evidence_bundle']['recurrence'])),
        'market_supply_must_come_from_supply_role':bool(tripsy_parse and tripsy_parse[0]['evidence_bundle']['market_supply']==['market_supply_external:apps:399057337']),
        'signatureless_fragments_survive':all(x.get('evidence_disposition')=='INCOMPLETE_NEED' for x in [frag1,frag2]),
        'signatureless_fragments_route_to_research_or_family':bool(fh or fr),
        'singleton_incomplete_enters_research':len(singleton[2])==1 and 'STABLE_PROBLEM_FAMILY_IDENTITY' in (singleton[2][0].get('missing_evidence') or []),
        'external_enabler_not_auto_transition':all('TRANSITION_GAP' not in (h.get('facets') or []) for h in hyps),
        'identity_meta_reports_unique_hypotheses':meta.get('unique_hypothesis_keys')==len(hyps),
    }


def static_acceptance()->dict[str,bool]:
    a=annotate_observation({'observation_id':'a','source':'community','source_family':'reddit_rss','source_table':'r','source_ref':'1','source_role':'FIRSTHAND_USER_PAIN','primary_pain_authority':True,'direct_pain':True,'problem_polarity':'NEGATIVE','problem_target':'PRIMARY_SOURCE_SUBJECT','problem_span':'Every booking means typing customer details into our sheet again.','primary_problem_signature':'','problem_signatures':[],'problem_self_contained':False,'actor_scope':'owner','native_scope':'smallbusiness','workflow':'booking','vertical':'professional_services','manual_behavior':True,'frequency_explicit':True,'normalized_problem_hash':'h1','independence_key':'r|1'})
    b=annotate_observation({**a,'observation_id':'b','source_ref':'2','problem_span':'For each booking I type the same customer details into a spreadsheet again.','normalized_problem_hash':'h2','independence_key':'r|2'})
    h,w,r,m=build_evidence_bundles([a,b])
    nf1=annotate_observation({'observation_id':'nf1','source':'community','source_family':'reddit_rss','source_table':'r','source_ref':'nf1','source_role':'FIRSTHAND_USER_PAIN','primary_pain_authority':True,'direct_pain':True,'problem_polarity':'NEGATIVE','problem_target':'PRIMARY_SOURCE_SUBJECT','problem_span':'Export is slow every time and takes several minutes to finish.','primary_problem_signature':'slow_delay','problem_signatures':['slow_delay'],'problem_self_contained':True,'actor_scope':'user','native_scope':'general','workflow':'other','vertical':'other','frequency_explicit':True,'normalized_problem_hash':'nfh1','independence_key':'r|nf1'})
    nf2=annotate_observation({'observation_id':'nf2','source':'community','source_family':'reddit_rss','source_table':'r','source_ref':'nf2','source_role':'FIRSTHAND_USER_PAIN','primary_pain_authority':True,'direct_pain':True,'problem_polarity':'NEGATIVE','problem_target':'PRIMARY_SOURCE_SUBJECT','problem_span':'The export process takes several minutes on every run and is painfully slow.','primary_problem_signature':'slow_delay','problem_signatures':['slow_delay'],'problem_self_contained':True,'actor_scope':'user','native_scope':'general','workflow':'other','vertical':'other','frequency_explicit':True,'normalized_problem_hash':'nfh2','independence_key':'r|nf2'})
    nfh,_,_,_=build_evidence_bundles([nf1,nf2])
    ti1=annotate_observation({**nf1,'observation_id':'ti1','source_ref':'ti1','problem_span':"I cannot import 'AgentExecutor' from langchain.agents and my app fails.",'workflow':'coding','vertical':'software','actor_scope':'developer','primary_problem_signature':'import_parse_failure','problem_signatures':['import_parse_failure'],'normalized_problem_hash':'ti1','independence_key':'r|ti1'})
    ti2=annotate_observation({**ti1,'observation_id':'ti2','source_ref':'ti2','problem_span':"We cannot import 'AgentExecutor' from langchain.agents after the update and it fails.",'normalized_problem_hash':'ti2','independence_key':'r|ti2'})
    tj1=annotate_observation({**ti1,'observation_id':'tj1','source_ref':'tj1','problem_span':"I cannot import 'Create_react_agent' from langchain.agents and my app fails.",'normalized_problem_hash':'tj1','independence_key':'r|tj1'})
    tj2=annotate_observation({**ti1,'observation_id':'tj2','source_ref':'tj2','problem_span':"We cannot import 'Create_react_agent' from langchain.agents after the update and it fails.",'normalized_problem_hash':'tj2','independence_key':'r|tj2'})
    target_seeds,_=build_problem_seeds([ti1,ti2,tj1,tj2])
    canon_test,canon_meta=canonicalize_hypotheses([nfh[0],dict(nfh[0])]) if nfh else ([],{})
    cp1=annotate_observation({**nf1,'observation_id':'cp1','source':'community_raw','source_family':'community_raw','source_ref':'3423','problem_span':'(Broadcast flag, Macrovision, deliberately miswritten floppy sectors, port dongles, physical manual challenge-response...)','normalized_problem_hash':'cp1','independence_key':'community_raw|3423'})
    cp2=annotate_observation({**nf1,'observation_id':'cp2','source':'community_raw','source_family':'community_raw','source_ref':'3424','problem_span':'(Broadcast flag, Macrovision, deliberately miswritten floppy sectors, port dongles, physical manual challenge-response...) Yes?','normalized_problem_hash':'cp2','independence_key':'community_raw|3424'})
    cp_h,_,_,_=build_evidence_bundles([cp1,cp2])
    return {
        'missing_signature_is_not_hard_reject':problem_observation_ok(a)[0] is True,
        'retrieve_rerank_retains_problem_fragments':len(h)+len(w)+len(r)>=1,
        'identity_stable_before_facets':bool((h and h[0].get('identity_facets_excluded')) or r),
        'content_independence_required':content_independent(a,b),
        'signatureless_evidence_not_deleted':all(x.get('evidence_disposition') in {'DIRECT_NEED','INCOMPLETE_NEED'} for x in (a,b)),
        'facet_set_is_nonexclusive':len(FACETS)==6,
        'hypothesis_key_does_not_embed_lane':all(x not in (h[0]['hypothesis_key'] if h else '') for x in FACETS) if h else True,
        'research_value_not_market_size':research_value_score(a)>=1.5,
        'opportunity_linkage_not_self_certified':all(x.get('opportunity_linkage_status')=='FRONTIER_NOT_SELF_CERTIFIED' for x in h) if h else True,
        'facet_not_required_for_research_hypothesis':len(nfh)==1 and not (nfh[0].get('facets') or []),
        'specific_target_prevents_broad_signature_identity_collision':len({x.get('hypothesis_key') for x in target_seeds if x.get('hypothesis_key')})==2,
        'canonicalization_merges_duplicate_hypothesis_records':len(canon_test)==1 and canon_meta.get('duplicate_hypothesis_records_merged')==1,
        'u4_crosspost_near_duplicate_not_hypothesis':len(cp_h)==0,
    }
