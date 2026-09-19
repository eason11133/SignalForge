from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from processors.signalforge_brain_v2_contracts import clean, dice, normalize_state, stable_hash

ENGINE_VERSION = "signalforge-brain-v2-structural-recall-g3"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+.#:/-]{1,}", re.I)
# Keep domain identity nouns such as agent/api/platform/model. Remove generic temporal prose
# that made R2 turn timing context into hundreds of false persistent transitions.
_IDENTITY_STOP = {
    "the","and","for","with","from","that","this","then","than","when","where","what","which","while",
    "into","onto","over","under","about","more","very","some","other","new","now","current","today","recent",
    "change","changes","changed","changing","shift","shifts","shifting","adoption","adopted","adopting","growth",
    "growing","increase","increasing","increased","decrease","decreasing","trend","trends","signal","signals",
    "market","markets","ecosystem","activity","activities","release","released","launch","launched","update",
    "updates","updated","capability","capabilities","workflow","workflows","system","systems","business","businesses",
    "user","users","people","company","companies","use","using","used","make","makes","made","making","become",
    "becomes","becoming","enable","enables","enabled","enabling","larger","smaller","better","faster","easier",
    "remains","remain","still","could","would","should","may","might","can","cannot","across","through","because",
}


def _iso_dt(value: Any) -> datetime | None:
    s = clean(value)
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def identity_terms(value: Any) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall(clean(value).lower()):
        t = raw.strip("._-/:#")
        if len(t) < 3 or t in _IDENTITY_STOP or re.fullmatch(r"\d+", t):
            continue
        if re.fullmatch(r"[0-9a-f]{12,}", t):
            continue
        out.add(t)
    return out


def _content_unit(atom: Mapping[str, Any]) -> str:
    return clean(atom.get("content_fingerprint")) or stable_hash(sorted(identity_terms(atom.get("text"))), length=24)


def _family(atom: Mapping[str, Any]) -> str:
    return clean(atom.get("source_family")) or clean(atom.get("source_ref"))


def _candidate_id(atom: Mapping[str, Any]) -> int:
    try:
        return int(atom.get("candidate_id") or 0)
    except Exception:
        return 0


def _eligible_context_atoms(atoms: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in atoms:
        atom = dict(raw)
        if atom.get("lineage_eligible"):
            continue
        if not bool(atom.get("verified")):
            continue
        if clean(atom.get("source_class")) == "DERIVED_FINGERPRINT_CONTEXT":
            continue
        driver = clean(atom.get("driver")).upper()
        if not driver or driver == "UNKNOWN":
            continue
        terms = identity_terms(atom.get("text"))
        if len(terms) < 2:
            continue
        atom["_identity_terms"] = sorted(terms)
        rows.append(atom)
    return rows


def build_transition_hypotheses(atoms: Iterable[Mapping[str, Any]], *, candidate_to_problem_lineage: Mapping[int, str] | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Stage verified timing context before it gains persistent transition authority.

    G2 intentionally made transition admission strict. That fixed R2's false-positive
    explosion, but a strict one-row admission rule can miss a real structural change that
    appears as several independent, individually context-only observations. G3 adds a
    middle layer: TransitionHypothesis.

    A hypothesis can promote context into a TransitionLineage only when independent sources
    converge on a specific identity over multiple candidates or time. It is still Brain
    derived truth and never writes Radar C01-C14.
    """
    rows = _eligible_context_atoms(atoms)
    if not rows:
        return [], {}

    n = len(rows)
    candidate_to_problem_lineage = {int(k): clean(v) for k,v in dict(candidate_to_problem_lineage or {}).items() if clean(v)}
    df: Counter[str] = Counter()
    for row in rows:
        df.update(set(row.get("_identity_terms") or []))
    # Dynamic specificity guard: common corpus-wide vocabulary is not an identity anchor.
    max_df = max(3, int(math.ceil(n * 0.08)))
    # Cross-problem promotion is deliberately stricter than ordinary specificity.
    # A corpus-relative 2% cutoff made generic vocabulary inside a small driver cohort
    # (for example "compliance/process") look rare enough to become a false global
    # transition. Cap the cross-problem anchor frequency: broad context may corroborate
    # within one already-validated ProblemLineage, but cross-problem promotion needs a
    # genuinely sparse shared identity anchor.
    rare_df = max(2, min(12, int(math.ceil(n * 0.005))))
    prepared: list[dict[str, Any]] = []
    for row in rows:
        terms = list(row.get("_identity_terms") or [])
        specific = [t for t in terms if df[t] <= max_df]
        # If the corpus is tiny, let moderately repeated terms survive while still requiring
        # two anchors. In a large corpus, this stays precision-first.
        if len(specific) < 2 and n <= 12:
            specific = terms
        if len(specific) < 2:
            continue
        specific.sort(key=lambda t: (df[t], -len(t), t))
        row["_specific_terms"] = specific[:8]
        row["_rare_terms"] = [t for t in specific if df[t] <= rare_df][:6]
        row["_problem_lineage_id"] = candidate_to_problem_lineage.get(_candidate_id(row), "")
        prepared.append(row)

    bucket_to_clusters: dict[str, set[int]] = defaultdict(set)
    clusters: list[list[dict[str, Any]]] = []
    comparisons = 0

    def same_hypothesis(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[bool, float]:
        if clean(a.get("driver")).upper() != clean(b.get("driver")).upper():
            return False, 0.0
        aa = set(a.get("_specific_terms") or [])
        bb = set(b.get("_specific_terms") or [])
        shared = aa & bb
        score = dice(aa, bb)
        pa = clean(a.get("_problem_lineage_id")); pb = clean(b.get("_problem_lineage_id"))
        same_problem_scope = bool(pa and pb and pa == pb)
        rare_shared = shared & set(a.get("_rare_terms") or []) & set(b.get("_rare_terms") or [])
        # Within one already-validated ProblemLineage, two independent context rows may
        # corroborate a problem-scoped transition. Across different problems, require a
        # corpus-rare shared identity anchor to prevent generic timing prose from merging.
        if same_problem_scope:
            return bool(len(shared) >= 2 or (len(shared) >= 1 and score >= 0.62)), score
        return bool(rare_shared and (len(shared) >= 2 or score >= 0.55)), score

    for row in sorted(prepared, key=lambda x: clean(x.get("transition_atom_id"))):
        driver = clean(row.get("driver")).upper()
        keys = [f"{driver}:{t}" for t in row.get("_specific_terms", [])]
        candidate_idxs: set[int] = set()
        for key in keys:
            candidate_idxs.update(bucket_to_clusters.get(key, set()))
        placed = False
        for idx in sorted(candidate_idxs):
            cluster = clusters[idx]
            ok = True
            for member in cluster:
                comparisons += 1
                same, _ = same_hypothesis(row, member)
                if not same:
                    ok = False
                    break
            if ok:
                cluster.append(row)
                for key in keys:
                    bucket_to_clusters[key].add(idx)
                placed = True
                break
        if not placed:
            idx = len(clusters)
            clusters.append([row])
            for key in keys:
                bucket_to_clusters[key].add(idx)

    hypotheses: list[dict[str, Any]] = []
    promotions: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        families = sorted({x for x in (_family(a) for a in cluster) if x})
        units = sorted({x for x in (_content_unit(a) for a in cluster) if x})
        cids = sorted({x for x in (_candidate_id(a) for a in cluster) if x})
        dates = sorted(x for x in (_iso_dt(a.get("valid_at")) for a in cluster) if x)
        span_days = max(0, (dates[-1] - dates[0]).days) if len(dates) >= 2 else 0
        term_counts: Counter[str] = Counter()
        for a in cluster:
            term_counts.update(set(a.get("_specific_terms") or []))
        threshold = max(2, int(math.ceil(len(cluster) * 0.60)))
        identity = sorted(
            [t for t, count in term_counts.items() if count >= threshold],
            key=lambda t: (df[t], -term_counts[t], -len(t), t),
        )[:8]
        if len(identity) < 2:
            # Keep a bounded diagnostic object only when two strong evidence units converge;
            # do not promote without a stable shared identity.
            continue
        pair_scores: list[float] = []
        coherent = True
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                same, score = same_hypothesis(cluster[i], cluster[j])
                pair_scores.append(score)
                if not same:
                    coherent = False
                    break
            if not coherent:
                break
        min_coherence = min(pair_scores) if pair_scores else 0.0
        scope_ids=sorted({clean(a.get("_problem_lineage_id")) for a in cluster if clean(a.get("_problem_lineage_id"))})
        same_problem_scope=bool(len(scope_ids)==1 and all(clean(a.get("_problem_lineage_id"))==scope_ids[0] for a in cluster))
        rare_identity=[t for t in identity if df[t] <= rare_df]
        identity_safe=bool(same_problem_scope or rare_identity)
        corroborating = bool(coherent and identity_safe and len(families) >= 2 and len(units) >= 2 and min_coherence >= 0.34)
        promotable = bool(corroborating and (len(cids) >= 2 or span_days >= 14))
        state = "PROMOTABLE" if promotable else ("CORROBORATING" if corroborating else "WEAK")
        if state == "WEAK":
            continue
        driver = clean(cluster[0].get("driver")).upper()
        scope_mode="PROBLEM_SCOPED" if same_problem_scope else "CROSS_PROBLEM_RARE_ANCHOR"
        scope_key=scope_ids[0] if same_problem_scope else "global"
        hid = "th_" + stable_hash(driver, scope_key, identity, length=22)
        obj = {
            "transition_hypothesis_id": hid,
            "driver": driver,
            "state": state,
            "identity_terms": identity,
            "rare_identity_terms": rare_identity[:8],
            "scope_mode": scope_mode,
            "problem_lineage_id": scope_ids[0] if same_problem_scope else None,
            "representative_text": clean(cluster[0].get("text"))[:1200],
            "member_transition_atom_ids": sorted(clean(a.get("transition_atom_id")) for a in cluster if clean(a.get("transition_atom_id"))),
            "member_candidate_ids": cids,
            "independent_source_families": len(families),
            "source_families": families[:32],
            "independent_content_units": len(units),
            "content_units": units[:32],
            "span_days": span_days,
            "first_seen_at": dates[0].isoformat() if dates else None,
            "last_observed_at": dates[-1].isoformat() if dates else None,
            "min_pair_coherence": round(min_coherence, 4),
            "promotion_eligible": promotable,
            "promotion_requirements": {
                "independent_source_families_gte_2": len(families) >= 2,
                "independent_content_units_gte_2": len(units) >= 2,
                "identity_terms_gte_2": len(identity) >= 2,
                "identity_safety_anchor": identity_safe,
                "same_problem_scope_or_rare_anchor": same_problem_scope or bool(rare_identity),
                "cross_candidate_or_14d": len(cids) >= 2 or span_days >= 14,
            },
            "authority": "STAGING_DERIVED_ONLY" if not promotable else "MAY_PROMOTE_TO_TRANSITION_LINEAGE_ONLY",
            "truth_boundary": "Corroborated timing context may become persistent TransitionLineage identity; it cannot certify buyer/WTP/gap/opportunity truth or write Radar C01-C14.",
        }
        hypotheses.append(obj)
        if promotable:
            for atom_id in obj["member_transition_atom_ids"]:
                promotions[atom_id] = {
                    "transition_hypothesis_id": hid,
                    "identity_terms": identity,
                    "driver": driver,
                    "source_families": families,
                    "content_units": units,
                    "span_days": span_days,
                }
    hypotheses.sort(key=lambda x: (0 if x["state"] == "PROMOTABLE" else 1, x["driver"], x["transition_hypothesis_id"]))
    return hypotheses, promotions


def apply_transition_hypothesis_promotions(atoms: Iterable[Mapping[str, Any]], promotions: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in atoms:
        atom = dict(raw)
        aid = clean(atom.get("transition_atom_id"))
        p = promotions.get(aid)
        if p:
            hid = clean(p.get("transition_hypothesis_id"))
            terms = [clean(x) for x in (p.get("identity_terms") or []) if clean(x)]
            atom.update({
                "lineage_eligible": True,
                "independence_eligible": True,
                "support": True,
                "identity_quality": "CORROBORATED_CONTEXT_PROMOTION",
                "admission_reason": "MULTI_SOURCE_SPECIFIC_TRANSITION_HYPOTHESIS",
                "transition_hypothesis_id": hid,
                "hypothesis_identity_terms": terms,
                "subject": " | ".join(terms[:6]),
                "subject_derived": True,
                "transition_key": f"hypothesis:{hid}",
                "truth_boundary": "Promoted by multi-source specific TransitionHypothesis. Authority is persistent transition identity only; no Radar claim or commercial truth write.",
            })
        out.append(atom)
    return out


def _problem_terms(pl: Mapping[str, Any]) -> set[str]:
    values: list[Any] = [pl.get("representative_title"), pl.get("representative_problem")]
    profile = pl.get("identity_profile") if isinstance(pl.get("identity_profile"), Mapping) else {}
    for key in ("actor", "actor_category", "task", "object", "failure_mode", "problem_statement", "title"):
        values.append(profile.get(key))
    values.extend(pl.get("actors") or [])
    values.extend(pl.get("contexts") or [])
    values.extend(pl.get("objects") or [])
    terms: set[str] = set()
    for value in values:
        terms.update(identity_terms(value))
    return terms


def _transition_anchor_terms(tl: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for value in tl.get("explicit_subjects") or []:
        out.update(identity_terms(value))
    for value in tl.get("hypothesis_identity_terms") or []:
        out.update(identity_terms(value))
    if not out:
        # Direct-pair lineages may be subjectless; retain only a very small representative
        # identity to create a research hypothesis, never an intersection.
        for value in tl.get("identity_terms") or []:
            t = clean(value).lower()
            if t and t not in _IDENTITY_STOP:
                out.add(t)
    return out


def build_structural_bridge_hypotheses(
    problem_lineages: Iterable[Mapping[str, Any]],
    transition_lineages: Iterable[Mapping[str, Any]],
    intersections: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Generate bounded research targets without pretending a semantic bridge is truth.

    StructuralIntersection remains evidence-gated. This layer exists specifically to avoid
    the G2 failure mode where high precision can yield zero intersections and therefore no
    targeted path to improve recall.
    """
    pls = [dict(x) for x in problem_lineages]
    tls = [dict(x) for x in transition_lineages]
    existing_pairs = {(clean(x.get("problem_lineage_id")), clean(x.get("transition_lineage_id"))) for x in intersections}
    term_to_tl: dict[str, set[str]] = defaultdict(set)
    tl_map: dict[str, dict[str, Any]] = {}
    anchors: dict[str, set[str]] = {}
    for tl in tls:
        tlid = clean(tl.get("transition_lineage_id"))
        if not tlid or normalize_state(tl.get("state")) not in {"SUPPORTED", "PARTIAL"}:
            continue
        aa = _transition_anchor_terms(tl)
        if not aa:
            continue
        tl_map[tlid] = tl
        anchors[tlid] = aa
        for term in aa:
            term_to_tl[term].add(tlid)

    out: list[dict[str, Any]] = []
    for pl in pls:
        plid = clean(pl.get("lineage_id"))
        if not plid or normalize_state(pl.get("persistence_state")) not in {"SUPPORTED", "PARTIAL"}:
            continue
        pterms = _problem_terms(pl)
        candidate_tl: set[str] = set()
        for term in pterms:
            candidate_tl.update(term_to_tl.get(term, set()))
        claims = pl.get("claim_states") if isinstance(pl.get("claim_states"), Mapping) else {}
        for tlid in sorted(candidate_tl):
            if (plid, tlid) in existing_pairs:
                continue
            tl = tl_map[tlid]
            aterms = anchors[tlid]
            shared = sorted(pterms & aterms)
            overlap = dice(pterms, aterms)
            if not shared or overlap < 0.12:
                continue
            score = 0.0
            score += min(0.48, overlap * 0.80)
            score += 0.14 if normalize_state(tl.get("state")) == "SUPPORTED" else 0.08
            score += 0.13 if normalize_state(pl.get("persistence_state")) == "SUPPORTED" else 0.07
            score += 0.10 if normalize_state(claims.get("C07")) == "SUPPORTED" else 0.0
            score += 0.08 if int(pl.get("workaround_level", 0) or 0) >= 2 else 0.0
            score += 0.07 if normalize_state(claims.get("C03")) == "SUPPORTED" else 0.0
            score = min(1.0, score)
            # This threshold creates a research target, not structural truth.
            if score < 0.42:
                continue
            cids = sorted({int(x) for x in (pl.get("member_candidate_ids") or []) if str(x).isdigit()} | {int(x) for x in (tl.get("member_candidate_ids") or []) if str(x).isdigit()})
            bid = "bh_" + stable_hash(plid, tlid, shared, length=22)
            out.append({
                "structural_bridge_hypothesis_id": bid,
                "problem_lineage_id": plid,
                "transition_lineage_id": tlid,
                "state": "RESEARCH_REQUIRED",
                "bridge_score": round(score, 4),
                "shared_identity_terms": shared[:12],
                "problem_persistence_state": normalize_state(pl.get("persistence_state")),
                "transition_state": normalize_state(tl.get("state")),
                "transition_driver": clean(tl.get("driver")).upper(),
                "member_candidate_ids": cids[:32],
                "why_candidate": [
                    "SPECIFIC_IDENTITY_OVERLAP",
                    "PERSISTENT_PROBLEM" if normalize_state(pl.get("persistence_state")) == "SUPPORTED" else "FORMING_PROBLEM",
                    "SUPPORTED_TRANSITION" if normalize_state(tl.get("state")) == "SUPPORTED" else "FORMING_TRANSITION",
                ],
                "required_evidence": "Find direct evidence that this specific transition changes/exposes the problem or makes the inherited system mismatch economically important.",
                "authority": "RESEARCH_TARGET_ONLY_NOT_STRUCTURAL_INTERSECTION",
                "truth_boundary": "Semantic/identity overlap is a retrieval hypothesis only. It cannot create StructuralIntersection or OpportunityThesis without validated bridge evidence.",
            })
    out.sort(key=lambda x: (-float(x.get("bridge_score", 0) or 0), x["structural_bridge_hypothesis_id"]))
    return out[:250]


def build_prethesis_research_questions(
    transition_hypotheses: Iterable[Mapping[str, Any]],
    bridge_hypotheses: Iterable[Mapping[str, Any]],
    previous_research: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for h in transition_hypotheses:
        if clean(h.get("state")) != "CORROBORATING":
            continue
        hid = clean(h.get("transition_hypothesis_id"))
        qid = "rq_" + stable_hash("transition_hypothesis", hid, length=22)
        old = previous_research.get(qid) or {}
        attempts = int(old.get("attempts", 0) or 0)
        redundancy = 1.0 / (1.0 + 0.40 * attempts)
        base = 1.35 + 0.12 * min(3, int(h.get("independent_source_families", 0) or 0))
        rows.append({
            "research_question_id": qid,
            "target_type": "TRANSITION_HYPOTHESIS",
            "target_id": hid,
            "thesis_id": None,
            "problem_lineage_id": None,
            "member_candidate_ids": list(h.get("member_candidate_ids") or []),
            "dimension": "transition_identity",
            "state": "PARTIAL",
            "fatal_gate": False,
            "voi": round(base * redundancy, 6),
            "source_group": "timing",
            "action": "Find another independent, time-separated or cross-actor source that confirms the same specific structural transition identity.",
            "attempts": attempts,
            "redundancy_penalty": round(redundancy, 4),
            "status": "OPEN",
            "recency_factor_used": False,
            "truth_boundary": "Pre-thesis research only; validated evidence must still enter the Radar/evidence pipeline before any atomic claim changes.",
        })
    for b in bridge_hypotheses:
        bid = clean(b.get("structural_bridge_hypothesis_id"))
        qid = "rq_" + stable_hash("structural_bridge", bid, length=22)
        old = previous_research.get(qid) or {}
        attempts = int(old.get("attempts", 0) or 0)
        redundancy = 1.0 / (1.0 + 0.40 * attempts)
        score = float(b.get("bridge_score", 0) or 0)
        rows.append({
            "research_question_id": qid,
            "target_type": "STRUCTURAL_BRIDGE_HYPOTHESIS",
            "target_id": bid,
            "thesis_id": None,
            "problem_lineage_id": b.get("problem_lineage_id"),
            "transition_lineage_id": b.get("transition_lineage_id"),
            "member_candidate_ids": list(b.get("member_candidate_ids") or []),
            "dimension": "system_mismatch_bridge",
            "state": "UNKNOWN",
            "fatal_gate": True,
            "voi": round((1.55 + 1.25 * score) * redundancy, 6),
            "source_group": "timing",
            "action": clean(b.get("required_evidence")),
            "attempts": attempts,
            "redundancy_penalty": round(redundancy, 4),
            "status": "OPEN",
            "recency_factor_used": False,
            "truth_boundary": "Bridge research target only; semantic overlap cannot create a StructuralIntersection.",
        })
    rows.sort(key=lambda x: (-float(x.get("voi", 0) or 0), 0 if x.get("fatal_gate") else 1, clean(x.get("research_question_id"))))
    return rows


def thesis_lifecycle_state(thesis: Mapping[str, Any]) -> str:
    if clean(thesis.get("death_state")):
        return "DEAD"
    z = clean(thesis.get("zip2_readiness"))
    c = clean(thesis.get("classification"))
    if c == "MARKET_VALIDATED_TESTED_OFFER":
        return "MARKET_VALIDATED"
    if z == "ZIP2_HIGH_CONVICTION":
        return "ZIP2_HIGH_CONVICTION"
    if z == "ZIP2_CANDIDATE":
        return "ZIP2_CANDIDATE"
    if c in {"STRUCTURAL_HIGH_CONVICTION", "FOUNDER_TEST_READY", "EMERGING_STRUCTURAL"}:
        return c
    if c in {"PERSISTENT_COMMERCIAL_WEDGE", "LEAD_USER_WEDGE"}:
        return c
    return "FORMING"


def evolve_thesis_lifecycle(obj: dict[str, Any], old: Mapping[str, Any] | None, *, changed_at: str) -> dict[str, Any]:
    old = dict(old or {})
    state = thesis_lifecycle_state(obj)
    old_state = clean(old.get("lifecycle_state")) or None
    history = [dict(x) for x in (old.get("lifecycle_history") or []) if isinstance(x, Mapping)][-24:]
    if old_state != state:
        kind = "CREATED" if old_state is None else ("REVIVED" if old_state == "DEAD" and state != "DEAD" else ("DIED" if old_state != "DEAD" and state == "DEAD" else "STATE_CHANGED"))
        history.append({
            "event": kind,
            "from": old_state,
            "to": state,
            "classification": clean(obj.get("classification")),
            "zip2_readiness": clean(obj.get("zip2_readiness")),
            "death_state": clean(obj.get("death_state")) or None,
            "changed_at": changed_at,
        })
    obj["lifecycle_state"] = state
    obj["lifecycle_history"] = history
    obj["revival_count"] = sum(1 for x in history if clean(x.get("event")) == "REVIVED")
    obj["death_count"] = sum(1 for x in history if clean(x.get("event")) == "DIED")
    return obj


def static_acceptance() -> dict[str, bool]:
    atoms = [
        {"transition_atom_id":"a1","candidate_id":1,"driver":"TECHNOLOGY","text":"Coding agents execute repository-wide changes while human verification remains manual","verified":True,"lineage_eligible":False,"source_class":"RADAR_C12_VALIDATED","source_family":"news:a","content_fingerprint":"u1","valid_at":"2025-01-01T00:00:00Z"},
        {"transition_atom_id":"a2","candidate_id":2,"driver":"TECHNOLOGY","text":"Coding agents now execute repository-wide tasks while manual verification remains the bottleneck","verified":True,"lineage_eligible":False,"source_class":"VERIFIED_CANDIDATE_TRANSITION","source_family":"community:b","content_fingerprint":"u2","valid_at":"2025-02-01T00:00:00Z"},
        {"transition_atom_id":"noise1","candidate_id":3,"driver":"TECHNOLOGY","text":"AI adoption is increasing and the market is changing quickly","verified":True,"lineage_eligible":False,"source_class":"RADAR_C12_VALIDATED","source_family":"news:n1","content_fingerprint":"n1","valid_at":"2025-01-01T00:00:00Z"},
        {"transition_atom_id":"noise2","candidate_id":4,"driver":"TECHNOLOGY","text":"AI adoption continues to grow across many companies and workflows","verified":True,"lineage_eligible":False,"source_class":"RADAR_C12_VALIDATED","source_family":"news:n2","content_fingerprint":"n2","valid_at":"2025-02-01T00:00:00Z"},
    ]
    hyps, promo = build_transition_hypotheses(atoms)
    promoted = apply_transition_hypothesis_promotions(atoms, promo)
    promoted_ids = {x["transition_atom_id"] for x in promoted if x.get("lineage_eligible")}
    broad=[]
    for i in range(12):
        broad.append({"transition_atom_id":f"b{i}","candidate_id":100+i,"driver":"TECHNOLOGY","text":"Autonomous coding agents execute repository workflows while manual review bottlenecks persist","verified":True,"lineage_eligible":False,"source_class":"RADAR_C12_VALIDATED","source_family":f"broad:{i}","content_fingerprint":f"bc:{i}","valid_at":"2025-01-01T00:00:00Z"})
    broad_h,broad_p=build_transition_hypotheses(broad)
    scoped_h,scoped_p=build_transition_hypotheses(broad,candidate_to_problem_lineage={100+i:"pl_scope" for i in range(12)})
    pl = {"lineage_id":"pl1","persistence_state":"SUPPORTED","representative_title":"Coding agent completion reports require manual verification","representative_problem":"coding agents report completion incorrectly and require manual verification","identity_profile":{"task":"coding agent verification","object":"agent report","failure_mode":"wrong completion report"},"claim_states":{"C03":"SUPPORTED","C07":"SUPPORTED"},"workaround_level":2,"member_candidate_ids":[10]}
    tl = {"transition_lineage_id":"tl1","state":"SUPPORTED","driver":"TECHNOLOGY","hypothesis_identity_terms":["coding","agents","verification"],"member_candidate_ids":[20]}
    bridges = build_structural_bridge_hypotheses([pl],[tl],[])
    return {
        "independent_specific_context_promotes": {"a1","a2"}.issubset(promoted_ids),
        "generic_timing_noise_not_promoted": "noise1" not in promoted_ids and "noise2" not in promoted_ids,
        "transition_hypothesis_materialized": any(x.get("state")=="PROMOTABLE" for x in hyps),
        "broad_cross_problem_context_not_promoted": not broad_h and not broad_p,
        "same_problem_scope_can_corroborate_transition": bool(scoped_h) and len(scoped_p)==12,
        "bridge_hypothesis_is_research_only": bool(bridges) and all(x.get("authority")=="RESEARCH_TARGET_ONLY_NOT_STRUCTURAL_INTERSECTION" for x in bridges),
        "bridge_research_question_without_thesis": bool(build_prethesis_research_questions([],bridges,{})),
    }


def zip2_gate_report(thesis: Mapping[str, Any]) -> dict[str, Any]:
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    def state(key: str) -> str:
        row = dims.get(key) if isinstance(dims, Mapping) else None
        return normalize_state(row.get("state")) if isinstance(row, Mapping) else "UNKNOWN"
    pillars = {
        "persistent_problem": state("problem_persistence"),
        "structural_transition": state("transition_strength"),
        "system_mismatch": state("system_mismatch"),
        "economic_necessity": state("economic_materiality"),
        "buyer_formation": state("buyer_formation"),
        "durable_gap": state("gap_durability"),
        "new_entrant_capture": state("captureability"),
        "distribution_leverage": state("distribution_leverage"),
        "asset_accessibility": state("asset_accessibility"),
        "expansion_surface": state("expansion_surface"),
    }
    mandatory = ("persistent_problem","structural_transition","system_mismatch","economic_necessity","buyer_formation","durable_gap","new_entrant_capture")
    blockers = [k for k in mandatory if pillars[k] == "REFUTED"]
    unknowns = [k for k in mandatory if pillars[k] in {"UNKNOWN","INSUFFICIENT","CONFLICTED"}]
    partials = [k for k in mandatory if pillars[k] == "PARTIAL"]
    strengths = [k for k,v in pillars.items() if v == "SUPPORTED"]
    return {
        "model": "GATE_PLUS_VECTOR_NOT_AVERAGE_SCORE",
        "mandatory_pillars": list(mandatory),
        "pillar_states": pillars,
        "fatal_blockers": blockers,
        "decision_critical_unknowns": unknowns,
        "partial_pillars": partials,
        "supported_pillars": strengths,
        "gate_pass": not blockers and not unknowns and not partials,
        "near_zip2": not blockers and len(unknowns) + len(partials) <= 2 and pillars["persistent_problem"] == "SUPPORTED" and pillars["economic_necessity"] == "SUPPORTED",
        "truth_boundary": "Zip2 gate summarizes evidence-owned dimensions; it cannot convert UNKNOWN/PARTIAL into support and is not a weighted average.",
    }
