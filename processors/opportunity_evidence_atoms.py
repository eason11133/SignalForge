"""Research-grounded evidence atoms for SignalForge.

This module adopts mature ideas from customer-need mining and weak supervision:
- raw UGC fragments can be useful even when they are incomplete;
- heuristic rules are labeling functions that may KEEP, REJECT, or ABSTAIN;
- missing one heuristic feature is not a hard negative;
- source role and complaint target remain hard truth boundaries.

The scores here are *not calibrated probabilities*. They are auditable weak-supervision
support/conflict scores used for routing evidence to DIRECT_NEED, INCOMPLETE_NEED,
CONTEXT, or REJECT. A future learned model may replace the aggregator without changing
these evidence contracts.
"""
from __future__ import annotations

import hashlib
import html
import math
import re
from collections import Counter
from typing import Any

ENGINE_VERSION = "opportunity-evidence-atoms-u8-need-solution-source-intent"
EVIDENCE_SCHEMA_VERSION = "feedback-role-need-frame-v5-need-solution-source-intent"
ROLE_CLASSIFIER_VERSION = "feedback-role-u8-need-solution-source-intent"
MAX_SEMANTIC_TEXT_CHARS = 2000

ABSTAIN = -1
REJECT = 0
KEEP = 1

# Labeling-function weights are intentionally simple and inspectable.  They are
# evidence-routing weights, not claims of statistical calibration.
LF_WEIGHTS = {
    "firsthand_direct_pain": 2.2,
    "negative_problem_span": 1.7,
    "problem_text_present": 1.0,
    "source_scoped_actor": 0.7,
    "product_scoped": 0.8,
    "workflow_known": 0.7,
    "signature_present": 0.5,
    "manual_workaround": 0.6,
    "burden_present": 0.6,
    "frequency_present": 0.5,
    "payment_behavior": 0.5,
    "wrong_target": 4.0,
    "non_primary_context": 2.5,
    "non_negative_review": 2.0,
}

_WORD = re.compile(r"[a-z0-9][a-z0-9_'-]{2,}", re.I)
STOP = {
    "this","that","with","from","have","will","your","their","there","about","into","when","using","used",
    "app","product","review","really","just","does","doesn","cannot","cant","could","would","should","because",
    "still","very","much","more","than","then","they","them","what","user","users","issue","problem","thing",
    "you","the","and","but","not","sure","anything","such","made","make","here","heres","built","specific","immediately",
}

# Mature need-mining systems typically keep partial semantic slots.  We expose a
# bounded lexical profile so downstream retrieval can work even without a legacy
# primary signature.
NORMALIZE = {
    "crashes":"crash","crashed":"crash","crashing":"crash","freezes":"freeze","freezing":"freeze","frozen":"freeze",
    "syncing":"sync","synchronized":"sync","synchronization":"sync","imports":"import","importing":"import",
    "parsing":"parse","parsed":"parse","emails":"email","emailed":"email","emailing":"email","manually":"manual","reenter":"re-enter","reentered":"re-enter",
    "trips":"trip","itineraries":"itinerary","typing":"type","typed":"type","types":"type",
    "expensive":"price","pricing":"price","costs":"cost","costly":"cost","delays":"delay","delayed":"delay",
    "hours":"hour","minutes":"minute","bookings":"booking","appointments":"appointment","invoices":"invoice",
}


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _evidence_text(o: dict[str, Any], *, limit: int = MAX_SEMANTIC_TEXT_CHARS) -> str:
    """Bound semantic regex work to the evidence-bearing span.

    Live community rows can contain many KB of metadata/full-post text. Mature feedback mining
    works on local evidence units; scanning an entire raw post for every labeling function both
    slows the system and increases context leakage. Preserve the original row untouched, but use
    an HTML-decoded bounded span for role/frame/triage semantics.
    """
    raw = str(o.get("problem_span") or o.get("reported_problem_span") or o.get("text") or "")
    # Bound *before* HTML decoding / whitespace normalization.  The previous order still
    # paid O(full-post-size) regex cost on every cached row, defeating the semantic cap.
    if len(raw) > limit:
        head = max(800, int(limit * 0.75))
        tail = max(200, limit - head)
        raw = raw[:head] + " … " + raw[-tail:]
    text = _clean(html.unescape(raw))
    return text[:limit]


def lexical_terms(text: Any, *, limit: int = 18) -> list[str]:
    out: list[str] = []
    for raw in _WORD.findall(_clean(text).lower()):
        t = NORMALIZE.get(raw, raw)
        if t in STOP or len(t) < 3:
            continue
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _known(v: Any) -> bool:
    s = _clean(v).lower()
    return bool(s and s not in {"unknown", "other", "none", "n/a"})



# Research-grounded multi-label feedback taxonomy.  Mature feedback-mining work
# separates problem reports, requests and usage/workaround signals from praise /
# feature strengths and from supplier-authored solution narratives.  These roles
# are evidence-routing labels, not market-truth labels.
NEED_FEEDBACK_ROLES = {"PROBLEM_REPORT", "FEATURE_REQUEST", "WORKAROUND_OR_USAGE"}
NON_NEED_CONTEXT_ROLES = {"POSITIVE_CAPABILITY", "SUPPLIER_PITCH", "USER_INNOVATION_NEED_SOLUTION", "POLICY_OPINION", "DISCUSSION_CONTEXT", "EMPLOYER_DEMAND_CONTEXT", "MARKET_SUPPLY_CONTEXT", "EXTERNAL_CONTEXT"}

# Source-role priors are stronger than lexical accidents.  Context-only corpora may
# contain phrases like "we built" or "because" but cannot become first-person user
# innovation or customer pain without a firsthand source contract.
CONTEXT_SOURCE_ROLE_MAP = {
    "HIRING_OR_VENDOR_CONTEXT": "EMPLOYER_DEMAND_CONTEXT",
    "MARKET_SUPPLY": "MARKET_SUPPLY_CONTEXT",
    "STRUCTURAL_OR_MARKET_CONTEXT": "EXTERNAL_CONTEXT",
    "TECHNICAL_MARKET_CONTEXT": "EXTERNAL_CONTEXT",
}
USER_INNOVATION_ALLOWED_SOURCE_ROLES = {"FIRSTHAND_USER_PAIN"}
USER_INNOVATION_ALLOWED_FAMILIES = {"reddit_rss","reddit","community_raw","hackernews","stackexchange","app_store_reviews"}

FIRST_PERSON_PAIN = re.compile(r"\b(?:i|we|my|our|me|us)\b.{0,90}\b(?:can['’]?t|cannot|couldn['’]?t|doesn['’]?t|didn['’]?t|fail(?:s|ed)?|crash(?:es|ed)?|freeze(?:s|d)?|slow|manual|by hand|re[- ]?enter|copy[- ]?paste|hate|annoy|frustrat|wast(?:e|ed)|takes?\s+(?:me|us)|kept\s+(?:making|asking|stopping)|have to|had to)\b", re.I)
FEATURE_REQUEST = re.compile(r"\b(?:i\s+(?:wish|want|need)|we\s+(?:wish|want|need)|please\s+(?:add|make|support)|would\s+be\s+(?:great|better|useful)\s+if|could\s+you\s+(?:add|make|support)|needs?\s+(?:a|an|to)\b)\b", re.I)
WORKAROUND_SIGNAL = re.compile(r"\b(?:workaround|instead\s+i|instead\s+we|so\s+i\s+(?:use|copy|export|type)|so\s+we\s+(?:use|copy|export|type)|i\s+(?:manually|have to)\s+(?:copy|type|enter|export)|we\s+(?:manually|have to)\s+(?:copy|type|enter|export)|i\s+(?:could\s+just|can\s+just)\s+use|we\s+(?:could\s+just|can\s+just)\s+use|i\s+use\s+my\s+\w+\s+to|we\s+use\s+our\s+\w+\s+to)\b", re.I)
POSITIVE_CAPABILITY = re.compile(r"\b(?:you\s+can\b|users?\s+can\b|allows?\s+(?:you|users?)\s+to\b|lets?\s+(?:you|users?)\b|works?\s+(?:beautifully|great|well)\b|don['’]?t\s+have\s+to\b|without\s+having\s+to\b|no\s+longer\s+(?:need|have)\s+to\b)\b", re.I)
BUILD_SIGNAL = re.compile(r"\b(?:(?:i|we)\s+)?(?:built|made|created|developed|wrote|shipped|launched|fine[- ]?tuned|configured|optimized|patched|assembled|set\s+up)\b|\b(?:i|we)\s+decided\s+to\s+build\b", re.I)
OWN_NEED_SIGNAL = re.compile(r"\b(?:because\s+i\b|because\s+we\b|i\s+(?:hate|needed|need|was\s+tired\s+of|kept|had\s+to)|we\s+(?:needed|need|were\s+tired\s+of|kept|had\s+to)|every\s+time\s+i\s+had\s+to|for\s+my\s+own|for\s+our\s+own)\b", re.I)
SUPPLIER_PITCH = re.compile(r"\b(?:here['’]?s\s+(?:a\s+)?(?:quick\s+)?demo|try\s+(?:our|my)\b|we\s+built\s+this\s+to\s+solve\b|our\s+(?:product|tool|platform|app)\b|book\s+a\s+demo|sign\s+up|we\s+help\s+(?:companies|teams|businesses)|customers?\s+use\s+our)\b", re.I)
POLICY_OPINION = re.compile(r"\b(?:regulation|law|rule|mandate|compliance)\b", re.I)
NORMATIVE_ONLY = re.compile(r"\b(?:should|ought\s+to|must\s+(?:show|put|disclose|require)|have\s+to\s+(?:put|show|disclose)|should\s+be\s+required)\b", re.I)


MAKER_PROMO = re.compile(r"\b(?:i['’]?ve\s+been\s+building|i\s+am\s+building|i['’]?m\s+building|we['’]?ve\s+been\s+building|my\s+(?:tool|app|product|service)|our\s+(?:tool|app|product|service)|(?:priced?|pricing)\s+(?:at|is)|\$\s*\d+(?:\.\d+)?\s*(?:/|per)\s*(?:month|mo)|\d+(?:\.\d+)?\s*/\s*month|supports?\s+(?:gpt|claude|gemini)|available\s+(?:for|on)|download\s+(?:it|now)|launch(?:ed|ing)\s+(?:my|our))\b", re.I)
SELF_SOLUTION_CUE = re.compile(r"\b(?:fine[- ]?tuned|configured|optimized|patched|hacked\s+together|set\s+up|assembled|wrote\s+(?:a\s+)?(?:script|guide)|decided\s+to\s+build|built|made|created|developed)\b", re.I)

# Source-intent is deliberately separate from feedback role. Research on user innovation
# distinguishes a user solving their own experienced need from project showcases, vendor/founder
# promotion, ordinary workaround use, and discussion/opinion. These are routing priors, not market truth.
PROJECT_SHOWCASE = re.compile(r"\b(?:show\s+hn:|hey\s+hn!?|i\s+built\s+this\s+solo|check\s+it\s+out\s+here|here(?:'|’)?s\s+what\s+i\s+built|launch(?:ed|ing)\s+(?:this|my)|demo\s+here|github\.com/|product\s+hunt)\b", re.I)
DISCUSSION_OPINION = re.compile(r"\b(?:i\s+guess\s+i\s+agree|i\s+don(?:'|’)?t\s+really\s+see\s+the\s+connection|not\s+seeing\s+your\s+(?:argument|point)|are\s+you\s+saying|i\s+agree\s+with\s+you\s+that)\b", re.I)

def _self_solution_own_need_pair(text: str) -> bool:
    """Conservative Need-Solution Pair test.

    Requires a concrete self-solution and an own-need cue in a causal/local relation. It
    accepts solution-first phrasing such as "I built X because I hate Y" and need-first
    phrasing such as "I kept doing Y, so I built X". Merely saying "I built this" or
    discussing a technology is not enough.
    """
    b = SELF_SOLUTION_CUE.search(text)
    n = OWN_NEED_SIGNAL.search(text)
    if not (b and n):
        return False
    # Explicit causal solution -> own need.
    if re.search(r"\b(?:built|made|created|developed|wrote|fine[- ]?tuned|configured|optimized|patched|set\s+up)\b[^.!?]{0,220}\bbecause\s+(?:i|we)\b", text, re.I):
        return True
    # Explicit need -> solution in a local evidence span.
    if n.start() <= b.start() and b.start() - n.start() <= 360:
        return True
    # Solution-first is acceptable only when the own-need cue is very local.
    return b.start() < n.start() and n.start() - b.start() <= 220

def source_intent(o: dict[str, Any], role: str | None = None) -> dict[str, Any]:
    text = _evidence_text(o)
    r = str(role or "")
    if r == "USER_INNOVATION_NEED_SOLUTION" and _self_solution_own_need_pair(text):
        return {"intent":"SELF_SOLUTION_FOR_OWN_NEED","confidence":"HIGH","reasons":["CAUSAL_NEED_SOLUTION_PAIR"]}
    if PROJECT_SHOWCASE.search(text):
        return {"intent":"PROJECT_SHOWCASE","confidence":"HIGH","reasons":["SHOWCASE_LANGUAGE"]}
    if r == "SUPPLIER_PITCH" or MAKER_PROMO.search(text):
        return {"intent":"FOUNDER_OR_VENDOR_PROMO","confidence":"HIGH","reasons":["PROMOTIONAL_SOLUTION_NARRATIVE"]}
    if r == "WORKAROUND_OR_USAGE":
        return {"intent":"WORKAROUND_USE","confidence":"HIGH","reasons":["USES_EXISTING_TOOL_OR_PROCESS"]}
    if r in {"DISCUSSION_CONTEXT","POLICY_OPINION"} or DISCUSSION_OPINION.search(text):
        return {"intent":"DISCUSSION_OR_OPINION","confidence":"HIGH","reasons":["DISCUSSION_LANGUAGE"]}
    if r in {"PROBLEM_REPORT","FEATURE_REQUEST"}:
        return {"intent":"FIRSTHAND_NEED","confidence":"MEDIUM","reasons":["NEED_ROLE"]}
    return {"intent":"UNRESOLVED","confidence":"LOW","reasons":["NO_SOURCE_INTENT"]}

def feedback_role(o: dict[str, Any]) -> dict[str, Any]:
    """Conservative feedback-role classifier with explicit source-intent separation.

    U8 adopts the mature user-innovation distinction between a self-solution to an own need
    and a showcase/promo/workaround. Role and intent are both evidence routing labels, never
    venture truth.
    """
    text = _evidence_text(o)
    if not text:
        return {"role":"UNRESOLVED", "confidence":"LOW", "reasons":["NO_TEXT"]}

    source_role=_clean(o.get("source_role")).upper()
    source_family=_clean(o.get("source_family") or o.get("source")).lower()
    source_table=_clean(o.get("source_table") or (o.get("raw_doc") or {}).get("table")).lower()
    if source_role in CONTEXT_SOURCE_ROLE_MAP or source_family in {"jobs","news","yc","packages","app_store","market_supply_external"} or "job_listing" in source_table:
        role=CONTEXT_SOURCE_ROLE_MAP.get(source_role)
        if not role:
            role="EMPLOYER_DEMAND_CONTEXT" if source_family=="jobs" or "job_listing" in source_table else ("MARKET_SUPPLY_CONTEXT" if source_family in {"app_store","market_supply_external"} else "EXTERNAL_CONTEXT")
        return {"role":role,"confidence":"HIGH","reasons":["SOURCE_ROLE_CONTEXT_PRIOR"]}

    # Explicit project/showcase and commercial maker promotion are solution context.
    if PROJECT_SHOWCASE.search(text):
        return {"role":"SUPPLIER_PITCH","confidence":"HIGH","reasons":["PROJECT_SHOWCASE_NOT_OWN_NEED_EVIDENCE"]}
    if SUPPLIER_PITCH.search(text) or MAKER_PROMO.search(text) or (BUILD_SIGNAL.search(text) and re.search(r"\b(?:companies|customers|clients|teams)\b", text, re.I)):
        return {"role":"SUPPLIER_PITCH", "confidence":"HIGH", "reasons":["SOLUTION_AUTHOR_OR_VENDOR_NARRATIVE"]}

    if POLICY_OPINION.search(text) and NORMATIVE_ONLY.search(text) and (re.search(r"\b(?:i\s+could\s+agree(?:\s+with\s+you)?\s+if|in\s+my\s+opinion|products?\s+(?:should|must|have\s+to))\b", text, re.I) or not FIRST_PERSON_PAIN.search(text)):
        return {"role":"POLICY_OPINION", "confidence":"HIGH", "reasons":["NORMATIVE_POLICY_CONTEXT_WITHOUT_FIRSTHAND_WORKFLOW_PAIN"]}
    if DISCUSSION_OPINION.search(text) and not FIRST_PERSON_PAIN.search(text):
        return {"role":"DISCUSSION_CONTEXT","confidence":"HIGH","reasons":["DISCUSSION_OR_ARGUMENT_CONTEXT"]}

    # Workaround use must be checked before user innovation. Using an existing AI/tool to cope
    # with a workflow is not the same thing as developing a novel self-solution.
    if WORKAROUND_SIGNAL.search(text):
        return {"role":"WORKAROUND_OR_USAGE", "confidence":"HIGH", "reasons":["WORKAROUND_OR_USAGE_SCENARIO"]}

    # Need-Solution Pair: concrete self-solution causally/local to an experienced own need.
    if (source_role in USER_INNOVATION_ALLOWED_SOURCE_ROLES and source_family in USER_INNOVATION_ALLOWED_FAMILIES
            and _self_solution_own_need_pair(text)):
        return {"role":"USER_INNOVATION_NEED_SOLUTION", "confidence":"HIGH", "reasons":["CAUSAL_NEED_SOLUTION_PAIR", "FIRSTHAND_UGC_SOURCE"]}

    pos_hits = len(POSITIVE_CAPABILITY.findall(text))
    if pos_hits >= 2 and not FIRST_PERSON_PAIN.search(text) and not FEATURE_REQUEST.search(text):
        return {"role":"POSITIVE_CAPABILITY", "confidence":"HIGH", "reasons":["FEATURE_STRENGTH_OR_BENEFIT_LANGUAGE"]}
    if FEATURE_REQUEST.search(text):
        return {"role":"FEATURE_REQUEST", "confidence":"HIGH", "reasons":["EXPLICIT_REQUEST"]}
    if FIRST_PERSON_PAIN.search(text):
        return {"role":"PROBLEM_REPORT", "confidence":"HIGH", "reasons":["FIRSTHAND_PROBLEM_LANGUAGE"]}
    if bool(o.get("primary_pain_authority")) and bool(o.get("direct_pain")) and _clean(o.get("problem_polarity")).upper()=="NEGATIVE":
        return {"role":"PROBLEM_REPORT", "confidence":"MEDIUM", "reasons":["UPSTREAM_PRIMARY_DIRECT_NEGATIVE"]}
    return {"role":"UNRESOLVED", "confidence":"LOW", "reasons":["NO_HIGH_CONFIDENCE_FEEDBACK_ROLE"]}



# Evidence-derived need frames adapt mature functional / need-representation work without
# pretending that a shallow regex parser has solved semantic understanding.  Every slot is
# traceable to supplied text or upstream parser metadata; missing slots remain UNKNOWN.
ACTION_PATTERNS = [
    ("enter", re.compile(r"\b(?:type|typing|typed|enter|entering|re[- ]?enter|retype|inputting)\b", re.I)),
    ("copy", re.compile(r"\b(?:copy|paste|copy[- ]?paste|transfer)\b", re.I)),
    ("import", re.compile(r"\b(?:import|parse|ingest|upload|extract)\b", re.I)),
    ("sync", re.compile(r"\b(?:sync|synchroni[sz]e|update)\b", re.I)),
    ("monitor", re.compile(r"\b(?:watch|monitor|check|status|track)\b", re.I)),
    ("format", re.compile(r"\b(?:format|formatting|layout|deck|slides?|presentation)\b", re.I)),
    ("confirm", re.compile(r"\b(?:confirm|confirmation|approve|approval|ask(?:ing)?\s+me)\b", re.I)),
    ("search", re.compile(r"\b(?:search|find|look\s+for|discover)\b", re.I)),
    ("book", re.compile(r"\b(?:book|booking|schedule|appointment|reservation)\b", re.I)),
    ("pay", re.compile(r"\b(?:pay|payment|billing|invoice|bank\s+transfer)\b", re.I)),
]
FAILURE_PATTERNS = [
    ("manual_reentry", re.compile(r"\b(?:manual(?:ly)?|by\s+hand|re[- ]?enter|retype|type\s+.*again|enter\s+.*again|copy[- ]?paste)\b", re.I)),
    ("slow_latency", re.compile(r"\b(?:slow|takes?\s+(?:too\s+)?long|several\s+(?:minutes|hours|days)|wait(?:ing)?|delay)\b", re.I)),
    ("crash_freeze", re.compile(r"\b(?:crash|freeze|frozen|hangs?|dies?)\b", re.I)),
    ("parse_import_failure", re.compile(r"\b(?:cannot|can['’]?t|doesn['’]?t|failed?\s+to|fails?\s+to)\b.{0,45}\b(?:import|parse|ingest|upload|extract)\b|\b(?:import|parse|ingest|upload|extract)\b.{0,45}\b(?:fail|error|wrong|missing)\b", re.I)),
    ("repeated_confirmation", re.compile(r"\b(?:kept|keeps?|repeatedly|again\s+and\s+again)\b.{0,60}\b(?:confirm|confirmation|ask|stop|stopping)\b|\b(?:stop|stopping)\b.{0,45}\b(?:confirm|confirmation|ask)\b", re.I)),
    ("missing_visibility", re.compile(r"\b(?:can['’]?t|cannot|hard\s+to|unable\s+to)\b.{0,50}\b(?:see|tell|know|distinguish|status|state)\b", re.I)),
    ("incorrect_result", re.compile(r"\b(?:wrong\s+(?:result|answer|output|value|data)|incorrect|bad\s+result|hallucinat|misclassif|mistake)\b", re.I)),
    ("cost_burden", re.compile(r"\b(?:expensive|costly|price|charged|costs?\s+too\s+much)\b", re.I)),
    ("privacy_constraint", re.compile(r"\b(?:privacy|private|confidential|local\s+only|cannot\s+upload)\b", re.I)),
]
CONSEQUENCE_PATTERNS = [
    re.compile(r"\b(?:wast(?:e|es|ed|ing)\s+(?:my|our)?\s*time|takes?\s+(?:me|us)?\s*(?:several|\d+)\s*(?:minutes|hours|days)|several\s+(?:minutes|hours|days))\b", re.I),
    re.compile(r"\b(?:miss(?:ed|ing)?\s+(?:booking|deadline|appointment)|lose|lost|blocked|stuck|cannot\s+finish|can['’]?t\s+finish)\b", re.I),
]


def extract_need_frame(o: dict[str, Any]) -> dict[str, Any]:
    text = _evidence_text(o)
    terms = lexical_terms(text, limit=28)
    actions = [name for name, pat in ACTION_PATTERNS if pat.search(text)]
    failures = [name for name, pat in FAILURE_PATTERNS if pat.search(text)]
    action_words = set(actions) | {"manual","again","problem","issue","error","fail","failed","slow","wrong","user","users"}
    objects = [x for x in terms if x not in action_words and x not in {"every","kept","keep","several","because"}][:8]
    consequence = _clean(o.get("burden_span"))
    if not consequence:
        for pat in CONSEQUENCE_PATTERNS:
            m=pat.search(text)
            if m:
                consequence=m.group(0);break
    workaround = _clean(o.get("current_behavior_span"))
    if not workaround and re.search(r"\b(?:manual(?:ly)?|by\s+hand|copy[- ]?paste|re[- ]?enter|retype)\b", text, re.I):
        workaround="manual workaround described in source text"
    actor = o.get("actor_scope") if _known(o.get("actor_scope")) else (o.get("native_scope") if _known(o.get("native_scope")) else None)
    workflow = o.get("workflow") if _known(o.get("workflow")) else None
    query=[]
    if workflow: query += lexical_terms(workflow,limit=3)
    query += actions[:2] + failures[:2] + objects[:5]
    specific_targets=[]
    for m in re.findall(r"['`\"]([A-Za-z][A-Za-z0-9_.-]{2,})['`\"]",text):
        z=m.lower()
        if z not in specific_targets:specific_targets.append(z)
    for m in re.findall(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z0-9_]*|[A-Za-z]+_[A-Za-z0-9_]+)\b",text):
        z=m.lower()
        if z not in specific_targets:specific_targets.append(z)
    specific_targets=specific_targets[:6]
    q=[]
    for x in query:
        x=str(x).lower().replace("_"," ").strip()
        if x and x not in q:q.append(x)
    filled=sum(bool(x) for x in [actor,workflow,actions,failures,objects,consequence,workaround])
    return {
        "frame_version":"need-frame-v1","status":"EVIDENCE_DERIVED_PARTIAL" if filled<5 else "EVIDENCE_DERIVED_RICH",
        "actor":actor,"workflow":workflow,"actions":actions,"failure_modes":failures,"objects":objects,"specific_targets":specific_targets,"primary_specific_target":specific_targets[0] if specific_targets else None,
        "consequence":consequence or None,"workaround":workaround or None,"query_terms":" ".join(q[:10]),
        "source_text_only":True,"semantic_completion_claimed":False,
    }


def ensure_observation_schema(o: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Migrate cached/live observations to the current research schema.

    Existing evidence_disposition is not evidence that the feedback-role / need-frame schema
    is current.  This prevents stale A1/A2 cache rows from bypassing newer evidence contracts.
    """
    if force or o.get("evidence_schema_version") != EVIDENCE_SCHEMA_VERSION or not o.get("feedback_role") or not o.get("source_intent") or not isinstance(o.get("need_frame"), dict):
        return annotate_observation(dict(o))
    return o


def labeling_function_votes(o: dict[str, Any]) -> dict[str, int]:
    role = _clean(o.get("source_role")).upper()
    target = _clean(o.get("problem_target")).upper()
    polarity = _clean(o.get("problem_polarity")).upper()
    problem = _clean(o.get("problem_span"))
    is_review = _clean(o.get("source_family")).lower() == "app_store_reviews"
    primary = bool(o.get("primary_pain_authority"))
    direct = bool(o.get("direct_pain"))

    return {
        "firsthand_direct_pain": KEEP if (primary and direct) else ABSTAIN,
        "negative_problem_span": KEEP if (problem and polarity == "NEGATIVE") else ABSTAIN,
        "problem_text_present": KEEP if len(problem) >= 12 else ABSTAIN,
        "source_scoped_actor": KEEP if (_known(o.get("actor_scope")) or _known(o.get("native_scope"))) else ABSTAIN,
        "product_scoped": KEEP if bool(_clean(o.get("product_id"))) else ABSTAIN,
        "workflow_known": KEEP if _known(o.get("workflow")) else ABSTAIN,
        # Crucial research adoption: missing signature is ABSTAIN, never REJECT.
        "signature_present": KEEP if bool(_clean(o.get("primary_problem_signature"))) else ABSTAIN,
        "manual_workaround": KEEP if bool(o.get("manual_behavior")) else ABSTAIN,
        "burden_present": KEEP if bool(o.get("burden_explicit")) else ABSTAIN,
        "frequency_present": KEEP if bool(o.get("frequency_explicit")) else ABSTAIN,
        "payment_behavior": KEEP if bool(o.get("payment_behavior_observed")) else ABSTAIN,
        "wrong_target": REJECT if target == "LISTED_ENTITY_OR_CONTENT" else ABSTAIN,
        "non_primary_context": REJECT if (role and role not in {"FIRSTHAND_USER_PAIN", "FIRSTHAND_TECHNICAL_PAIN"} and problem) else ABSTAIN,
        "non_negative_review": REJECT if (is_review and problem and polarity != "NEGATIVE") else ABSTAIN,
    }


def aggregate_weak_supervision(votes: dict[str, int]) -> dict[str, Any]:
    support = 0.0
    conflict = 0.0
    active = 0
    for name, vote in votes.items():
        if vote == ABSTAIN:
            continue
        active += 1
        w = float(LF_WEIGHTS.get(name, 1.0))
        if vote == KEEP:
            support += w
        elif vote == REJECT:
            conflict += w
    margin = support - conflict
    # This bounded score is only for deterministic routing; do not call it a probability.
    routing_score = 0.0 if active == 0 else 1.0 / (1.0 + math.exp(-margin / 2.0))
    return {
        "support_score": round(support, 3),
        "conflict_score": round(conflict, 3),
        "margin": round(margin, 3),
        "active_labeling_functions": active,
        "routing_score": round(routing_score, 4),
        "calibrated_probability": False,
    }


def evidence_disposition(o: dict[str, Any], agg: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    agg = agg or aggregate_weak_supervision(labeling_function_votes(o))
    reasons: list[str] = []
    role = _clean(o.get("source_role")).upper()
    target = _clean(o.get("problem_target")).upper()
    problem = _clean(o.get("problem_span"))
    polarity = _clean(o.get("problem_polarity")).upper()
    fb = feedback_role(o)
    fb_role = fb.get("role") or "UNRESOLVED"

    if target == "LISTED_ENTITY_OR_CONTENT":
        return "REJECT", ["WRONG_COMPLAINT_TARGET"]
    if role in {"MARKET_SUPPLY", "STRUCTURAL_OR_MARKET_CONTEXT", "HIRING_OR_VENDOR_CONTEXT", "TECHNICAL_MARKET_CONTEXT"}:
        return "CONTEXT", ["NON_PRIMARY_CONTEXT_ROLE"]
    if fb_role in NON_NEED_CONTEXT_ROLES:
        return "CONTEXT", ["FEEDBACK_ROLE_" + fb_role]
    if not o.get("primary_pain_authority"):
        return "REJECT", ["SOURCE_NOT_PRIMARY_PAIN_AUTHORITY"]

    # Mature feedback taxonomies include explicit requests and usage/workaround
    # scenarios even when sentiment is not strictly negative.  We still require a
    # primary firsthand-authority source; feature/request text alone cannot bootstrap
    # a vendor or context document into customer pain.
    role_supported_need = fb_role in NEED_FEEDBACK_ROLES
    parser_supported_problem = bool(o.get("direct_pain")) and bool(problem) and polarity == "NEGATIVE"
    if not problem or not (role_supported_need or parser_supported_problem):
        return "REJECT", ["NO_FIRSTHAND_REQUIREMENTS_RELEVANT_SIGNAL"]

    if o.get("primary_problem_signature") and o.get("problem_self_contained"):
        reasons.append("LEGACY_SIGNATURE_AVAILABLE")
        reasons.append("FEEDBACK_ROLE_" + fb_role)
        return "DIRECT_NEED", reasons

    if not o.get("primary_problem_signature"):
        reasons.append("SIGNATURE_ABSTAIN_NOT_REJECT")
    if not o.get("problem_self_contained"):
        reasons.append("INCOMPLETE_SCOPE_OR_CONTEXT")
    if not (_known(o.get("actor_scope")) or _known(o.get("native_scope")) or _clean(o.get("product_id"))):
        reasons.append("AFFECTED_SCOPE_INCOMPLETE")
    reasons.append("FEEDBACK_ROLE_" + fb_role)
    return "INCOMPLETE_NEED", reasons or ["INCOMPLETE_BUT_RETAINED"]


META_NOISE = re.compile(r"\b(?:repo_full_name|repository|github|gitlab|issue_id|pull_request|commit|sha256|title|mediajunkie|fly-audit|package_name|file_path|stack trace)\b|[_/\\]{1,}", re.I)
NATURAL_PAIN = re.compile(r"\b(?:i|we|my|our|me|us|every|again|manual|by hand|takes?|hours?|minutes?|can['’]?t|cannot|doesn['’]?t|fails?|crash|freeze|wrong|lost|missing|re[- ]enter|copy[- ]?paste|slow|expensive|charged|wait|delay)\b", re.I)

def fragment_information_quality(o: dict[str, Any]) -> dict[str, Any]:
    """Route retained need fragments by information value without deleting them.

    This is a triage signal, not a truth label. Low-information fragments remain stored
    but do not consume the scarce corroboration budget ahead of concrete user/workflow pain.
    """
    text=_evidence_text(o)
    terms=lexical_terms(text,limit=24)
    score=0.0; reasons=[]
    if len(text)>=24: score+=0.6; reasons.append("TEXT_LENGTH")
    if len(terms)>=3: score+=0.7; reasons.append("CONTENT_TERMS")
    if NATURAL_PAIN.search(text): score+=0.9; reasons.append("NATURAL_PAIN_LANGUAGE")
    if _known(o.get("workflow")): score+=0.6; reasons.append("WORKFLOW")
    if _known(o.get("actor_scope")) or _clean(o.get("product_id")): score+=0.5; reasons.append("SCOPE")
    if o.get("manual_behavior"): score+=0.7; reasons.append("MANUAL_WORKAROUND")
    if o.get("burden_explicit"): score+=0.7; reasons.append("BURDEN")
    if o.get("frequency_explicit"): score+=0.5; reasons.append("FREQUENCY")
    if o.get("payment_behavior_observed"): score+=0.6; reasons.append("PAYMENT_BEHAVIOR")
    codey=bool(META_NOISE.search(text)) or (text.count("_")+text.count("/")>=3)
    if codey: score-=2.6; reasons.append("METADATA_OR_CODE_NOISE")
    if len(terms)<2: score-=0.8; reasons.append("LOW_CONTENT")
    tier="HIGH" if score>=2.6 else ("MEDIUM" if score>=1.6 else "MISC")
    return {"score":round(max(0.0,score),2),"tier":tier,"reasons":reasons,"retained":True}

def annotate_observation(o: dict[str, Any]) -> dict[str, Any]:
    votes = labeling_function_votes(o)
    agg = aggregate_weak_supervision(votes)
    fb = feedback_role(o)
    si = source_intent(o, fb.get("role"))
    disposition, reasons = evidence_disposition(o, agg)
    problem = _evidence_text(o)
    frame = extract_need_frame(o)
    terms = lexical_terms(problem)
    # Add evidence-derived frame terms to retrieval vocabulary without making them identity truth.
    for ft in list(frame.get("actions") or []) + list(frame.get("failure_modes") or []) + list(frame.get("objects") or []):
        token=str(ft).lower().strip()
        if token and token not in terms: terms.append(token)
    terms=terms[:28]
    atom_id = "eat_" + hashlib.sha1((str(o.get("observation_id") or "") + "|" + problem).encode()).hexdigest()[:18]
    atom = {
        "atom_id": atom_id,
        "atom_type": "NEED_FRAGMENT" if disposition in {"DIRECT_NEED", "INCOMPLETE_NEED"} else ("CONTEXT" if disposition == "CONTEXT" else "REJECTED"),
        "disposition": disposition,
        "routing_reasons": reasons,
        "text": problem[:1200],
        "actor": o.get("actor_scope"),
        "workflow": o.get("workflow"),
        "vertical": o.get("vertical"),
        "product_id": o.get("product_id"),
        "product_name": o.get("product_name"),
        "problem_target": o.get("problem_target"),
        "legacy_primary_signature": o.get("primary_problem_signature") or None,
        "lexical_terms": terms,
        "workaround": _clean(o.get("current_behavior_span"))[:500] or None,
        "burden": _clean(o.get("burden_span"))[:500] or None,
        "frequency": _clean(o.get("frequency_span"))[:500] or None,
        "payment_behavior": _clean(o.get("payment_evidence_span"))[:500] or None,
        "source_role": o.get("source_role"),
        "source_family": o.get("source_family"),
        "source_ref": o.get("source_ref"),
        "normalized_problem_hash": o.get("normalized_problem_hash"),
        "feedback_role": fb.get("role"),
        "feedback_role_confidence": fb.get("confidence"),
        "feedback_role_reasons": list(fb.get("reasons") or []),
        "source_intent": si.get("intent"),
        "source_intent_confidence": si.get("confidence"),
        "source_intent_reasons": list(si.get("reasons") or []),
        "need_frame": frame,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "semantic_text_bounded": True,
        "semantic_text_char_cap": MAX_SEMANTIC_TEXT_CHARS,
        "weak_supervision": {"votes": votes, **agg},
    }
    out = dict(o)
    out["evidence_atom"] = atom
    out["evidence_atom_id"] = atom_id
    out["evidence_disposition"] = disposition
    out["evidence_routing_reasons"] = reasons
    out["feedback_role"] = fb.get("role")
    out["feedback_role_confidence"] = fb.get("confidence")
    out["feedback_role_reasons"] = list(fb.get("reasons") or [])
    out["source_intent"] = si.get("intent")
    out["source_intent_confidence"] = si.get("confidence")
    out["source_intent_reasons"] = list(si.get("reasons") or [])
    out["need_frame"] = frame
    out["evidence_schema_version"] = EVIDENCE_SCHEMA_VERSION
    out["weak_supervision_votes"] = votes
    out["weak_supervision_support_score"] = agg["support_score"]
    out["weak_supervision_conflict_score"] = agg["conflict_score"]
    out["weak_supervision_routing_score"] = agg["routing_score"]
    out["problem_lexical_terms"] = terms
    info = fragment_information_quality(out) if disposition in {"DIRECT_NEED","INCOMPLETE_NEED"} else {"score":0.0,"tier":"N/A","reasons":[],"retained":True}
    out["fragment_information"] = info
    out["research_tier"] = info.get("tier")
    # Compatibility only. It no longer requires a primary signature.
    out["hypothesis_seed_eligible"] = disposition == "DIRECT_NEED"
    out["research_fragment_eligible"] = disposition in {"DIRECT_NEED", "INCOMPLETE_NEED"}
    out["corroboration_priority_eligible"] = disposition in {"DIRECT_NEED","INCOMPLETE_NEED"} and info.get("tier") in {"HIGH","MEDIUM"}
    return out


def research_priority(o: dict[str, Any]) -> float:
    if o.get("evidence_disposition") not in {"DIRECT_NEED", "INCOMPLETE_NEED"}:
        return 0.0
    info=o.get("fragment_information") or fragment_information_quality(o)
    score = 0.8 + min(1.4,float(info.get("score") or 0.0)*0.35)
    score += 0.9 if o.get("product_id") else 0.0
    score += 0.8 if o.get("manual_behavior") else 0.0
    score += 0.8 if o.get("burden_explicit") else 0.0
    score += 0.6 if o.get("frequency_explicit") else 0.0
    score += 0.6 if o.get("payment_behavior_observed") else 0.0
    score += 0.4 if o.get("commercial_context_explicit") else 0.0
    score += 0.4 if _known(o.get("workflow")) else 0.0
    if info.get("tier")=="MISC": score-=1.0
    return round(max(0.0,score), 2)


def static_acceptance() -> dict[str, bool]:
    base = {
        "source_role":"FIRSTHAND_USER_PAIN","primary_pain_authority":True,"direct_pain":True,
        "problem_polarity":"NEGATIVE","problem_target":"PRIMARY_SOURCE_SUBJECT","problem_span":"Every booking I retype the details into a spreadsheet.",
        "primary_problem_signature":"","problem_self_contained":False,"actor_scope":"small_business_owner","native_scope":"smallbusiness",
        "workflow":"booking","vertical":"professional_services","product_id":"","manual_behavior":True,"burden_explicit":False,
        "frequency_explicit":True,"payment_behavior_observed":False,"commercial_context_explicit":False,
        "observation_id":"o1","source_family":"reddit_rss","source_ref":"r1","normalized_problem_hash":"h1",
    }
    a = annotate_observation(base)
    bad = annotate_observation({**base,"problem_target":"LISTED_ENTITY_OR_CONTENT"})
    supply = annotate_observation({**base,"source_role":"MARKET_SUPPLY","primary_pain_authority":False,"direct_pain":False,"paid_supply":True,"problem_span":""})
    positive = annotate_observation({**base,"problem_span":"You can immediately distinguish when an agent is actively working, waiting, finished, or stopped because of an error, and you don't have to keep watching the dashboard.","primary_problem_signature":"","problem_self_contained":False})
    user_innovation = annotate_observation({**base,"problem_span":"Built a tool to generate slides from research papers using local LLMs because I hate formatting decks and privacy matters.","primary_problem_signature":"","problem_self_contained":False})
    supplier_pitch = annotate_observation({**base,"problem_span":"Here's a quick demo of Skyvern. We built this to solve a specific problem: building browser automations often requires companies to hire people.","primary_problem_signature":"","problem_self_contained":False})
    policy = annotate_observation({**base,"problem_span":"I could agree if products that fail with the regulation have to put these shortcomings front and center wherever they are marketed.","primary_problem_signature":"","problem_self_contained":False})
    direct = annotate_observation({**base,"problem_span":"Codex made such slow progress on my work that I iterated for several days; it kept making small changes, stopping, and asking me for confirmation again and again.","primary_problem_signature":"","problem_self_contained":False})
    job_fake=annotate_observation({**base,"source":"jobs","source_family":"jobs","source_table":"job_listings","source_role":"HIRING_OR_VENDOR_CONTEXT","primary_pain_authority":False,"direct_pain":False,"problem_polarity":"NON_NEGATIVE","problem_span":"We built internal automation because our teams needed faster operations."})
    supply_fake=annotate_observation({**base,"source":"market_supply_external","source_family":"app_store","source_role":"MARKET_SUPPLY","primary_pain_authority":False,"direct_pain":False,"problem_polarity":"NON_NEGATIVE","problem_span":"We built this app because teams hate manual scheduling."})
    return {
        "missing_signature_abstains_not_dies": a["evidence_disposition"] == "INCOMPLETE_NEED" and "SIGNATURE_ABSTAIN_NOT_REJECT" in a["evidence_routing_reasons"],
        "weak_supervision_exposes_votes": isinstance(a.get("weak_supervision_votes"), dict) and a["weak_supervision_votes"].get("signature_present") == ABSTAIN,
        "wrong_target_hard_rejected": bad["evidence_disposition"] == "REJECT",
        "market_supply_is_context_not_need": supply["evidence_disposition"] == "CONTEXT",
        "partial_semantic_slots_preserved": bool(a["evidence_atom"]["workflow"]) and bool(a["evidence_atom"]["lexical_terms"]),
        "routing_score_not_claimed_calibrated": a["evidence_atom"]["weak_supervision"]["calibrated_probability"] is False,
        "informative_fragment_tier_visible": annotate_observation(base).get("research_tier") in {"HIGH","MEDIUM","MISC"},
        "metadata_like_fragment_retained_but_misc": annotate_observation({**base,"problem_span":"repo_full_name mediajunkie piper-morgan-product title fly-audit"}).get("research_tier")=="MISC",
        "schema_version_written": a.get("evidence_schema_version")==EVIDENCE_SCHEMA_VERSION,
        "bounded_semantic_text": a.get("evidence_atom",{}).get("semantic_text_bounded") is True,
        "need_frame_written": isinstance(a.get("need_frame"),dict) and a["need_frame"].get("source_text_only") is True,
        "stale_observation_reannotated": ensure_observation_schema({**base,"evidence_disposition":"INCOMPLETE_NEED","feedback_role":None,"evidence_schema_version":"old"}).get("feedback_role") in NEED_FEEDBACK_ROLES,
        "positive_capability_demoted_to_context": positive.get("feedback_role")=="POSITIVE_CAPABILITY" and positive.get("evidence_disposition")=="CONTEXT",
        "user_innovation_separate_from_need": user_innovation.get("feedback_role")=="USER_INNOVATION_NEED_SOLUTION" and user_innovation.get("evidence_disposition")=="CONTEXT",
        "supplier_pitch_separate_from_need": supplier_pitch.get("feedback_role")=="SUPPLIER_PITCH" and supplier_pitch.get("evidence_disposition")=="CONTEXT",
        "policy_opinion_separate_from_need": policy.get("feedback_role")=="POLICY_OPINION" and policy.get("evidence_disposition")=="CONTEXT",
        "firsthand_repeated_slow_progress_kept_as_need": direct.get("feedback_role")=="PROBLEM_REPORT" and direct.get("evidence_disposition")=="INCOMPLETE_NEED",
        "job_source_prior_blocks_false_user_innovation": job_fake.get("feedback_role")=="EMPLOYER_DEMAND_CONTEXT" and job_fake.get("evidence_disposition")=="CONTEXT",
        "market_supply_prior_blocks_false_user_innovation": supply_fake.get("feedback_role")=="MARKET_SUPPLY_CONTEXT" and supply_fake.get("evidence_disposition")=="CONTEXT",
    }
