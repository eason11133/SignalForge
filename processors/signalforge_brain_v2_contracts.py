from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "signalforge-brain-v2-contracts-full-system-g3-structural-recall"
SCHEMA_VERSION = "signalforge-brain-v2-full-system-g3"

CLAIM_STATES = {"SUPPORTED", "PARTIAL", "INSUFFICIENT", "UNKNOWN", "REFUTED", "CONFLICTED"}
POSITIVE = {"SUPPORTED"}
OPEN_STATES = {"PARTIAL", "INSUFFICIENT", "UNKNOWN", "CONFLICTED"}

GENERIC = {
    "the","and","for","with","from","that","this","then","than","when","where","what","which","while",
    "user","users","using","used","use","system","systems","software","product","products","tool","tools",
    "problem","problems","issue","issues","work","working","workflow","task","tasks","data","code","model",
    "models","ai","llm","agent","agents","application","applications","service","services","need","needs",
    "cannot","cant","doesnt","does","have","has","had","into","about","more","very","some","other",
    "company","companies","business","businesses","developer","developers","people","thing","things","current",
    "new","now","make","makes","made","making","get","gets","got","want","wants","really","also","like",
}
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.#:/-]{1,}", re.I)

DRIVER_PATTERNS = {
    "REGULATION": re.compile(r"\b(regulat|compliance|law|mandate|policy|standard|audit requirement)\w*\b", re.I),
    "COST": re.compile(r"\b(cost|price|cheaper|afford|commodity|commoditi|inference cost|compute cost|falling cost)\w*\b", re.I),
    "DISTRIBUTION": re.compile(r"\b(api|platform|marketplace|distribution|channel|app store|browser|web|mobile|integration)\w*\b", re.I),
    "BEHAVIOR": re.compile(r"\b(adoption|users? (?:start|shift|move)|behavior|behaviour|workflow shift|trust|usage)\w*\b", re.I),
    "INSTITUTION": re.compile(r"\b(team|department|governance|procurement|headcount|role|organization|organisation|enterprise adoption)\w*\b", re.I),
    "BUSINESS_MODEL": re.compile(r"\b(subscription|usage[- ]based|outcome[- ]based|pricing model|business model|seat[- ]based|monetiz)\w*\b", re.I),
    "TECHNOLOGY": re.compile(r"\b(release|launch|capability|automation|autonomous|agentic|open source|open-source|model quality|context window|multimodal|inference|hardware|gpu|api)\w*\b", re.I),
}

W6 = re.compile(r"\b(dedicated (?:role|team)|added headcount|allocated (?:a )?budget|budgeted for|paid (?:a )?vendor|signed (?:a )?contract|contracted (?:a )?vendor|paid pilot|procurement|we hired|hired (?:a|an) |annual spend|(?:spend|spent|pay|paid|budget(?:ed)?)\s+(?:about\s+|around\s+|up to\s+)?\$\s*\d+(?:[,\.]\d+)*)\b", re.I)
W5 = re.compile(r"\b(internal tool|custom tool|custom script|wrote (?:a )?script|built (?:a |an )?(?:tool|service|app|bot)|developed (?:our|an?)|homegrown|in-house tool)\b", re.I)
W4 = re.compile(r"\b(spreadsheet|zapier|make\.com|airtable|notion|automation|macro|prompt chain|prompt workflow|workflow automation|excel)\b", re.I)
W3 = re.compile(r"\b(stitch|glue|chain|several tools|multiple tools|tool stack|combine|connect .* and .*|using .* plus .*)\b", re.I)
W2 = re.compile(r"\b(manual|manually|by hand|copy[- ]?paste|re[- ]?enter|retype|spreadsheet workaround|check every|review every)\b", re.I)
W1 = re.compile(r"\b(workaround|avoid|instead|changed (?:our|my) process|extra step|double check|double-check)\b", re.I)

DIMENSION_KEYS = (
    "problem_persistence",
    "transition_strength",
    "system_mismatch",
    "economic_materiality",
    "workaround_intensity",
    "buyer_formation",
    "gap_durability",
    "asset_accessibility",
    "distribution_leverage",
    "incumbent_response_power",
    "captureability",
    "expansion_surface",
)

# Fatal means the thesis cannot advance while REFUTED. Unknown does not equal false.
DIMENSION_POLICY = {
    "problem_persistence": {"fatal": True, "flip_weight": 1.00, "source_group": "problem"},
    "transition_strength": {"fatal": False, "flip_weight": 0.93, "source_group": "timing"},
    "system_mismatch": {"fatal": True, "flip_weight": 1.00, "source_group": "problem"},
    "economic_materiality": {"fatal": True, "flip_weight": 0.96, "source_group": "problem"},
    "workaround_intensity": {"fatal": False, "flip_weight": 0.80, "source_group": "problem"},
    "buyer_formation": {"fatal": True, "flip_weight": 1.00, "source_group": "buyer"},
    "gap_durability": {"fatal": True, "flip_weight": 1.00, "source_group": "market"},
    "asset_accessibility": {"fatal": False, "flip_weight": 0.74, "source_group": "timing"},
    "distribution_leverage": {"fatal": False, "flip_weight": 0.88, "source_group": "buyer"},
    "incumbent_response_power": {"fatal": False, "flip_weight": 0.85, "source_group": "market"},
    "captureability": {"fatal": True, "flip_weight": 0.98, "source_group": "market"},
    "expansion_surface": {"fatal": False, "flip_weight": 0.67, "source_group": "market"},
}

RESEARCH_ACTIONS = {
    "problem_persistence": "Find independent same-problem evidence across time/actors; reject copies and adjacent pains.",
    "transition_strength": "Find independent evidence that the structural change is occurring, diffusing, and persisting.",
    "system_mismatch": "Find direct evidence that the inherited workflow/system is failing because the environment changed.",
    "economic_materiality": "Find direct time, money, risk, revenue, or blocking-cost evidence from affected users.",
    "workaround_intensity": "Find revealed behavior: manual workarounds, tool stitching, custom scripts, internal tools, or allocated budget.",
    "buyer_formation": "Find a named economic buyer with authority and budget aligned to this exact problem; generic hiring is insufficient.",
    "gap_durability": "Test current solutions and counterevidence; determine why the gap remains unresolved and whether that reason persists.",
    "asset_accessibility": "Verify which complementary assets became newly accessible or cheap enough for a new entrant.",
    "distribution_leverage": "Find a credible repeatable path to customers and any existing distribution leverage.",
    "incumbent_response_power": "Assess incumbent data, distribution, bundling, installed-base, regulatory, and subsidy power.",
    "captureability": "Verify execution + distribution + competitive survivability for a new/solo entrant.",
    "expansion_surface": "Find evidence-backed adjacent workflows/value pools reachable after the initial wedge; do not invent TAM.",
}

CLASS_PRIORITY = {
    "MARKET_VALIDATED_TESTED_OFFER": 0,
    "STRUCTURAL_HIGH_CONVICTION": 1,
    "FOUNDER_TEST_READY": 2,
    "EMERGING_STRUCTURAL": 3,
    "PERSISTENT_COMMERCIAL_WEDGE": 4,
    "LEAD_USER_WEDGE": 5,
    "DEAD_OR_INVALIDATED": 9,
}
ZIP2_PRIORITY = {"ZIP2_HIGH_CONVICTION": 0, "ZIP2_CANDIDATE": 1, "NOT_ZIP2_CLASS": 2}


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(*parts: Any, length: int = 24) -> str:
    raw = "|".join(canonical_json(x) if isinstance(x, (dict, list, tuple, set)) else clean(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:length]


def words(v: Any) -> set[str]:
    out: set[str] = set()
    for raw in WORD_RE.findall(clean(v).lower()):
        t = raw.strip("._-/:#")
        if len(t) < 3 or t in GENERIC or re.fullmatch(r"[0-9a-f]{12,}", t):
            continue
        out.add(t)
    return out


def dice(a: Iterable[str], b: Iterable[str]) -> float:
    aa, bb = set(a), set(b)
    if not aa or not bb:
        return 0.0
    return 2.0 * len(aa & bb) / (len(aa) + len(bb))


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    aa, bb = set(a), set(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def normalize_state(value: Any) -> str:
    s = clean(value).upper()
    if s in CLAIM_STATES:
        return s
    if s in {"KNOWN", "TRUE", "PASS", "YES"}:
        return "SUPPORTED"
    if s in {"FALSE", "NO", "FAILED"}:
        return "REFUTED"
    if s in {"PENDING", "UNPROVEN", "NOT_REGISTERED"}:
        return "UNKNOWN"
    return "UNKNOWN"


def aggregate_claim_states(values: Iterable[Any]) -> str:
    vals = [normalize_state(x) for x in values if clean(x)]
    if not vals:
        return "UNKNOWN"
    if "CONFLICTED" in vals or ("SUPPORTED" in vals and "REFUTED" in vals):
        return "CONFLICTED"
    if "SUPPORTED" in vals:
        return "SUPPORTED"
    if vals and all(x == "REFUTED" for x in vals):
        return "REFUTED"
    if "PARTIAL" in vals:
        return "PARTIAL"
    if "INSUFFICIENT" in vals or "REFUTED" in vals:
        return "INSUFFICIENT"
    return "UNKNOWN"


def transition_driver(text: Any) -> str:
    s = clean(text)
    hits = [name for name, pat in DRIVER_PATTERNS.items() if pat.search(s)]
    if not hits:
        return "UNKNOWN"
    for p in ("REGULATION", "COST", "BUSINESS_MODEL", "INSTITUTION", "DISTRIBUTION", "BEHAVIOR", "TECHNOLOGY"):
        if p in hits:
            return p
    return hits[0]


def workaround_level(text: Any, *, validated_budget: bool = False) -> tuple[int, str]:
    s = clean(text)
    if validated_budget or W6.search(s):
        return 6, "W6_DEDICATED_ROLE_BUDGET_VENDOR"
    if W5.search(s):
        return 5, "W5_CUSTOM_SCRIPT_OR_INTERNAL_TOOL"
    if W4.search(s):
        return 4, "W4_STRUCTURED_AUTOMATION_OR_SPREADSHEET"
    if W3.search(s):
        return 3, "W3_TOOL_STITCHING"
    if W2.search(s):
        return 2, "W2_MANUAL_WORKAROUND"
    if W1.search(s):
        return 1, "W1_BEHAVIOR_CHANGE"
    return 0, "W0_COMPLAINT_OR_NO_WORKAROUND"


def _fp(atom: Mapping[str, Any]) -> Mapping[str, Any]:
    x = atom.get("fingerprint")
    return x if isinstance(x, Mapping) else {}


def problem_features(atom: Mapping[str, Any]) -> dict[str, Any]:
    fp = _fp(atom)
    frame = fp.get("need_frame") if isinstance(fp.get("need_frame"), Mapping) else {}
    signature = clean(fp.get("primary_problem_signature") or atom.get("primary_problem_signature"))
    scope_key = clean(fp.get("problem_scope_key") or atom.get("problem_scope_key"))
    descriptor = clean(fp.get("problem_family_descriptor") or atom.get("problem_family_descriptor"))
    target = clean(frame.get("primary_specific_target") or fp.get("primary_specific_target"))
    failure_text = " ".join(clean(x) for x in [atom.get("failure_mode"), atom.get("problem_statement"), atom.get("title")])
    return {
        "actor": words(atom.get("actor") or atom.get("actor_category")),
        "task": words(atom.get("task") or atom.get("workflow")),
        "object": words(atom.get("object")),
        "failure": words(failure_text),
        "signature": signature.lower(),
        "scope_key": scope_key.lower(),
        "descriptor_terms": words(descriptor),
        "specific_target": target.lower(),
    }


def problem_bucket_keys(atom: Mapping[str, Any]) -> list[str]:
    f = problem_features(atom)
    keys: list[str] = []
    if f["specific_target"]:
        keys.append("target:" + f["specific_target"])
    if f["scope_key"]:
        keys.append("scope:" + f["scope_key"])
    if f["signature"]:
        keys.append("sig:" + f["signature"])
    # When both upstream identity anchors exist, different anchors are a hard conflict in
    # same_problem(). Generic task/failure buckets would therefore create quadratic
    # comparisons that can never merge. Keep only the strong buckets in that case.
    if f["scope_key"] and f["signature"]:
        return list(dict.fromkeys(keys))[:12]
    failure = sorted(f["failure"])[:5]
    task = sorted(f["task"])[:3]
    for x in failure:
        keys.append("failure:" + x)
    for x in task:
        keys.append("task:" + x)
    if not keys:
        keys.append("fallback:" + stable_hash(sorted(words(atom.get("problem_statement") or atom.get("title"))), length=12))
    return list(dict.fromkeys(keys))[:12]


def same_problem(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    fa, fb = problem_features(a), problem_features(b)
    if fa["specific_target"] and fb["specific_target"] and fa["specific_target"] != fb["specific_target"]:
        return {"same_problem": False, "score": 0.0, "reasons": ["SPECIFIC_TARGET_CONFLICT"]}
    # Two explicit upstream identity keys disagreeing is strong negative evidence.
    # This prevents generic failure/task vocabulary from merging distinct problem families.
    if (fa["scope_key"] and fb["scope_key"] and fa["scope_key"] != fb["scope_key"]
            and fa["signature"] and fb["signature"] and fa["signature"] != fb["signature"]):
        return {"same_problem": False, "score": 0.0, "reasons": ["STRONG_IDENTITY_KEY_CONFLICT"]}
    if fa["scope_key"] and fa["scope_key"] == fb["scope_key"]:
        failure = dice(fa["failure"], fb["failure"])
        task = dice(fa["task"], fb["task"])
        obj = dice(fa["object"], fb["object"])
        if fa["signature"] and fa["signature"] == fb["signature"]:
            return {"same_problem": True, "score": 1.0, "reasons": ["SAME_PROBLEM_SCOPE_KEY", "SAME_SIGNATURE"]}
        if failure >= 0.12 and (task >= 0.10 or obj >= 0.10):
            return {"same_problem": True, "score": 0.92, "reasons": ["SAME_PROBLEM_SCOPE_KEY", "SEMANTIC_IDENTITY_ANCHOR"]}
        return {"same_problem": False, "score": 0.35, "reasons": ["SCOPE_KEY_WITHOUT_SEMANTIC_IDENTITY"]}
    same_sig = bool(fa["signature"] and fa["signature"] == fb["signature"])
    failure = dice(fa["failure"], fb["failure"])
    task = dice(fa["task"], fb["task"])
    obj = dice(fa["object"], fb["object"])
    descriptor = dice(fa["descriptor_terms"], fb["descriptor_terms"])
    actor = dice(fa["actor"], fb["actor"])
    score = 0.37 * failure + 0.22 * task + 0.18 * obj + 0.13 * descriptor + 0.05 * actor + (0.18 if same_sig else 0.0)
    structural = same_sig or (failure >= 0.18 and (task >= 0.15 or obj >= 0.15 or descriptor >= 0.20))
    same = bool(structural and score >= 0.50)
    reasons: list[str] = []
    if same_sig: reasons.append("SAME_SIGNATURE")
    if failure >= 0.18: reasons.append("FAILURE_OVERLAP")
    if task >= 0.15: reasons.append("TASK_OVERLAP")
    if obj >= 0.15: reasons.append("OBJECT_OVERLAP")
    if descriptor >= 0.20: reasons.append("DESCRIPTOR_OVERLAP")
    if not structural: reasons.append("NO_STRUCTURAL_IDENTITY")
    return {"same_problem": same, "score": round(max(0.0, min(1.0, score)), 4), "reasons": reasons}


def transition_features(atom: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "driver": clean(atom.get("driver")).upper() or "UNKNOWN",
        "terms": words(atom.get("text")),
        "transition_key": clean(atom.get("transition_key")),
        "subject_terms": words(atom.get("subject") or atom.get("mechanism")),
        "subject_explicit": bool(atom.get("subject_explicit")),
        "direct_link": bool(atom.get("direct_problem_transition_link")),
        "identity_quality": clean(atom.get("identity_quality")).upper(),
    }


def transition_bucket_keys(atom: Mapping[str, Any]) -> list[str]:
    """Precision-first candidate buckets for persistent transition identity.

    Generic transition prose is deliberately not a primary identity anchor. Explicit
    subjects (a named platform/regulation/technology/cost driver) own the strongest
    buckets; direct pair evidence without a subject gets only a narrow semantic fallback.
    """
    f = transition_features(atom)
    keys = ["driver:" + f["driver"]]
    if f["subject_explicit"] and f["subject_terms"]:
        for x in sorted(f["subject_terms"])[:8]:
            keys.append("subject:" + x)
    elif f["direct_link"]:
        for x in sorted(f["terms"])[:5]:
            keys.append("direct-term:" + x)
    if f["transition_key"]:
        keys.append("key:" + f["transition_key"] )
    return list(dict.fromkeys(keys))[:12]


def same_transition(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Conservative persistent-transition identity.

    R2 allowed broad semantic overlap to create a TransitionLineage. On the real corpus
    that turned almost every C12/why-now record into a persistent structural object. G2
    requires an identity anchor: explicit subject overlap, an exact evidence identity, or
    two direct pair records with unusually strong semantic agreement.
    """
    fa, fb = transition_features(a), transition_features(b)
    if fa["driver"] != "UNKNOWN" and fb["driver"] != "UNKNOWN" and fa["driver"] != fb["driver"]:
        return {"same_transition": False, "score": 0.0, "reasons": ["DRIVER_CONFLICT"]}
    subject = dice(fa["subject_terms"], fb["subject_terms"])
    overlap = dice(fa["terms"], fb["terms"])
    if fa["subject_explicit"] and fb["subject_explicit"]:
        if not fa["subject_terms"] or not fb["subject_terms"] or subject == 0.0:
            return {"same_transition": False, "score": 0.0, "reasons": ["EXPLICIT_SUBJECT_CONFLICT"]}
        same = bool(subject >= 0.34 and overlap >= 0.12)
        return {"same_transition": same, "score": round(0.72*subject + 0.28*overlap,4), "reasons": ["EXPLICIT_SUBJECT_OVERLAP"] if same else ["SUBJECT_OVERLAP_WITHOUT_EVENT_IDENTITY"]}
    if fa["transition_key"] and fa["transition_key"] == fb["transition_key"]:
        return {"same_transition": True, "score": 1.0, "reasons": ["SAME_TRANSITION_KEY"]}
    # One explicit subject and one unanchored context row must never merge by generic prose.
    if fa["subject_explicit"] != fb["subject_explicit"]:
        return {"same_transition": False, "score": 0.0, "reasons": ["ASYMMETRIC_TRANSITION_IDENTITY"]}
    # Subjectless rows can only establish cross-source identity when both are direct links
    # and their event language is exceptionally close.
    if fa["direct_link"] and fb["direct_link"] and overlap >= 0.58:
        return {"same_transition": True, "score": round(overlap,4), "reasons": ["DIRECT_PAIR_HIGH_SEMANTIC_IDENTITY"]}
    return {"same_transition": False, "score": round(overlap,4), "reasons": ["NO_PERSISTENT_TRANSITION_IDENTITY_ANCHOR"]}


def dimension(state: Any, *, basis: str, evidence: Iterable[Any] | None = None, metrics: Mapping[str, Any] | None = None, owner: str = "BRAIN_DERIVED") -> dict[str, Any]:
    return {
        "state": normalize_state(state),
        "basis": clean(basis),
        "evidence_refs": [clean(x) for x in (evidence or []) if clean(x)][:32],
        "metrics": dict(metrics or {}),
        "truth_owner": owner,
    }


def dim_state(dimensions: Mapping[str, Any], key: str) -> str:
    row = dimensions.get(key) if isinstance(dimensions, Mapping) else None
    return normalize_state(row.get("state")) if isinstance(row, Mapping) else "UNKNOWN"


def intersection_gate(
    *,
    problem_lineage: Mapping[str, Any],
    transition_lineage: Mapping[str, Any],
    direct_link_count: int,
    direct_independent_units: int = 0,
    direct_independent_families: int = 0,
    shared_candidate_count: int,
    c07_state: str,
    workaround_level_value: int,
) -> dict[str, Any]:
    """Adjudicate the *pair* between a problem lineage and transition lineage.

    Global TransitionLineage strength cannot be borrowed as proof that the change causes or
    exposes this particular problem.  A single verified pair link is useful but remains
    PARTIAL; SUPPORTED mismatch requires two independent direct pair units/families.
    This prevents evidence accumulated elsewhere in a broad transition lineage from leaking
    into every problem it happens to touch.
    """
    p = normalize_state(problem_lineage.get("persistence_state"))
    t = normalize_state(transition_lineage.get("state"))
    if p == "REFUTED" or t == "REFUTED" or shared_candidate_count <= 0:
        return {"state": "REFUTED", "eligibility": "REJECTED", "reasons": ["NO_VALID_STRUCTURAL_INTERSECTION"]}
    if direct_independent_units >= 2 and direct_independent_families >= 2 and t in {"SUPPORTED", "PARTIAL"}:
        return {
            "state": "SUPPORTED",
            "eligibility": "DIRECT_MULTI_SOURCE_LINKED",
            "reasons": ["INDEPENDENT_DIRECT_PROBLEM_TRANSITION_LINKS"],
        }
    if direct_link_count > 0 and t in {"SUPPORTED", "PARTIAL"}:
        return {
            "state": "PARTIAL",
            "eligibility": "DIRECT_SINGLE_SOURCE_LINKED",
            "reasons": ["DIRECT_PROBLEM_TRANSITION_LINK_SINGLE_SOURCE"],
        }
    if t == "SUPPORTED" and normalize_state(c07_state) == "SUPPORTED" and workaround_level_value >= 2:
        return {"state": "PARTIAL", "eligibility": "CORROBORATED_MISMATCH", "reasons": ["SUPPORTED_TRANSITION", "DURABLE_GAP", "REVEALED_WORKAROUND"]}
    return {"state": "INSUFFICIENT", "eligibility": "CONTEXT_ONLY", "reasons": ["SHARED_CONTEXT_WITHOUT_MISMATCH_PROOF"]}


def death_state(dimensions: Mapping[str, Any], *, transition_present: bool) -> str | None:
    if dim_state(dimensions, "problem_persistence") == "REFUTED": return "TEMPORARY_SPIKE"
    if dim_state(dimensions, "system_mismatch") == "REFUTED": return "NO_STRUCTURAL_MISMATCH"
    if dim_state(dimensions, "economic_materiality") == "REFUTED": return "ECONOMICALLY_TRIVIAL"
    if dim_state(dimensions, "buyer_formation") == "REFUTED": return "NO_BUYER"
    if dim_state(dimensions, "gap_durability") == "REFUTED": return "SOLVED_OR_NO_DURABLE_GAP"
    if transition_present and dim_state(dimensions, "transition_strength") == "REFUTED": return "TRANSITION_STALLED"
    if dim_state(dimensions, "captureability") == "REFUTED": return "NON_CAPTUREABLE"
    # C13 semantics are survivability: REFUTED means incumbent/competition power defeated the thesis.
    if dim_state(dimensions, "incumbent_response_power") == "REFUTED": return "ABSORBED_OR_INCUMBENT_DOMINATED"
    return None


def classify_thesis(
    dimensions: Mapping[str, Any],
    *,
    transition_present: bool,
    workaround_level_value: int,
    market_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    market_validation = dict(market_validation or {})
    dead = death_state(dimensions, transition_present=transition_present)
    if dead:
        return {"classification": "DEAD_OR_INVALIDATED", "zip2_readiness": "NOT_ZIP2_CLASS", "death_state": dead}

    p = dim_state(dimensions, "problem_persistence")
    t = dim_state(dimensions, "transition_strength")
    m = dim_state(dimensions, "system_mismatch")
    e = dim_state(dimensions, "economic_materiality")
    b = dim_state(dimensions, "buyer_formation")
    g = dim_state(dimensions, "gap_durability")
    a = dim_state(dimensions, "asset_accessibility")
    d = dim_state(dimensions, "distribution_leverage")
    c = dim_state(dimensions, "captureability")
    x = dim_state(dimensions, "expansion_surface")

    paid = bool(market_validation.get("paid_tested_offer_observed"))
    if paid:
        cls = "MARKET_VALIDATED_TESTED_OFFER"
    elif transition_present and all(v == "SUPPORTED" for v in (p, t, m, e, b, g, c)) and (a == "SUPPORTED" or d == "SUPPORTED") and x in {"SUPPORTED", "PARTIAL"}:
        cls = "STRUCTURAL_HIGH_CONVICTION"
    elif p == "SUPPORTED" and e == "SUPPORTED" and b == "SUPPORTED" and g == "SUPPORTED" and c != "REFUTED":
        cls = "FOUNDER_TEST_READY"
    elif transition_present and p in {"SUPPORTED", "PARTIAL"} and t in {"SUPPORTED", "PARTIAL"} and m in {"SUPPORTED", "PARTIAL"} and g != "REFUTED":
        cls = "EMERGING_STRUCTURAL"
    elif not transition_present and p == "SUPPORTED" and b == "SUPPORTED" and g == "SUPPORTED":
        cls = "PERSISTENT_COMMERCIAL_WEDGE"
    elif not transition_present and p in {"SUPPORTED", "PARTIAL"} and workaround_level_value >= 5 and e == "SUPPORTED":
        cls = "LEAD_USER_WEDGE"
    else:
        # A problem space is not an opportunity thesis. Callers should normally not materialize it.
        cls = "EMERGING_STRUCTURAL" if transition_present else "LEAD_USER_WEDGE"

    zip2_candidate = bool(
        transition_present
        and p == "SUPPORTED"
        and t in {"SUPPORTED", "PARTIAL"}
        and m in {"SUPPORTED", "PARTIAL"}
        and e == "SUPPORTED"
        and b == "SUPPORTED"
        and g == "SUPPORTED"
        and c != "REFUTED"
    )
    zip2_high = bool(
        zip2_candidate and t == "SUPPORTED" and m == "SUPPORTED" and c == "SUPPORTED"
        and d == "SUPPORTED" and a in {"SUPPORTED", "PARTIAL"} and x in {"SUPPORTED", "PARTIAL"}
    )
    return {
        "classification": cls,
        "zip2_readiness": "ZIP2_HIGH_CONVICTION" if zip2_high else ("ZIP2_CANDIDATE" if zip2_candidate else "NOT_ZIP2_CLASS"),
        "death_state": None,
    }


def research_plan(
    dimensions: Mapping[str, Any],
    *,
    existing_attempts: Mapping[str, int] | None = None,
    estimated_costs: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    existing_attempts = dict(existing_attempts or {})
    estimated_costs = dict(estimated_costs or {})
    rows: list[dict[str, Any]] = []
    for key in DIMENSION_KEYS:
        state = dim_state(dimensions, key)
        if state in {"SUPPORTED", "REFUTED"}:
            continue
        policy = DIMENSION_POLICY[key]
        attempts = max(0, int(existing_attempts.get(key, 0) or 0))
        cost = max(0.15, float(estimated_costs.get(key, 1.0) or 1.0))
        uncertainty = {"UNKNOWN": 1.0, "CONFLICTED": 0.98, "INSUFFICIENT": 0.82, "PARTIAL": 0.58}.get(state, 0.8)
        redundancy = 1.0 / (1.0 + 0.40 * attempts)
        fatal_multiplier = 1.85 if policy["fatal"] else 1.0
        # Value-of-information: chance to flip a consequential decision, divided by effort.
        voi = policy["flip_weight"] * uncertainty * redundancy * fatal_multiplier / math.sqrt(cost)
        rows.append({
            "dimension": key,
            "state": state,
            "fatal_gate": bool(policy["fatal"]),
            "decision_flip_weight": policy["flip_weight"],
            "uncertainty": uncertainty,
            "attempts": attempts,
            "redundancy_penalty": round(redundancy, 4),
            "estimated_relative_cost": round(cost, 3),
            "voi": round(voi, 6),
            "source_group": policy["source_group"],
            "action": RESEARCH_ACTIONS[key],
            "authority_effect": "PLANNING_ONLY_NO_ATOMIC_CLAIM_STATE_WRITE",
            "recency_factor_used": False,
        })
    rows.sort(key=lambda r: (-r["voi"], 0 if r["fatal_gate"] else 1, r["dimension"]))
    for i, row in enumerate(rows, 1):
        row["priority_rank"] = i
    return rows


def portfolio_sort_key(thesis: Mapping[str, Any]) -> tuple:
    dims = thesis.get("dimensions") if isinstance(thesis.get("dimensions"), Mapping) else {}
    supported = sum(1 for k in DIMENSION_KEYS if dim_state(dims, k) == "SUPPORTED")
    pmetrics = ((dims.get("problem_persistence") or {}).get("metrics") or {}) if isinstance(dims.get("problem_persistence"), Mapping) else {}
    return (
        CLASS_PRIORITY.get(clean(thesis.get("classification")), 8),
        ZIP2_PRIORITY.get(clean(thesis.get("zip2_readiness")), 3),
        -supported,
        -int(pmetrics.get("independent_families", 0) or 0),
        -int(pmetrics.get("actor_spread", 0) or 0),
        -int(thesis.get("workaround_level", 0) or 0),
        -min(int(pmetrics.get("span_days", 0) or 0), 3650),
        clean(thesis.get("thesis_id")),
    )


def semantic_fingerprint(obj: Mapping[str, Any], *, ignore: Iterable[str] = ()) -> str:
    ignored = set(ignore)
    payload = {k: v for k, v in obj.items() if k not in ignored}
    return stable_hash(payload, length=40)


def meaningful_change(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> dict[str, Any] | None:
    if before is None:
        return {"change_type": "CREATED", "before": None, "after_fingerprint": semantic_fingerprint(after, ignore={"updated_at","last_observed_at","last_checked_at"})}
    ignore = {"revision", "updated_at", "last_checked_at", "last_observed_at", "refreshed_at", "elapsed_ms", "portfolio_rank", "last_meaningful_update_at"}
    b = semantic_fingerprint(before, ignore=ignore)
    a = semantic_fingerprint(after, ignore=ignore)
    if a == b:
        return None
    return {"change_type": "MEANINGFUL_UPDATE", "before_fingerprint": b, "after_fingerprint": a}


def static_acceptance() -> dict[str, bool]:
    actual = {
        "title": "Claude Code assumptions lead to reporting errors",
        "task": "run coding agent and report work results",
        "object": "Claude Code report",
        "failure_mode": "hidden assumptions cause wrong reporting numbers",
        "problem_statement": "Agent makes assumptions and reports incorrect results",
        "fingerprint": {},
    }
    same = {
        "title": "Coding agent assumptions produce incorrect status reports",
        "task": "run coding agent and report results",
        "object": "agent report",
        "failure_mode": "assumptions produce wrong reported results",
        "problem_statement": "incorrect report caused by hidden assumptions",
        "fingerprint": {},
    }
    unrelated = {
        "title": "Claude account email cannot be changed",
        "task": "change account email and billing",
        "object": "Claude account email",
        "failure_mode": "account email update is unavailable",
        "problem_statement": "cannot change account email",
        "fingerprint": {},
    }
    t1 = {"driver":"TECHNOLOGY", "text":"autonomous coding agents execute larger scopes while review capacity stays manual", "transition_key":"", "subject":"coding agents", "subject_explicit":True}
    t2 = {"driver":"TECHNOLOGY", "text":"coding agent autonomy now handles larger work scopes while human review remains manual", "transition_key":"", "subject":"coding agents", "subject_explicit":True}
    t3 = {"driver":"REGULATION", "text":"new compliance reporting mandate changes audit workflow", "transition_key":""}
    t_subject_a = {"driver":"TECHNOLOGY", "text":"automation adoption lowers workflow operating cost and changes delivery patterns", "subject":"coding agents", "subject_explicit":True, "transition_key":""}
    t_subject_b = {"driver":"TECHNOLOGY", "text":"automation adoption lowers workflow operating cost and changes delivery patterns", "subject":"warehouse robotics", "subject_explicit":True, "transition_key":""}
    dims = {k: dimension("UNKNOWN", basis="fixture") for k in DIMENSION_KEYS}
    for k in ("problem_persistence","transition_strength","system_mismatch","economic_materiality","buyer_formation","gap_durability"):
        dims[k] = dimension("SUPPORTED", basis="fixture")
    dims["captureability"] = dimension("PARTIAL", basis="fixture")
    c = classify_thesis(dims, transition_present=True, workaround_level_value=5)
    plan = research_plan(dims)
    inter = intersection_gate(problem_lineage={"persistence_state":"SUPPORTED"}, transition_lineage={"state":"SUPPORTED"}, direct_link_count=2, direct_independent_units=2, direct_independent_families=2, shared_candidate_count=1, c07_state="SUPPORTED", workaround_level_value=2)
    single = intersection_gate(problem_lineage={"persistence_state":"SUPPORTED"}, transition_lineage={"state":"SUPPORTED"}, direct_link_count=1, direct_independent_units=1, direct_independent_families=1, shared_candidate_count=1, c07_state="SUPPORTED", workaround_level_value=2)
    context = intersection_gate(problem_lineage={"persistence_state":"SUPPORTED"}, transition_lineage={"state":"SUPPORTED"}, direct_link_count=0, direct_independent_units=0, direct_independent_families=0, shared_candidate_count=1, c07_state="UNKNOWN", workaround_level_value=0)
    return {
        "same_problem_true_positive": same_problem(actual, same)["same_problem"] is True,
        "same_technology_not_same_problem": same_problem(actual, unrelated)["same_problem"] is False,
        "problem_buckets_exist": bool(problem_bucket_keys(actual)),
        "same_transition_true_positive": same_transition(t1, t2)["same_transition"] is True,
        "driver_conflict_blocks_transition_merge": same_transition(t1, t3)["same_transition"] is False,
        "explicit_transition_subject_conflict_blocks_overmerge": same_transition(t_subject_a, t_subject_b)["same_transition"] is False and "EXPLICIT_SUBJECT_CONFLICT" in same_transition(t_subject_a, t_subject_b)["reasons"],
        "transition_buckets_exist": bool(transition_bucket_keys(t1)),
        "manual_workaround_detected": workaround_level("we manually copy paste every result")[0] >= 2,
        "internal_tool_detected": workaround_level("we built an internal tool because manual review was painful")[0] >= 5,
        "generic_hiring_not_w6": workaround_level("the market is hiring AI engineers")[0] < 6,
        "direct_intersection_supported": inter["state"] == "SUPPORTED",
        "single_direct_intersection_stays_partial": single["state"] == "PARTIAL" and single["eligibility"] == "DIRECT_SINGLE_SOURCE_LINKED",
        "context_only_intersection_not_promoted": context["eligibility"] == "CONTEXT_ONLY" and context["state"] == "INSUFFICIENT",
        "zip2_candidate_requires_mismatch": c["zip2_readiness"] == "ZIP2_CANDIDATE",
        "research_no_recency_authority": bool(plan) and all(x.get("recency_factor_used") is False for x in plan),
        "fatal_unknowns_rank_high": any(x["fatal_gate"] for x in plan[:3]),
        "portfolio_sort_excludes_last_seen": portfolio_sort_key({"classification":"EMERGING_STRUCTURAL","zip2_readiness":"NOT_ZIP2_CLASS","dimensions":dims,"workaround_level":2,"thesis_id":"a","last_seen_at":"2099"}) == portfolio_sort_key({"classification":"EMERGING_STRUCTURAL","zip2_readiness":"NOT_ZIP2_CLASS","dimensions":dims,"workaround_level":2,"thesis_id":"a","last_seen_at":"2000"}),
    }
