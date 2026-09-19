"""Balanced hybrid evidence retrieval + reranking for SignalForge A2.

Mature methods adopted:
- inverted-index / TF-IDF-style candidate retrieval instead of a single hard signature;
- per-anchor top-k retrieval so one large bucket cannot starve the rest of the corpus;
- multiple reranking signals (lexical, product, workflow, vertical, actor, legacy signature);
- provenance/dependence is checked before recurrence is counted;
- low-confidence relations remain candidates/related context rather than truth.

This module still does not decide that a venture opportunity exists.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from processors.opportunity_evidence_atoms import lexical_terms, ensure_observation_schema
from processors.opportunity_evidence_provenance import content_independent, dependence_reason

ENGINE_VERSION = "opportunity-evidence-retrieval-usability-u3-structural-need-rerank"
MAX_BUCKET = 120
PER_ANCHOR_CANDIDATES = 8
MAX_PAIRS = 16000

GENERIC_TERMS = {
    "this","that","with","from","have","will","your","their","there","about","into","when","using","used",
    "app","product","review","really","just","does","doesn","cannot","cant","could","would","should","because",
    "still","very","much","more","than","then","they","them","what","user","users","issue","problem","thing",
    "title","repo","repo_full_name","repository","mediajunkie","audit","ops","http","https","www","com","github",
}


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _tokens(o: dict[str, Any]) -> set[str]:
    terms = o.get("problem_lexical_terms") or ((o.get("evidence_atom") or {}).get("lexical_terms"))
    if not terms:
        terms = lexical_terms(o.get("problem_span") or o.get("text"), limit=24)
    out=set()
    for raw in terms:
        t=str(raw).lower().strip(" -_./:;,")
        if len(t)<3 or t in GENERIC_TERMS or "_" in t or "/" in t or "\\" in t:
            continue
        if re.fullmatch(r"[a-f0-9]{8,}",t):
            continue
        out.add(t)
    return out


def _char_ngrams(text: Any, n: int = 4) -> set[str]:
    s = re.sub(r"[^a-z0-9]+", " ", _clean(text).lower()).strip()
    s = f" {s} "
    if len(s) <= n:
        return {s} if s else set()
    return {s[i:i+n] for i in range(len(s)-n+1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def lexical_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    # Word-level normalized overlap is the main mature retrieval signal. Character
    # n-grams are intentionally omitted from the hot path because they made live
    # corroboration quadratic-in-string-work even after pair bounding.
    ta,tb=_tokens(a),_tokens(b)
    if not ta or not tb:return 0.0
    inter=len(ta&tb)
    # Sørensen-Dice is less punitive than Jaccard for short paraphrases.
    return round((2.0*inter)/max(1,len(ta)+len(tb)),4)


def _frame(o: dict[str, Any]) -> dict[str, Any]:
    f=o.get("need_frame")
    return f if isinstance(f,dict) else {}


def _set(v: Any) -> set[str]:
    if isinstance(v,(list,tuple,set)):
        return {str(x).lower().strip() for x in v if str(x).strip()}
    return {str(v).lower().strip()} if str(v or '').strip() else set()


def structural_features(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    pa, pb = _clean(a.get("product_id")), _clean(b.get("product_id"))
    wa, wb = _clean(a.get("workflow")).lower(), _clean(b.get("workflow")).lower()
    va, vb = _clean(a.get("vertical")).lower(), _clean(b.get("vertical")).lower()
    aa, ab = _clean(a.get("actor_scope")).lower(), _clean(b.get("actor_scope")).lower()
    sa, sb = _clean(a.get("primary_problem_signature")).lower(), _clean(b.get("primary_problem_signature")).lower()
    fa,fb=_frame(a),_frame(b)
    acta,actb=_set(fa.get("actions")),_set(fb.get("actions"))
    falla,fallb=_set(fa.get("failure_modes")),_set(fb.get("failure_modes"))
    obja,objb=_set(fa.get("objects")),_set(fb.get("objects"))
    ta,tb=_set(fa.get("specific_targets")),_set(fb.get("specific_targets"))
    pta,ptb=str(fa.get("primary_specific_target") or '').lower(),str(fb.get("primary_specific_target") or '').lower()
    return {
        "same_product": 1.0 if pa and pb and pa == pb else 0.0,
        "same_workflow": 1.0 if wa and wb and wa != "other" and wa == wb else 0.0,
        "same_vertical": 1.0 if va and vb and va != "other" and va == vb else 0.0,
        "same_actor": 1.0 if aa and ab and aa not in {"unknown", "community_user"} and aa == ab else 0.0,
        "same_legacy_signature": 1.0 if sa and sb and sa == sb else 0.0,
        "different_strong_signature": 1.0 if sa and sb and sa != sb else 0.0,
        "same_action": 1.0 if acta and actb and bool(acta&actb) else 0.0,
        "same_failure": 1.0 if falla and fallb and bool(falla&fallb) else 0.0,
        "object_overlap": round(jaccard(obja,objb),4) if obja and objb else 0.0,
        "specific_target_match": 1.0 if pta and ptb and pta==ptb else 0.0,
        "specific_target_conflict": 1.0 if pta and ptb and pta!=ptb else 0.0,
    }

def relation_score(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    dep = dependence_reason(a, b)
    if dep:
        return {"relation":"DEPENDENT_EVIDENCE", "score":0.0, "reason_codes":[dep], "lexical":0.0, "features":{}}
    f = structural_features(a, b)
    lex = lexical_similarity(a, b)
    shared=len(_tokens(a)&_tokens(b))
    score = 0.0
    score += 0.30 * f["same_product"]
    score += 0.18 * f["same_workflow"]
    score += 0.08 * f["same_vertical"]
    score += 0.05 * f["same_actor"]
    score += 0.22 * f["same_legacy_signature"]
    score += 0.12 * f["same_action"]
    score += 0.18 * f["same_failure"]
    score += 0.10 * f["object_overlap"]
    score += 0.12 * f["specific_target_match"]
    score += 0.42 * lex
    score += 0.05 if shared >= 2 else 0.0
    if f["different_strong_signature"]:
        score -= 0.38
    if f.get("specific_target_conflict"):
        score -= 0.58
    if f.get("specific_target_conflict"):
        score=min(score,0.49)
    # Same product is useful retrieval context but never sufficient evidence of the same pain.
    if f["same_product"] and not f["same_legacy_signature"] and (lex < 0.18 or shared < 2):
        score -= 0.28
        # Product/workflow scope is retrieval context, not identity. Without at least
        # two shared problem terms, do not allow structural context alone to cross the
        # SAME_PROBLEM threshold.
        if shared < 2 and not (f.get("same_failure") and f.get("same_action") and f.get("object_overlap",0)>=0.12):
            score=min(score,0.49)
    # Cross-product/market recurrence needs both structural and lexical support.
    if not f["same_product"] and not (f["same_workflow"] and f["same_vertical"]):
        score -= 0.18
    # Structural alignment is an additional relation signal, never a standalone truth gate.
    if f.get("same_failure") and f.get("same_action") and f.get("object_overlap",0)>=0.12:
        score += 0.08
    if f.get("specific_target_conflict"):
        score=min(score,0.49)
    score = max(0.0, min(1.0, score))
    reasons=[]
    for k,v in f.items():
        if v: reasons.append(k.upper())
    if shared: reasons.append(f"SHARED_TERMS_{shared}")
    if lex >= 0.15: reasons.append("LEXICAL_SUPPORT")
    if lex < 0.05: reasons.append("LOW_LEXICAL_SUPPORT")
    relation = "SAME_PROBLEM_CANDIDATE" if score >= 0.54 else ("RELATED_CONTEXT" if score >= 0.34 else "MISMATCH")
    return {"relation":relation,"score":round(score,4),"reason_codes":reasons,"lexical":lex,"features":f,"shared_terms":shared}


def _eligible(observations: list[dict[str, Any]]) -> list[int]:
    return [i for i,o in enumerate(observations) if o.get("evidence_disposition") in {"DIRECT_NEED","INCOMPLETE_NEED"}]


def _idf(observations: list[dict[str, Any]], ids: list[int]) -> dict[str,float]:
    df=Counter()
    for i in ids:
        for t in _tokens(observations[i]): df[t]+=1
    n=max(1,len(ids))
    return {t: math.log((n+1)/(c+1))+1.0 for t,c in df.items()}


def candidate_pairs(observations: list[dict[str, Any]]) -> tuple[list[tuple[int,int]], dict[str, Any]]:
    ids=_eligible(observations)
    idf=_idf(observations,ids)
    by_product=defaultdict(list);by_market=defaultdict(list);by_sig=defaultdict(list);by_term=defaultdict(list);by_failure=defaultdict(list);by_action=defaultdict(list)
    for i in ids:
        o=observations[i]
        pid=_clean(o.get("product_id"));wf=_clean(o.get("workflow")).lower();vert=_clean(o.get("vertical")).lower();sig=_clean(o.get("primary_problem_signature")).lower()
        if pid and len(by_product[pid])<MAX_BUCKET: by_product[pid].append(i)
        if wf and wf!="other" and vert and vert!="other" and len(by_market[(vert,wf)])<MAX_BUCKET: by_market[(vert,wf)].append(i)
        if sig and len(by_sig[sig])<MAX_BUCKET: by_sig[sig].append(i)
        for t in sorted(_tokens(o), key=lambda x:idf.get(x,0), reverse=True)[:6]:
            if len(by_term[t])<MAX_BUCKET: by_term[t].append(i)
        fr=_frame(o)
        for ft in list(fr.get("failure_modes") or [])[:3]:
            if len(by_failure[str(ft)])<MAX_BUCKET: by_failure[str(ft)].append(i)
        for ac in list(fr.get("actions") or [])[:3]:
            if len(by_action[str(ac)])<MAX_BUCKET: by_action[str(ac)].append(i)

    pair_scores={}
    anchors_with_candidates=0
    for i in ids:
        o=observations[i];cand=Counter();pid=_clean(o.get("product_id"));wf=_clean(o.get("workflow")).lower();vert=_clean(o.get("vertical")).lower();sig=_clean(o.get("primary_problem_signature")).lower()
        if pid:
            for j in by_product.get(pid,[]):
                if j!=i: cand[j]+=2.2
        if sig:
            for j in by_sig.get(sig,[]):
                if j!=i: cand[j]+=3.0
        if wf and wf!="other" and vert and vert!="other":
            for j in by_market.get((vert,wf),[]):
                if j!=i: cand[j]+=1.2
        for t in sorted(_tokens(o), key=lambda x:idf.get(x,0), reverse=True)[:6]:
            w=min(2.2,idf.get(t,1.0))
            for j in by_term.get(t,[]):
                if j!=i: cand[j]+=w
        fr=_frame(o)
        for ft in list(fr.get("failure_modes") or [])[:3]:
            for j in by_failure.get(str(ft),[]):
                if j!=i: cand[j]+=1.35
        for ac in list(fr.get("actions") or [])[:3]:
            for j in by_action.get(str(ac),[]):
                if j!=i: cand[j]+=0.75
        if cand: anchors_with_candidates+=1
        # Per-anchor top-k prevents one early giant bucket from exhausting the global budget.
        for j,_ in cand.most_common(PER_ANCHOR_CANDIDATES):
            a,b=(i,j) if i<j else (j,i)
            if a==b: continue
            pair_scores[(a,b)]=max(pair_scores.get((a,b),0.0),float(cand[j]))

    ranked=sorted(pair_scores.items(), key=lambda kv:(-kv[1],kv[0]))[:MAX_PAIRS]
    pairs=[p for p,_ in ranked]
    return pairs, {
        "eligible":len(ids),"candidate_pairs":len(pairs),"pair_cap":MAX_PAIRS,"per_anchor_cap":PER_ANCHOR_CANDIDATES,
        "anchors_with_candidates":anchors_with_candidates,"coverage":round(anchors_with_candidates/max(1,len(ids)),4),
        "index_terms":len(by_term),"product_buckets":len(by_product),"market_buckets":len(by_market),"signature_buckets":len(by_sig),
        "failure_buckets":len(by_failure),"action_buckets":len(by_action),
        "architecture":"BALANCED_PER_ANCHOR_HYBRID_TFIDF_PLUS_EVIDENCE_DERIVED_STRUCTURAL_FRAME_RETRIEVAL",
    }


def retrieve_neighbors(anchor: dict[str, Any], observations: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    out=[]
    for o in observations:
        if o is anchor or o.get("observation_id")==anchor.get("observation_id"):
            continue
        if o.get("evidence_disposition") not in {"DIRECT_NEED","INCOMPLETE_NEED"}:
            continue
        r=relation_score(anchor,o)
        if r["relation"] in {"SAME_PROBLEM_CANDIDATE","RELATED_CONTEXT"}:
            out.append({"observation":o, **r})
    out.sort(key=lambda x:x["score"],reverse=True)
    return out[:limit]


def build_relation_candidates(observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs, meta = candidate_pairs(observations)
    edges=[]; relations=Counter(); independent_checked=0;top_related=[]
    for i,j in pairs:
        a,b=observations[i],observations[j]
        independent_checked+=1
        r=relation_score(a,b); relations[r["relation"]]+=1
        sample={"a":a.get("observation_id"),"b":b.get("observation_id"),"score":r["score"],"lexical":r.get("lexical"),"reasons":r.get("reason_codes"),"a_text":_clean(a.get("problem_span"))[:180],"b_text":_clean(b.get("problem_span"))[:180]}
        if r["relation"]=="SAME_PROBLEM_CANDIDATE":
            edges.append({"a":a.get("observation_id"),"b":b.get("observation_id"),"score":r["score"],"reason_codes":r["reason_codes"],"lexical":r["lexical"],"features":r["features"]})
        elif r["relation"]=="RELATED_CONTEXT":
            top_related.append(sample)
    top_related=sorted(top_related,key=lambda x:x["score"],reverse=True)[:12]
    meta.update({"relations":dict(relations),"independent_checked":independent_checked,"same_problem_candidates":len(edges),"top_related_samples":top_related,"architecture":"RETRIEVE_THEN_RERANK_NOT_SINGLE_SIGNATURE_GATE"})
    return edges,meta


def static_acceptance() -> dict[str, bool]:
    base={"source_family":"app_store_reviews","source":"product_review_external","source_table":"reviews","source_role":"FIRSTHAND_USER_PAIN","primary_pain_authority":True,"direct_pain":True,"problem_polarity":"NEGATIVE","problem_target":"PRIMARY_SOURCE_SUBJECT","evidence_disposition":"INCOMPLETE_NEED","workflow":"travel_planning","vertical":"consumer","actor_scope":"product_user","product_id":"tripsy","primary_problem_signature":"","problem_lexical_terms":[]}
    a={**base,"source_ref":"1","observation_id":"1","problem_span":"Email trips make me type itinerary details again by hand."}
    b={**base,"source_ref":"2","observation_id":"2","problem_span":"For emailed itineraries I must manually type all the trip details again."}
    c={**base,"source_ref":"3","observation_id":"3","problem_span":"The app freezes whenever I open a long trip.","primary_problem_signature":"crash_freeze"}
    d={**base,"source_ref":"4","observation_id":"4","problem_span":"Tripsy crashes and freezes when opening long itineraries.","primary_problem_signature":"crash_freeze"}
    a=ensure_observation_schema(a,force=True);b=ensure_observation_schema(b,force=True);c=ensure_observation_schema(c,force=True);d=ensure_observation_schema(d,force=True)
    ra=relation_score(a,b);rc=relation_score(c,d);mix=relation_score(a,c)
    # Starvation regression: a matching pair late in the list must still be nominated.
    many=[]
    for i in range(600):
        many.append({"observation_id":f"x{i}","source_family":"reddit_rss","source_ref":f"x{i}","evidence_disposition":"INCOMPLETE_NEED","workflow":"ops","vertical":"business","problem_span":f"Generic workflow complaint unique{i}","problem_lexical_terms":["workflow",f"unique{i}"],"product_id":""})
    many += [
        {**a,"observation_id":"late_a","source_ref":"late_a","product_id":"lateproduct"},
        {**b,"observation_id":"late_b","source_ref":"late_b","product_id":"lateproduct"},
    ]
    pairs,pm=candidate_pairs(many);idx={o["observation_id"]:i for i,o in enumerate(many)};late=(min(idx["late_a"],idx["late_b"]),max(idx["late_a"],idx["late_b"]))
    return {
        "signatureless_paraphrase_can_retrieve":ra["relation"]=="SAME_PROBLEM_CANDIDATE",
        "legacy_signature_still_helps_not_controls":rc["relation"]=="SAME_PROBLEM_CANDIDATE",
        "same_product_different_failure_not_forced_same":mix["relation"]!="SAME_PROBLEM_CANDIDATE",
        "retrieval_exposes_reason_codes":bool(ra["reason_codes"]),
        "balanced_per_anchor_prevents_global_bucket_starvation":late in pairs,
        "bounded_candidate_generation":pm["candidate_pairs"]<=MAX_PAIRS,
        "structural_features_visible":all(k in ra.get("features",{}) for k in ["same_action","same_failure","object_overlap","specific_target_conflict"]),
    }
