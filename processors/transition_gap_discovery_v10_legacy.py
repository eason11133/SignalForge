"""SignalForge V8 role-locked multi-lane opportunity discovery.

Discovery is intentionally broader than a single Zip2/transition-gap pattern while
remaining evidence governed.  Six opportunity classes are searched in parallel:

* TRANSITION_GAP
* PROVEN_MARKET_WEDGE
* MICRO_FRICTION
* DISTRIBUTION_MODEL_GAP
* SECOND_ORDER_PAIN
* BORING_OPS

The LLM is allowed to adjudicate whether already-retrieved evidence belongs
together.  It is NOT allowed to write actor/problem/cost/change/gap truth.  Every persisted factual field is copied from a role-qualified exact source span or deterministically tagged.
UNKNOWN remains UNKNOWN.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import async_session, ProblemCandidate, CandidateEvidence, Post, ProductReview
from processors.llm_client import TokenUsage, call_llm
from processors.opportunity_engine import OpportunityEngine
from processors.problem_candidate_engine import ProblemCandidateEngine
from processors.solo_transition_opportunity import fingerprint_is_founder_unit

ENGINE_VERSION = "opportunity-portfolio-discovery-v10-source-portfolio-expanded-role-local"
CACHE_PATH = Path(".radar_runtime/transition_gap_discovery.json")
MAX_SCREEN_POOL = 48
MAX_PER_LLM_CALL = 24
MAX_PERSIST_PER_RUN = 8
V61_ENGINE = "transition-gap-discovery-v4-compact-ndjson-safe"
V7_ENGINE = "opportunity-portfolio-discovery-v7-evidence-locked"
V8_ENGINE = "opportunity-portfolio-discovery-v8-role-locked"

LANES = (
    "TRANSITION_GAP",
    "PROVEN_MARKET_WEDGE",
    "MICRO_FRICTION",
    "DISTRIBUTION_MODEL_GAP",
    "SECOND_ORDER_PAIN",
    "BORING_OPS",
)

CHANGE_TRIGGER_RE = re.compile(
    r"\b(?:now (?:supports?|available|possible|costs?|handles?|allows?)|"
    r"newly (?:available|released|supported)|launched|released|introducing|announced|general(?:ly)? available|available today|"
    r"became available|price (?:cut|drop)|cheaper|cost fell|open[- ]source(?:d)?|"
    r"mandat(?:e|ed|ory)|new regulation|new law|compliance deadline|"
    r"api (?:now|released|available)|real[- ]time api|can automate|can handle|agent(?:s)? can now|"
    r"automation (?:now|can now)|ocr (?:now|can now)|voice ai|computer vision)\b",
    re.I,
)
TECH_CHANGE_RE = re.compile(
    r"\b(?:ai agent|agents|llm|api|ocr|speech[- ]to[- ]text|voice ai|computer vision|vision model|"
    r"automation|workflow automation|open source|platform api|webhook|integration|smartphone|sensor|payment infrastructure)\b",
    re.I,
)
LEGACY_RE = re.compile(
    r"\b(?:manual(?:ly)?|spreadsheets?|excel|google sheets?|csv|email(?:s)?|copy(?:ing)?[ -]?and[ -]?paste|"
    r"copy[ -]?paste|paper(?:work)?|pdf(?:s)?|phone calls?|voicemail|fax|data entry|re[- ]enter|hand[- ]enter|"
    r"by hand|workaround|shared inbox|whatsapp|line messages?|chasing|follow[- ]ups? by email|"
    r"sticky notes?|notebooks?|pen and paper|word documents?|multiple tabs?|multiple tools?)\b",
    re.I,
)
# A "burden" must describe the current failure/cost, not the benefit claimed by a solution.
NEGATIVE_BURDEN_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:hours?|minutes?|days?)\b|\bentire day\b|\bhours? (?:a|per) (?:day|week|month)\b|"
    r"\btime[- ]consuming\b|\blabor(?:ious)?\b|\blabour\b|\bmanual coordination\b|\bmanual (?:work|process|workflow|entry)\b|"
    r"\bbacklog\b|\bdelay(?:ed|s)?\b|\brework\b|\bmissed\b|\blost\b|\bloss(?:es)?\b|\blose(?:s|d|ing)? (?:millions?|money|revenue|sales)\b|"
    r"\bwaste(?:d|s|ing)?\b|\bdowntime\b|\bunpaid\b|\bfine\b|\bpenalt(?:y|ies)\b|\bbottleneck(?:s)?\b|\berror(?:s)?\b|"
    r"\bwaits?\b|\bdays? later\b|\bmissing\b|"
    r"\b(?:costs?|spend|spent|waste(?:d)?|lost|fine|penalt(?:y|ies)|unpaid)\s+(?:(?:\$|usd|nt\$)\s*)?\d)",
    re.I,
)
BENEFIT_CLAIM_RE = re.compile(
    r"\b(?:reduce[sd]?|reducing|save[sd]?|saving|lower(?:ed|s|ing)?|alleviat(?:e|es|ed|ing)|"
    r"eliminat(?:e|es|ed|ing)|improv(?:e|es|ed|ing)|faster|streamlin(?:e|es|ed|ing)|"
    r"automat(?:e|es|ed|ing)|allow(?:s|ed|ing)?|enable(?:s|d|ing)?)\b",
    re.I,
)
SOLUTION_MARKETING_RE = re.compile(
    r"\b(?:our (?:platform|product|software|solution)|we (?:built|developed|offer|provide)|"
    r"it (?:ingests|extracts|handles|automates|writes|connects)|the platform (?:keeps|automates|provides)|"
    r"helps? .* (?:spend less|save|reduce)|built by)\b",
    re.I,
)
PROMOTIONAL_PROOF_RE = re.compile(
    r"\b(?:trust(?:s|ed)? .* (?:customers?|clinicians?|organizations?)|\d+[,+]?\d*\+? (?:customers?|clinicians?|organizations?)|"
    r"support(?:s|ing)? over \d+|handle(?:s|d|ing)? \$(?:\d|\.)+[mbk]?\+?|annual claims|top[- ]line revenue|"
    r"backed by|funded by|market leader|leading platform)\b", re.I,
)
FUNDING_RE = re.compile(
    r"\b(?:raises?|raised|raising|funding|funded|series [a-z]|seed round|venture|valuation|investors?|backed by|capital raise)\b", re.I,
)
WORKAROUND_METHOD_RE = re.compile(
    r"\b(?:manual(?:ly)?|by hand|spreadsheets?|excel|google sheets?|csv|email(?:s)?|copy(?:ing)?[ -]?and[ -]?paste|copy[ -]?paste|"
    r"phone calls?|voicemail|fax|data entry|re[- ]enter|hand[- ]enter|shared inbox|whatsapp|line messages?|chasing|"
    r"follow[- ]ups? by email|sticky notes?|notebooks?|pen and paper|word documents?|multiple tabs?|multiple tools?|"
    r"paper[- ]based|paper forms?|manual paperwork)\b", re.I,
)
STRUCTURAL_CHANGE_RE = re.compile(
    r"\b(?:now available|available today|became available|generally available|released|launched|announced|"
    r"api (?:now|released|available)|can now|agents? can now|automation can now|"
    r"price (?:cut|drop)|cost fell|open[- ]sourced|new regulation|new law|compliance deadline|mandat(?:e|ed|ory))\b",
    re.I,
)
RESEARCH_PAPER_RE = re.compile(
    r"\b(?:in this paper|we (?:present|propose|report|evaluate|characterize|developed a .* framework)|"
    r"empirical user study|macro f1|balanced accuracy|multicentric|sampling|benchmark|dataset|arxiv|"
    r"fine[- ]tuned|vision transformer|temporal convolutional|diffusion transformer|compute[- ]in[- ]memory)\b",
    re.I,
)
SPECIFIC_ACTOR_RE = re.compile(
    r"\b(?:medical practices?|primary care offices?|dental practices?|dentists?|clinics?|practice managers?|"
    r"referral coordinators?|care coordinators?|revenue cycle teams?|restaurants?|retailers?|store owners?|agencies?|"
    r"accounting firms?|accountants?|bookkeepers?|fund accountants?|law firms?|property managers?|landlords?|"
    r"contractors?|construction companies?|logistics companies?|freight forwarders?|warehouses?|insurance brokers?|"
    r"schools?|training providers?|hotels?|hospitality businesses?|salons?|repair shops?|dealers?|manufacturers?|"
    r"small businesses?|smbs?|operations managers?|office managers?|sales teams?|sales managers?|"
    r"investment analysts?|investment professionals?|data analysts?|researchers?|it managers?|it teams?|"
    r"customer support teams?|support teams?|finance teams?|procurement teams?|field service teams?)\b",
    re.I,
)
DIRECT_BEHAVIOR_RE = re.compile(
    r"\b(?:i |we |our |my |every time|every day|every week|daily|weekly|monthly|constantly|repeatedly|"
    r"have to|has to|need to|still use|still uses|by hand|manual(?:ly)?|workaround|takes? \d+|spend \d+)\b",
    re.I,
)

WORKFLOW_RE = re.compile(
    r"\b(?:bookings?|appointments?|schedul\w*|dispatch(?:ing)?|invoices?|billing|quotes?|estimating|leads?|sales|crm|follow[- ]ups?|"
    r"customer support|support tickets?|intake|onboarding|referrals?|inventory|orders?|procurement|purchase orders?|reconcil\w*|"
    r"reporting|compliance|permits?|claims?|forms?|documents?|timesheets?|payroll|property management|maintenance|inspections?|"
    r"reservations?|call handling|data entry|case management|application processing|renewals?|collections|"
    r"research|analysis|monitoring|issue resolution|catalog|feedback|coordination|coordinator|queue|read(?:ing)?|study|studying|note taking)\b",
    re.I,
)
# Kept for evidence-excerpt retrieval compatibility. It is not sufficient to prove burden in V8.
ECONOMIC_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:hours?|minutes?|days?)|hours? (?:a|per) (?:day|week|month)|"
    r"\$\s?\d|nt\$\s?\d|usd\s?\d|costs?|spend|spent|waste(?:d|s|ing)?|lost|loss|revenue|headcount|labor|labour|"
    r"salary|fee|fine|penalt|backlog|delay|rework|refund|churn|conversion|downtime|missed sales?|unpaid)\b",
    re.I,
)
FRICTION_RE = re.compile(
    r"\b(?:annoy(?:ing|ed|ance)?|frustrat(?:ing|ed|ion)?|tedious|cumbersome|painful|time[- ]consuming|"
    r"inconvenien(?:t|ce)|messy|hard to|difficult to|keeps? (?:happening|breaking|failing)|every time|"
    r"constantly|repeatedly|easy to miss|gets? lost|too many steps?|takes? forever|hate having to|"
    r"wish there was|workaround|manual(?:ly)?)\b",
    re.I,
)
FREQUENCY_RE = re.compile(
    r"\b(?:daily|weekly|monthly|every day|every week|every month|every time|often|frequently|repeatedly|constantly|"
    r"per day|per week|per month|each time|again and again)\b",
    re.I,
)
DISSATISFACTION_RE = re.compile(
    r"\b(?:too expensive|too costly|too complex|overkill|hard to use|difficult to use|not worth|doesn['’]?t fit|"
    r"does not fit|poor support|missing feature|limited|not adopted|low adoption|switching cost|long wait|"
    r"hard to access|difficult to access|unavailable|minimum order|high fee|hidden fee|manual workaround|"
    r"still use|still rely|still manually|fragmented|multiple tools?)\b",
    re.I,
)
DISTRIBUTION_GAP_RE = re.compile(
    r"\b(?:too expensive|too complex|overkill|not adopted|low adoption|hard to access|difficult to access|"
    r"long wait|minimum order|high fee|hidden fee|only available|not available in|local access|distribution|"
    r"channel|middleman|commission|subscription only|enterprise only|sales process)\b",
    re.I,
)
SUPPLY_RE = re.compile(
    r"\b(?:product|service|software|platform|app|tool|vendor|provider|startup|company|solution|subscription|plan|pricing|"
    r"customers?|clients?|revenue|paid|per month|per year|marketplace|launched|available)\b",
    re.I,
)
HARD_PAY_SIGNAL_RE = re.compile(
    r"(?:\$\s?\d|nt\$\s?\d|usd\s?\d|\bpricing\b|\bsubscription\b|\bpaid\b|\bfee\b|\brevenue\b|"
    r"\bper month\b|\bper year\b|\bcontract value\b|\bannual recurring revenue\b|\barr\b|\bmrr\b)",
    re.I,
)
# Broader retrieval-only matcher. This may find a sentence worth inspecting but is never enough to prove paid market supply.
PAY_SIGNAL_RE = re.compile(
    r"(?:" + HARD_PAY_SIGNAL_RE.pattern + r"|\bcustomers?\b|\bclients?\b)",
    re.I,
)
SECOND_ORDER_RE = re.compile(
    r"\b(?:since (?:adopting|using|switching|rolling out)|after (?:adopting|using|switching|rolling out)|"
    r"now that|because of the rise of|as .* adoption grows|created a new problem|introduced a new problem|"
    r"with .* now being used|as more .* use)\b",
    re.I,
)
BUYER_RE = SPECIFIC_ACTOR_RE
CONSUMER_RE = re.compile(
    r"\b(?:readers?|students?|parents?|families?|households?|travelers?|creators?|freelancers?|hobbyists?|homeowners?|pet owners?)\b",
    re.I,
)
FRONTIER_RE = re.compile(
    r"\b(?:rocm|cuda|cudagraph|sglang|vllm|kernel|tensor parallel|expert parallel|disaggregated serving|"
    r"speculative decoding|kv cache|mechanistic interpret|foundation model training|pretraining|causal genetics|mendelian randomization)\b",
    re.I,
)
DEVELOPER_ONLY_RE = re.compile(
    r"\b(?:pull request|github issue|stack trace|compiler bug|runtime bug|sdk bug|package maintainer|unit test framework|"
    r"cuda|kernel|repository maintainer|dependency conflict)\b",
    re.I,
)
BROAD_AI_RE = re.compile(
    r"\b(?:ai models? (?:are|is) unreliable|llm hallucinations?|ai hallucinations?|model assumptions?|"
    r"ai output quality|ai makes people lazy|junior engineers? over[- ]rely)\b",
    re.I,
)

STRUCTURAL_CHANGE_SOURCES = {"news", "packages"}
PRIMARY_SUPPLY_SOURCES = {"news", "yc", "product_review", "product_review_external", "market_supply_external"}
PRIMARY_LAG_SOURCES = {"jobs", "news", "yc", "product_review", "community_raw", "community_external", "product_review_external"}
DIRECT_PAIN_SOURCES = {"community_raw", "product_review", "community_external", "product_review_external"}
WEDGE_PAIN_SOURCES = {"community_raw", "product_review", "community_external", "product_review_external", "yc", "news"}
BORING_OPS_SOURCES = {"community_raw", "product_review", "community_external", "product_review_external", "yc", "jobs"}
SECOND_ORDER_SOURCES = {"community_raw", "product_review", "community_external", "product_review_external", "news"}

CAPABILITY_PATTERNS = {
    "voice": re.compile(r"\b(?:voice ai|speech[- ]to[- ]text|speech recognition|call automation|phone agent)\b", re.I),
    "document": re.compile(r"\b(?:ocr|document ai|document understanding|pdf extraction|form extraction|vision model)\b", re.I),
    "automation": re.compile(r"\b(?:ai agent|agents can now|workflow automation|automation can now|can automate|api now|api released|api available|webhook|integration api)\b", re.I),
    "vision": re.compile(r"\b(?:computer vision|vision model|visual inspection|image recognition)\b", re.I),
    "regulation": re.compile(r"\b(?:mandat(?:e|ed|ory)|new regulation|new law|compliance deadline)\b", re.I),
    "cost": re.compile(r"\b(?:price (?:cut|drop)|cheaper|cost fell|open[- ]source(?:d)?)\b", re.I),
    "platform": re.compile(r"\b(?:platform api|marketplace api|real[- ]time api|webhook|integration)\b", re.I),
}
VERTICAL_PATTERNS = {
    "healthcare": re.compile(r"\b(?:clinics?|dental|dentists?|medical practices?|practice managers?|patients?|primary care offices?|referral coordinators?)\b", re.I),
    "property": re.compile(r"\b(?:property manager|property management|landlord|real estate|tenant)\b", re.I),
    "construction_trades": re.compile(r"\b(?:contractor|construction|hvac|plumber|electrician|repair shop|field service)\b", re.I),
    "logistics": re.compile(r"\b(?:logistics|freight|warehouse|shipping|trucking|carrier)\b", re.I),
    "hospitality": re.compile(r"\b(?:hotel|hospitality|restaurant|reservation)\b", re.I),
    "professional_services": re.compile(r"\b(?:accounting|accountant|law firm|insurance|broker|agency)\b", re.I),
    "retail": re.compile(r"\b(?:retailer|retail store|store owner|dealer|merchant)\b", re.I),
    "manufacturing": re.compile(r"\b(?:manufacturer|manufacturing|factory|plant manager)\b", re.I),
    "education": re.compile(r"\b(?:schools?|training providers?|education providers?|students?|study|studying)\b", re.I),
    "personal_services": re.compile(r"\b(?:salon|spa|barber|beauty clinic)\b", re.I),
    "consumer": re.compile(r"\b(?:readers?|parents?|famil(?:y|ies)|households?|travelers?|creators?|freelancers?|hobbyists?|homeowners?|pet owners?|consumers?)\b", re.I),
}
WORKFLOW_PATTERNS = {
    "booking": re.compile(r"\b(?:bookings?|appointments?|reservations?|schedul\w*)\b", re.I),
    "billing": re.compile(r"\b(?:invoices?|billing|quotes?|estimating|reconcil\w*)\b", re.I),
    "sales": re.compile(r"\b(?:lead|sales|crm|follow[- ]up|conversion|collections)\b", re.I),
    "support": re.compile(r"\b(?:customer support|support ticket|call handling|shared inbox|phone calls?)\b", re.I),
    "intake": re.compile(r"\b(?:intake|onboarding|application processing|referrals?|form|document|data entry)\b", re.I),
    "ops": re.compile(r"\b(?:inventory|orders?|procurement|dispatch(?:ing)?|maintenance|inspections?|purchase orders?|monitoring|issue resolution)\b", re.I),
    "compliance": re.compile(r"\b(?:compliance|permit|claim|renewal|reporting)\b", re.I),
    "backoffice": re.compile(r"\b(?:data entry|back office|spreadsheet|excel|email|pdf|copy[- ]paste|catalog)\b", re.I),
    "research": re.compile(r"\b(?:research|analysis|literature review|data analysis)\b", re.I),
    "coordination": re.compile(r"\b(?:coordination|coordinator|handoff|queue|shared calendar|feedback)\b", re.I),
    "reading_study": re.compile(r"\b(?:read(?:ing)?|study|studying|note taking)\b", re.I),
}
CAPABILITY_WORKFLOW = {
    "voice": {"booking", "support", "sales"},
    "document": {"billing", "intake", "compliance", "backoffice"},
    "automation": set(WORKFLOW_PATTERNS),
    "vision": {"ops", "compliance"},
    "regulation": {"compliance", "intake", "backoffice"},
    "cost": set(WORKFLOW_PATTERNS),
    "platform": set(WORKFLOW_PATTERNS),
}
GENERIC_PAIR_TOKENS = {
    "ai", "llm", "model", "models", "agent", "agents", "software", "tool", "tools", "new", "now", "use", "using",
    "used", "user", "users", "company", "business", "problem", "issue", "work", "workflow", "system", "systems", "data",
    "platform", "customer", "customers", "service", "services", "team", "teams", "developer", "developers", "engineer",
    "engineers", "application", "applications",
}


def _clean(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        v = " ".join(map(str, v))
    elif isinstance(v, dict):
        v = " ".join(f"{k} {x}" for k, x in v.items())
    s = re.sub(r"<[^>]+>", " ", str(v))
    s = re.sub(r"https?://\S+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _known(v: Any) -> bool:
    return _clean(v).lower() not in {"", "unknown", "unclear", "none", "none mentioned", "n/a"}


def _parse_llm_items(raw: Any) -> list[dict[str, Any]]:
    # V9.1 protocol safety: a one-item batch commonly returns a single object
    # {"i":"P1","a":0} rather than an {"items":[...]} wrapper/NDJSON stream.
    # Treat direct verdict objects as first-class, while still supporting wrapper,
    # list, NDJSON, fenced JSON and truncated-tail recovery.
    def _as_items(obj: Any) -> list[dict[str, Any]]:
        if isinstance(obj, dict):
            if ("i" in obj or "id" in obj) and "a" in obj:
                return [obj]
            items = obj.get("items")
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
            return []
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return []

    if isinstance(raw, (dict, list)):
        return _as_items(raw)
    text = raw.strip() if isinstance(raw, str) else _clean(raw)
    if not text:
        return []
    text = re.sub(r"^```(?:json|jsonl|ndjson)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        items = _as_items(obj)
        if items:
            return items
    except Exception:
        pass
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        # Complete NDJSON objects are retained even if the final tail is truncated.
        if not line.endswith("}"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        out.extend(_as_items(obj))
    return out


def _doc_id(doc: dict[str, Any]) -> str:
    return f"{doc.get('source','unknown')}:{doc.get('table','unknown')}:{doc.get('pk','unknown')}"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", _clean(text).lower()) if t not in GENERIC_PAIR_TOKENS}


CORROBORATION_GENERIC_TOKENS = {
    "manual","manually","process","processes","frustrating","frustrated","annoying","tedious","time","hours","hour","minutes","minute",
    "daily","weekly","monthly","every","each","still","because","takes","take","spend","spent","workaround","workflow","problem","issue",
    "data","entry","coordination","business","company","team","teams","customers","customer","clients","client"
}

def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", _clean(text).lower())
            if t not in GENERIC_PAIR_TOKENS and t not in CORROBORATION_GENERIC_TOKENS and t not in ENGLISH_STOP_WORDS}


def _sentences(text: str, max_sentences: int = 18) -> list[str]:
    text = _clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s*[;•]\s+|\s+[-–—]\s+", text)
    out: list[str] = []
    for p in parts:
        p = _clean(p).strip(" -–—")
        if len(p) < 18:
            continue
        if len(p) > 360:
            # Keep exact normalized substrings; do not paraphrase.
            for q in re.split(r"\s*,\s+", p):
                q = _clean(q)
                if 18 <= len(q) <= 360:
                    out.append(q)
                    if len(out) >= max_sentences:
                        return out
        else:
            out.append(p)
        if len(out) >= max_sentences:
            break
    return out or ([text[:360]] if text else [])


def _first_sentence(text: str, *patterns: re.Pattern[str]) -> str:
    ss = _sentences(text)
    for s in ss:
        if all(p.search(s) for p in patterns if p is not None):
            return s
    for s in ss:
        if any(p.search(s) for p in patterns if p is not None):
            return s
    return ss[0] if ss else ""


def _best_evidence_sentences(text: str, patterns: tuple[re.Pattern[str], ...], limit: int = 5) -> list[str]:
    scored = []
    for i, s in enumerate(_sentences(text, 24)):
        hits = sum(1 for p in patterns if p.search(s))
        if hits:
            scored.append((hits, -i, s))
    scored.sort(reverse=True)
    out = [s for _, _, s in scored[:limit]]
    if not out:
        out = _sentences(text, limit)
    return out


def _tag_names(text: str, patterns: dict[str, re.Pattern[str]]) -> set[str]:
    text = _clean(text)
    return {name for name, pattern in patterns.items() if pattern.search(text)}


def _normalized_capabilities(text: str) -> set[str]:
    caps = _tag_names(text, CAPABILITY_PATTERNS)
    specific = caps & {"voice", "document", "vision", "regulation"}
    if specific:
        return specific | ({"cost"} if "cost" in caps else set())
    return caps


def _first_match(text: str, patterns: list[re.Pattern[str]] | tuple[re.Pattern[str], ...]) -> str:
    for p in patterns:
        m = p.search(_clean(text))
        if m:
            return _clean(m.group(0))
    return ""


def _strict_sentence(
    text: str,
    *,
    all_patterns: tuple[re.Pattern[str], ...] = (),
    any_patterns: tuple[re.Pattern[str], ...] = (),
    forbid_patterns: tuple[re.Pattern[str], ...] = (),
) -> str:
    for s in _sentences(text, 30):
        if all(p.search(s) for p in all_patterns) and (not any_patterns or any(p.search(s) for p in any_patterns)):
            if any(p.search(s) for p in forbid_patterns):
                continue
            return s
    return ""


def _sentence_containing_literal(text: str, literal: str) -> str:
    literal = _clean(literal)
    if not literal or literal.upper() == "UNKNOWN":
        return ""
    for s in _sentences(text, 30):
        if re.search(r"\b" + re.escape(literal) + r"\b", s, re.I):
            return s
    return ""


def _burden_sentence(text: str) -> str:
    # A burden must be a CURRENT negative consequence. Adoption/revenue/funding proof is not pain.
    return _strict_sentence(
        text,
        all_patterns=(NEGATIVE_BURDEN_RE,),
        any_patterns=(WORKFLOW_RE, LEGACY_RE, FRICTION_RE),
        forbid_patterns=(BENEFIT_CLAIM_RE, SOLUTION_MARKETING_RE, PROMOTIONAL_PROOF_RE),
    )


def _workaround_sentence(text: str) -> str:
    # "paperwork has errors" is a problem, not a workaround. Require an actual operating method.
    return _strict_sentence(
        text,
        all_patterns=(WORKAROUND_METHOD_RE,),
        any_patterns=(WORKFLOW_RE, DIRECT_BEHAVIOR_RE),
        forbid_patterns=(BENEFIT_CLAIM_RE, SOLUTION_MARKETING_RE, PROMOTIONAL_PROOF_RE),
    )


def _problem_sentence(text: str) -> str:
    return _strict_sentence(
        text,
        all_patterns=(WORKFLOW_RE,),
        any_patterns=(FRICTION_RE, DISSATISFACTION_RE, NEGATIVE_BURDEN_RE),
        forbid_patterns=(BENEFIT_CLAIM_RE, SOLUTION_MARKETING_RE, PROMOTIONAL_PROOF_RE),
    )


def _change_sentence(text: str) -> str:
    for s in _sentences(text, 30):
        if not STRUCTURAL_CHANGE_RE.search(s):
            continue
        if FUNDING_RE.search(s):
            continue
        if not (_normalized_capabilities(s) or VERTICAL_PATTERNS["consumer"].search(s)):
            continue
        return s
    return ""


def _supply_sentence(text: str) -> str:
    for s in _sentences(text, 30):
        if not HARD_PAY_SIGNAL_RE.search(s):
            continue
        if FUNDING_RE.search(s):
            continue
        if not (SUPPLY_RE.search(s) or BUYER_RE.search(s) or CONSUMER_RE.search(s)):
            continue
        return s
    return ""


def _distribution_sentence(text: str) -> str:
    return _strict_sentence(text, all_patterns=(DISTRIBUTION_GAP_RE,), any_patterns=(DISSATISFACTION_RE, FRICTION_RE, LEGACY_RE))


def _second_order_sentence(text: str) -> str:
    return _strict_sentence(text, all_patterns=(SECOND_ORDER_RE,), any_patterns=(FRICTION_RE, NEGATIVE_BURDEN_RE, DISSATISFACTION_RE))


def _is_research_paper(text: str) -> bool:
    return bool(RESEARCH_PAPER_RE.search(_clean(text)))


def _actor_from_text(text: str, source: str = "") -> tuple[str, bool]:
    text = _clean(text)
    m = SPECIFIC_ACTOR_RE.search(text)
    if m:
        return _clean(m.group(0)), True
    m = CONSUMER_RE.search(text)
    if m:
        return _clean(m.group(0)), True
    return "UNKNOWN", False


def _workflow_from_text(text: str) -> tuple[str, str]:
    text=_clean(text); matches=[]
    priority={"booking":1,"billing":1,"sales":1,"support":1,"intake":1,"ops":1,"compliance":1,"research":1,"reading_study":1,"coordination":2,"backoffice":3}
    for name,pattern in WORKFLOW_PATTERNS.items():
        m=pattern.search(text)
        if m: matches.append((m.start(),priority.get(name,5),name,_clean(m.group(0))))
    if not matches: return "", ""
    _,_,name,exact=min(matches)
    return name,exact


def _vertical_from_text(text: str) -> str:
    text=_clean(text); matches=[]
    for name,pattern in VERTICAL_PATTERNS.items():
        m=pattern.search(text)
        if m: matches.append((m.start(),name))
    return min(matches)[1] if matches else "other"


def _role_text(problem: str, workaround: str, consequence: str) -> str:
    parts=[]
    for x in (problem, workaround, consequence):
        x=_clean(x)
        if x and x not in parts:
            parts.append(x)
    return " ".join(parts)


def _actor_from_role_spans(problem: str, workaround: str, consequence: str) -> tuple[str, bool]:
    return _actor_from_text(_role_text(problem, workaround, consequence))


def _workflow_from_role_spans(problem: str, workaround: str, consequence: str) -> tuple[str, str]:
    return _workflow_from_text(_role_text(problem, workaround, consequence))


def _vertical_from_role_spans(problem: str, workaround: str, consequence: str) -> str:
    return _vertical_from_text(_role_text(problem, workaround, consequence))


def _context_role_text(doc: dict[str, Any] | None, exact_span: str) -> str:
    if not doc or not exact_span:
        return ""
    title=_clean(doc.get("title"))
    ss=_sentences(_clean(doc.get("text")), 30)
    exact=_clean(exact_span)
    idx=-1
    for i,s in enumerate(ss):
        if s == exact or exact in s or s in exact:
            idx=i; break
    nearby=[]
    if idx >= 0:
        nearby=ss[max(0,idx-1):min(len(ss),idx+2)]
    else:
        nearby=[exact]
    return _clean(" ".join(([title] if title else []) + nearby))


def classify_document(text: str, source: str = "") -> dict[str, Any]:
    text = _clean(text)
    source = str(source or "").lower()
    frontier = bool(FRONTIER_RE.search(text))
    broad = bool(BROAD_AI_RE.search(text))
    research_paper = _is_research_paper(text)
    workflows = _tag_names(text, WORKFLOW_PATTERNS)
    verticals = _tag_names(text, VERTICAL_PATTERNS)
    actor, actor_explicit = _actor_from_text(text, source)
    capabilities = _normalized_capabilities(text)
    legacy = bool(LEGACY_RE.search(text))
    burden_sentence = _burden_sentence(text)
    economic = bool(burden_sentence)
    friction_sentence = _strict_sentence(text, all_patterns=(FRICTION_RE,), any_patterns=(WORKFLOW_RE, LEGACY_RE, DIRECT_BEHAVIOR_RE), forbid_patterns=(BENEFIT_CLAIM_RE,))
    friction = bool(friction_sentence)
    frequency = bool(FREQUENCY_RE.search(text))
    dissatisfaction = bool(DISSATISFACTION_RE.search(text))
    distribution_sentence = _distribution_sentence(text)
    distribution_gap = bool(distribution_sentence)
    supply_sentence = _supply_sentence(text)
    supply = bool(supply_sentence)
    change_sentence = _change_sentence(text)
    change = bool(change_sentence and capabilities)
    second_order_sentence = _second_order_sentence(text)
    second_order = bool(second_order_sentence)
    developer_only = bool(DEVELOPER_ONLY_RE.search(text)) and not actor_explicit
    problem_sentence = _problem_sentence(text)
    workaround_sentence = _workaround_sentence(text)
    direct_behavior = bool(DIRECT_BEHAVIOR_RE.search(text))
    return {
        "frontier": frontier,
        "broad": broad,
        "research_paper": research_paper,
        "workflows": sorted(workflows),
        "verticals": sorted(verticals),
        "actor": actor,
        "actor_explicit": actor_explicit,
        "capabilities": sorted(capabilities),
        "legacy": legacy,
        "economic": economic,
        "friction": friction,
        "frequency": frequency,
        "dissatisfaction": dissatisfaction,
        "distribution_gap": distribution_gap,
        "supply": supply,
        "change": change,
        "second_order": second_order,
        "developer_only": developer_only,
        "problem_sentence": problem_sentence,
        "workaround_sentence": workaround_sentence,
        "burden_sentence": burden_sentence,
        "friction_sentence": friction_sentence,
        "change_sentence": change_sentence,
        "supply_sentence": supply_sentence,
        "distribution_sentence": distribution_sentence,
        "second_order_sentence": second_order_sentence,
        "direct_behavior": direct_behavior,
        "has_transition_change": change and source in STRUCTURAL_CHANGE_SOURCES and not frontier and not broad and not research_paper,
        "has_commercial_lag": bool(problem_sentence and workaround_sentence and burden_sentence and actor_explicit) and source in PRIMARY_LAG_SOURCES and not frontier and not broad and not research_paper and not developer_only,
        "has_boring_ops": bool(problem_sentence and workaround_sentence and burden_sentence and actor_explicit) and source in BORING_OPS_SOURCES and not frontier and not broad and not research_paper and not developer_only,
        "has_micro_friction": bool(problem_sentence and workaround_sentence and friction and actor_explicit and (frequency or direct_behavior)) and source in DIRECT_PAIN_SOURCES and not frontier and not broad and not developer_only,
        "has_supply": supply and bool(workflows or verticals or actor_explicit) and source in PRIMARY_SUPPLY_SOURCES and not frontier and not broad and not research_paper,
        "has_wedge_pain": bool(problem_sentence and workaround_sentence and actor_explicit and (friction or economic or dissatisfaction)) and source in WEDGE_PAIN_SOURCES and not frontier and not broad and not research_paper and not developer_only,
        "has_second_order": bool(second_order_sentence and problem_sentence and actor_explicit) and source in SECOND_ORDER_SOURCES and not frontier and not broad and not research_paper and not developer_only,
    }


def _is_primary_lag_doc(doc: dict[str, Any]) -> bool:
    source = str(doc.get("source") or "").lower()
    table = str(doc.get("table") or "").lower()
    return table in {"posts", "product_reviews"} or source in PRIMARY_LAG_SOURCES


def _pair_compatible(a: dict[str, Any], b: dict[str, Any], *, require_capability: bool = False) -> tuple[bool, dict[str, Any]]:
    at = _clean(a.get("text")); bt = _clean(b.get("text"))
    aw = _tag_names(at, WORKFLOW_PATTERNS); bw = _tag_names(bt, WORKFLOW_PATTERNS)
    av = _tag_names(at, VERTICAL_PATTERNS); bv = _tag_names(bt, VERTICAL_PATTERNS)
    caps = _normalized_capabilities(at)
    if require_capability:
        # A vertical-specific change may not jump to an unrelated vertical.
        if av and bv and not (av & bv):
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
        compatible = {cap for cap in caps if CAPABILITY_WORKFLOW.get(cap, set()) & bw}
        if not compatible:
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
        shared_workflows = aw & bw
        # Generic phone/backoffice overlap is not enough to transplant an appointment-specific change into ordering, logistics, etc.
        if aw and bw and shared_workflows and shared_workflows <= {"support", "backoffice", "coordination"} and not (av & bv):
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
        if aw and bw and not shared_workflows and not (av & bv):
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
        caps = compatible
    else:
        # Existing-market wedges need a shared market/segment, not merely a generic shared word like "sales".
        if not (av and bv and (av & bv)):
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
        if aw and bw and not (aw & bw):
            return False, {"workflows": sorted(bw), "verticals": sorted(bv), "capabilities": sorted(caps)}
    return True, {
        "workflows": sorted(bw or aw),
        "verticals": sorted(bv or av),
        "capabilities": sorted(caps),
        "vertical_match": sorted(av & bv),
        "workflow_match": sorted(aw & bw),
    }


def _tfidf_pairs(left: list[dict[str, Any]], right: list[dict[str, Any]], *, require_capability: bool, top_neighbors: int = 14) -> list[dict[str, Any]]:
    if not left or not right:
        return []
    lt = [_clean(d.get("text"))[:1800] for d in left]
    rt = [_clean(d.get("text"))[:1800] for d in right]
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, max_features=26000)
        x = vec.fit_transform(lt + rt)
        sim = cosine_similarity(x[:len(lt)], x[len(lt):])
    except Exception:
        sim = np.zeros((len(lt), len(rt)))
    out = []
    for i, adoc in enumerate(left):
        atok = _tokens(lt[i])
        for jj in np.argsort(sim[i])[::-1][:top_neighbors]:
            j = int(jj); bdoc = right[j]
            if _doc_id(adoc) == _doc_id(bdoc):
                continue
            ok, meta = _pair_compatible(adoc, bdoc, require_capability=require_capability)
            if not ok:
                continue
            btok = _tokens(rt[j]); overlap = len(atok & btok) / max(1, min(len(atok), len(btok))) if atok and btok else 0.0
            score = float(sim[i, j]) + overlap * 0.18 + (0.05 if adoc.get("source") != bdoc.get("source") else 0.0)
            if meta.get("vertical_match"): score += 0.07
            if meta.get("workflow_match"): score += 0.07
            if require_capability and meta.get("capabilities"): score += 0.07
            if score < 0.05 and not meta.get("vertical_match") and not meta.get("workflow_match"):
                continue
            out.append({"left": adoc, "right": bdoc, "score": round(score, 4), "compatibility": meta})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _unit_from_docs(lane: str, problem_doc: dict[str, Any], context_doc: dict[str, Any] | None = None, score: float = 0.0, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    ptext = _clean(problem_doc.get("text"))
    psource = str(problem_doc.get("source") or "").lower()
    info = classify_document(ptext, psource)

    problem_sentence = _clean(info.get("problem_sentence"))
    consequence_sentence = _clean(info.get("burden_sentence")) or _clean(info.get("friction_sentence"))
    workaround_sentence = _clean(info.get("workaround_sentence"))
    actor, actor_explicit = _actor_from_role_spans(problem_sentence, workaround_sentence, consequence_sentence)
    workflow_tag, workflow_exact = _workflow_from_role_spans(problem_sentence, workaround_sentence, consequence_sentence)
    vertical = _vertical_from_role_spans(problem_sentence, workaround_sentence, consequence_sentence)
    buyer_sentence = _sentence_containing_literal(_role_text(problem_sentence, workaround_sentence, consequence_sentence), actor) if actor_explicit else ""

    context_text = _clean((context_doc or {}).get("text"))
    csource = str((context_doc or {}).get("source") or "").lower()
    context_info = classify_document(context_text, csource) if context_doc else {}
    change_sentence = _clean(context_info.get("change_sentence")) if context_doc and lane == "TRANSITION_GAP" else ""
    supply_sentence = _clean(context_info.get("supply_sentence")) if context_doc and lane in {"PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"} else ""
    second_order_sentence = _clean(info.get("second_order_sentence")) if lane == "SECOND_ORDER_PAIN" else ""
    distribution_sentence = _clean(info.get("distribution_sentence")) if lane == "DISTRIBUTION_MODEL_GAP" else ""
    context_exact = change_sentence or supply_sentence
    context_role_text = _context_role_text(context_doc, context_exact)

    docs = [problem_doc] + ([context_doc] if context_doc else [])
    return {
        "lane": lane, "problem_doc": problem_doc, "context_doc": context_doc, "corroboration_doc": None,
        "docs": docs, "score": float(score), "compatibility": meta or {},
        "truth": {
            "actor": actor, "actor_explicit": actor_explicit,
            "actor_category": "consumer" if vertical == "consumer" else ("business" if actor_explicit else "other"),
            "workflow_tag": workflow_tag, "workflow_exact": workflow_exact, "vertical": vertical,
            "problem_sentence": problem_sentence, "consequence_sentence": consequence_sentence, "workaround_sentence": workaround_sentence,
            "buyer_sentence": buyer_sentence, "change_sentence": change_sentence, "supply_sentence": supply_sentence,
            "second_order_sentence": second_order_sentence, "distribution_sentence": distribution_sentence,
            "context_role_text": context_role_text,
            "economic_explicit": bool(info.get("economic")), "friction_explicit": bool(info.get("friction")),
            "frequency_explicit": bool(info.get("frequency")), "direct_behavior_explicit": bool(info.get("direct_behavior")),
            "distribution_gap_explicit": bool(info.get("distribution_gap")), "opportunity_classes": [lane],
            "context_info": context_info,
            "problem_source_role": "DIRECT_BEHAVIOR" if psource in DIRECT_PAIN_SOURCES else ("OPERATIONAL_OBSERVATION" if psource in BORING_OPS_SOURCES else "MARKET_OBSERVATION"),
            "context_source_role": "STRUCTURAL_CHANGE" if lane == "TRANSITION_GAP" else ("PAID_SUPPLY" if lane in {"PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"} else "NONE"),
            "corroborated": False, "corroboration_problem_sentence": "", "corroboration_ref": "", "corroboration_score": 0.0,
        },
    }


def _norm_key_text(v: Any) -> str:
    words=re.sub(r"\W+"," ",str(v or "").lower()).split()
    out=[]
    for w in words:
        if len(w)>4 and w.endswith("s") and not w.endswith("ss"):
            w=w[:-1]
        out.append(w)
    return " ".join(out)

def _unit_key(unit: dict[str, Any]) -> str:
    t = unit["truth"]
    actor = _norm_key_text(t.get("actor") or "unknown")
    workflow = str(t.get("workflow_tag") or "other")
    vertical = str(t.get("vertical") or "other")
    basis = _clean(t.get("workaround_sentence")) or _clean(t.get("problem_sentence"))[:120]
    m = LEGACY_RE.search(basis)
    legacy = _norm_key_text(m.group(0) if m else basis[:50])
    # Deliberately exclude lane and trailing consequence wording so the same underlying workflow cannot survive twice.
    return f"{vertical}|{workflow}|{actor}|{legacy}"


def _same_market_context(unit: dict[str, Any]) -> bool:
    lane=unit["lane"]; t=unit["truth"]
    if lane not in {"TRANSITION_GAP","PROVEN_MARKET_WEDGE","DISTRIBUTION_MODEL_GAP"}:
        return True
    context=_clean(t.get("context_role_text"))
    if not context:
        return False
    pw=str(t.get("workflow_tag") or "")
    pv=str(t.get("vertical") or "other")
    cw=_tag_names(context, WORKFLOW_PATTERNS)
    cv=_tag_names(context, VERTICAL_PATTERNS)
    # Same workflow is mandatory. Vertical must also match whenever the problem has a specific vertical.
    if not pw or pw not in cw:
        return False
    if pv not in {"", "other"} and pv not in cv:
        return False
    return True


def _pain_signature(doc: dict[str, Any]) -> dict[str, Any] | None:
    text=_clean(doc.get("text")); source=str(doc.get("source") or "").lower()
    info=classify_document(text,source)
    problem=_clean(info.get("problem_sentence")); workaround=_clean(info.get("workaround_sentence")); burden=_clean(info.get("burden_sentence")) or _clean(info.get("friction_sentence"))
    actor,actor_explicit=_actor_from_role_spans(problem,workaround,burden)
    workflow,_=_workflow_from_role_spans(problem,workaround,burden)
    vertical=_vertical_from_role_spans(problem,workaround,burden)
    if not problem or not actor_explicit or not workflow:
        return None
    role=_role_text(problem,workaround,burden)
    return {"problem":problem,"workaround":workaround,"burden":burden,"actor":actor,"workflow":workflow,"vertical":vertical,"role":role}


def _find_corroboration(problem_doc: dict[str, Any], pool: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, str]:
    base=_pain_signature(problem_doc)
    if not base:
        return None,0.0,""
    bt=_content_tokens(base["role"]); best=None; best_score=0.0; best_problem=""
    for d in pool:
        if _doc_id(d)==_doc_id(problem_doc):
            continue
        sig=_pain_signature(d)
        if not sig or sig["workflow"]!=base["workflow"]:
            continue
        if base["vertical"] not in {"", "other"} and sig["vertical"]!=base["vertical"]:
            continue
        dt=_content_tokens(sig["role"]); overlap=len(bt & dt)/max(1,min(len(bt),len(dt))) if bt and dt else 0.0
        shared=bt & dt
        # Workflow words and stopwords are already removed. Require real domain/object overlap, not "every/time/because".
        if len(shared) < 2 or overlap < 0.15:
            continue
        if base["vertical"] in {"consumer","education"} and sig["actor"].lower().rstrip("s") != base["actor"].lower().rstrip("s"):
            continue
        source_bonus=0.05 if str(d.get("source")) != str(problem_doc.get("source")) else 0.0
        score=overlap+source_bonus
        if score>best_score:
            best,best_score,best_problem=d,score,sig["problem"]
    return best,round(best_score,4),best_problem


def _attach_corroboration(unit: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any]:
    d,score,problem=_find_corroboration(unit["problem_doc"],pool)
    if not d:
        return unit
    unit=dict(unit); unit["docs"]=list(unit.get("docs") or [])+[d]; unit["corroboration_doc"]=d
    t=dict(unit["truth"]); t.update({"corroborated":True,"corroboration_problem_sentence":problem,"corroboration_ref":_doc_id(d),"corroboration_score":score})
    unit["truth"]=t; unit["score"]=float(unit.get("score",0))+min(0.18,score*0.18)
    return unit


def _valid_unit_deterministic(unit: dict[str, Any]) -> bool:
    lane = unit["lane"]; t = unit["truth"]
    problem = _clean(t.get("problem_sentence")); workaround = _clean(t.get("workaround_sentence")); actor=_clean(t.get("actor"))
    if not problem or not t.get("workflow_tag") or not t.get("actor_explicit") or not _known(actor):
        return False
    if lane != "SECOND_ORDER_PAIN" and not workaround:
        return False
    if BROAD_AI_RE.search(problem) or FRONTIER_RE.search(problem) or RESEARCH_PAPER_RE.search(problem):
        return False
    if PROMOTIONAL_PROOF_RE.search(problem) or SOLUTION_MARKETING_RE.search(problem) or BENEFIT_CLAIM_RE.search(problem):
        return False
    if not WORKFLOW_RE.search(problem):
        return False
    # Actor/workflow are role-local, never inferred from unrelated prose elsewhere in the document.
    role=_role_text(problem,workaround,_clean(t.get("consequence_sentence")))
    if not re.search(r"\b"+re.escape(actor)+r"\b",role,re.I):
        return False
    if lane != "SECOND_ORDER_PAIN":
        if not WORKAROUND_METHOD_RE.search(workaround):
            return False
        if BENEFIT_CLAIM_RE.search(workaround) or SOLUTION_MARKETING_RE.search(workaround) or PROMOTIONAL_PROOF_RE.search(workaround):
            return False
    if lane in {"TRANSITION_GAP","PROVEN_MARKET_WEDGE","DISTRIBUTION_MODEL_GAP"} and not _same_market_context(unit):
        return False
    # Discovery persistence requires a second role-qualified pain document. Single-source pain remains a source-gap signal, not an opportunity candidate.
    if not t.get("corroborated"):
        return False

    if lane == "TRANSITION_GAP":
        change=_clean(t.get("change_sentence"))
        return bool(t.get("economic_explicit") and change and STRUCTURAL_CHANGE_RE.search(change) and not FUNDING_RE.search(change))
    if lane == "PROVEN_MARKET_WEDGE":
        supply=_clean(t.get("supply_sentence"))
        return bool(supply and HARD_PAY_SIGNAL_RE.search(supply) and not FUNDING_RE.search(supply) and (t.get("friction_explicit") or t.get("economic_explicit")))
    if lane == "DISTRIBUTION_MODEL_GAP":
        supply=_clean(t.get("supply_sentence")); dist=_clean(t.get("distribution_sentence"))
        return bool(supply and HARD_PAY_SIGNAL_RE.search(supply) and not FUNDING_RE.search(supply) and dist and t.get("distribution_gap_explicit"))
    if lane == "BORING_OPS":
        return bool(t.get("economic_explicit") and NEGATIVE_BURDEN_RE.search(_clean(t.get("consequence_sentence"))))
    if lane == "MICRO_FRICTION":
        return bool(t.get("friction_explicit") and (t.get("frequency_explicit") or t.get("direct_behavior_explicit")))
    if lane == "SECOND_ORDER_PAIN":
        second=_clean(t.get("second_order_sentence"))
        return bool(second and SECOND_ORDER_RE.search(second) and (t.get("friction_explicit") or t.get("economic_explicit")))
    return False


def _deterministic_confidence(unit: dict[str, Any]) -> float:
    t = unit["truth"]
    score = 0.80
    if t.get("actor_explicit"): score += 0.03
    if t.get("economic_explicit"): score += 0.03
    if t.get("friction_explicit"): score += 0.02
    if t.get("frequency_explicit") or t.get("direct_behavior_explicit"): score += 0.02
    if unit.get("context_doc"): score += 0.03
    if t.get("vertical") not in {"", "other"}: score += 0.02
    if t.get("corroborated"): score += 0.04
    return round(min(0.95, score), 2)


LANE_SPECIFICITY = {
    "SECOND_ORDER_PAIN": 6,
    "TRANSITION_GAP": 5,
    "DISTRIBUTION_MODEL_GAP": 4,
    "PROVEN_MARKET_WEDGE": 3,
    "MICRO_FRICTION": 2,
    "BORING_OPS": 1,
}


def _semantic_specificity(unit: dict[str, Any]) -> int:
    return int(LANE_SPECIFICITY.get(str(unit.get("lane") or ""), 0))


def _diverse_take(units: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    units = sorted(units, key=lambda x: float(x.get("score", 0)), reverse=True)
    out: list[dict[str, Any]] = []
    bucket_counts: Counter = Counter()
    seen: set[str] = set()
    for u in units:
        if not _valid_unit_deterministic(u):
            continue
        k = _unit_key(u)
        if k in seen:
            continue
        t = u["truth"]
        bucket = (u["lane"], t.get("vertical"), t.get("workflow_tag"))
        if bucket_counts[bucket] >= 3:
            continue
        seen.add(k); bucket_counts[bucket] += 1; out.append(u)
        if len(out) >= limit:
            break
    return out


def build_portfolio_units(docs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    classified=[]; rejected_research_papers=0
    for d in docs:
        info=classify_document(d.get("text", ""), str(d.get("source") or ""))
        if info.get("research_paper"): rejected_research_papers += 1
        classified.append((d,info))
    changes=[d for d,i in classified if i["has_transition_change"]]
    commercial_lag=[d for d,i in classified if i["has_commercial_lag"] and _is_primary_lag_doc(d)]
    boring=[d for d,i in classified if i["has_boring_ops"]]
    micro=[d for d,i in classified if i["has_micro_friction"]]
    supplies=[d for d,i in classified if i["has_supply"]]
    wedge_pain=[d for d,i in classified if i["has_wedge_pain"]]
    second=[d for d,i in classified if i["has_second_order"]]
    pain_pool=[]; seen_docs=set()
    for d in commercial_lag+wedge_pain+boring+micro+second:
        did=_doc_id(d)
        if did not in seen_docs:
            pain_pool.append(d); seen_docs.add(did)

    lane_units: dict[str,list[dict[str,Any]]]=defaultdict(list)
    raw_before_corroboration=Counter()
    for pair in _tfidf_pairs(changes[:500],commercial_lag[:700],require_capability=True,top_neighbors=10):
        u=_unit_from_docs("TRANSITION_GAP",pair["right"],pair["left"],pair["score"],pair["compatibility"]); raw_before_corroboration["TRANSITION_GAP"]+=1
        u=_attach_corroboration(u,pain_pool)
        if _valid_unit_deterministic(u): lane_units["TRANSITION_GAP"].append(u)
    for pair in _tfidf_pairs(supplies[:500],wedge_pain[:700],require_capability=False,top_neighbors=10):
        pinfo=classify_document(pair["right"].get("text", ""),str(pair["right"].get("source") or ""))
        lane="DISTRIBUTION_MODEL_GAP" if pinfo.get("distribution_gap") else "PROVEN_MARKET_WEDGE"; raw_before_corroboration[lane]+=1
        u=_unit_from_docs(lane,pair["right"],pair["left"],pair["score"],pair["compatibility"]); u=_attach_corroboration(u,pain_pool)
        if _valid_unit_deterministic(u): lane_units[lane].append(u)
    for d in boring[:900]:
        info=classify_document(d.get("text", ""),str(d.get("source") or "")); raw_before_corroboration["BORING_OPS"]+=1
        score=0.50+(0.12 if info["frequency"] else 0)+(0.15 if info["friction"] else 0)+(0.18 if info["economic"] else 0)
        u=_attach_corroboration(_unit_from_docs("BORING_OPS",d,None,score),pain_pool)
        if _valid_unit_deterministic(u): lane_units["BORING_OPS"].append(u)
    for d in micro[:1200]:
        info=classify_document(d.get("text", ""),str(d.get("source") or "")); raw_before_corroboration["MICRO_FRICTION"]+=1
        score=0.48+(0.18 if info["frequency"] else 0)+(0.22 if info["friction"] else 0)+(0.08 if info["economic"] else 0)
        u=_attach_corroboration(_unit_from_docs("MICRO_FRICTION",d,None,score),pain_pool)
        if _valid_unit_deterministic(u): lane_units["MICRO_FRICTION"].append(u)
    for d in second[:500]:
        info=classify_document(d.get("text", ""),str(d.get("source") or "")); raw_before_corroboration["SECOND_ORDER_PAIN"]+=1
        score=0.55+(0.16 if info["economic"] else 0)+(0.12 if info["frequency"] else 0)
        u=_attach_corroboration(_unit_from_docs("SECOND_ORDER_PAIN",d,None,score),pain_pool)
        if _valid_unit_deterministic(u): lane_units["SECOND_ORDER_PAIN"].append(u)

    quotas={lane:8 for lane in LANES}; selected_raw=[]
    for lane in LANES: selected_raw.extend(_diverse_take(lane_units.get(lane,[]),quotas[lane]))
    best_by_key={}
    for u in selected_raw:
        k=_unit_key(u); prev=best_by_key.get(k)
        if prev is None or (_semantic_specificity(u),float(u.get("score",0)))>(_semantic_specificity(prev),float(prev.get("score",0))): best_by_key[k]=u
    selected=sorted(best_by_key.values(),key=lambda u:(_semantic_specificity(u),float(u.get("score",0))),reverse=True)[:MAX_SCREEN_POOL]
    source_gap_by_lane={}
    for lane in LANES:
        formed=len(lane_units.get(lane,[])); raw=int(raw_before_corroboration.get(lane,0))
        source_gap_by_lane[lane]={"pre_corroboration":raw,"corroborated_role_locked":formed,"status":"AVAILABLE" if formed else ("CORPUS_OR_CORROBORATION_GAP" if raw else "CORPUS_GAP")}
    formation={
        "change_docs":len(changes),"commercial_lag_docs":len(commercial_lag),"supply_docs":len(supplies),"wedge_pain_docs":len(wedge_pain),
        "boring_ops_docs":len(boring),"micro_friction_docs":len(micro),"second_order_docs":len(second),
        "research_papers_rejected_from_formation":rejected_research_papers,"raw_lane_units":dict(raw_before_corroboration),
        "corroborated_lane_units":{lane:len(lane_units.get(lane,[])) for lane in LANES},
        "screen_pool_by_lane":dict(Counter(u["lane"] for u in selected)),
        "screen_pool_verticals":dict(Counter(u["truth"].get("vertical") or "other" for u in selected)),
        "screen_pool_workflows":dict(Counter(u["truth"].get("workflow_tag") or "other" for u in selected)),
        "source_gap_by_lane":source_gap_by_lane,
        "role_lock":"problem/workaround/burden are role-local; change/supply must match the exact workflow+vertical; persistence requires a second role-qualified pain document",
    }
    return selected,formation


class OpportunityPortfolioDiscovery:
    def __init__(self, *, ai_call_allowance: int = 2, max_persist: int = MAX_PERSIST_PER_RUN, persist: bool = True):
        self.ai_call_allowance = max(0, int(ai_call_allowance))
        self.max_persist = max(1, int(max_persist))
        self.persist_enabled = bool(persist)
        self.usage = TokenUsage(); self.llm_calls = 0
        self.source_portfolio_health: dict[str, Any] = {}

    async def _load_docs(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        cross = ProblemCandidateEngine(fingerprint_ai_call_allowance=0, profile_ai_call_allowance=0, verify_ai_call_allowance=0, translate=False)
        await cross.reflect_schema(); await cross.load_sources()
        docs: list[dict[str, Any]] = []; source_counts: dict[str, int] = {}
        for source, rows in cross.docs.items():
            if source in {"arxiv", "huggingface"}:
                continue
            source_counts[source] = len(rows)
            for row in rows[:2500]:
                docs.append({**row, "text": _clean(row.get("text"))[:2200]})

        community = OpportunityEngine(fingerprint_ai_call_allowance=0)
        posts = await community.find_candidates(); discussions = community.build_discussions(posts)
        source_counts["community_structured"] = len(discussions)
        for d in discussions[:2500]:
            posts0 = d.get("posts") or []; first = posts0[0] if posts0 else {}
            docs.append({
                "source": str(d.get("platform") or "community"), "table": "posts", "pk": str(d.get("discussion_key") or ""),
                "title": _clean(first.get("title"))[:500], "text": _clean(d.get("problem_text"))[:2200],
                "url": _clean(first.get("url")), "date": str(d.get("observed_at") or ""),
            })

        async with async_session() as session:
            raw_posts = list((await session.execute(
                select(Post).where(Post.body.isnot(None)).order_by(Post.score.desc(), Post.created_at.desc()).limit(5000)
            )).scalars().all())
            review_rows = list((await session.execute(
                select(ProductReview).order_by(ProductReview.updated_at.desc()).limit(1000)
            )).scalars().all())
        raw_added = 0
        for row in raw_posts:
            text0 = _clean(" ".join([str(getattr(row, "title", "") or ""), str(getattr(row, "body", "") or "")]))
            if len(text0) < 40:
                continue
            docs.append({
                "source": "community_raw", "table": "posts", "pk": str(getattr(row, "id", "") or ""),
                "title": _clean(getattr(row, "title", ""))[:500], "text": text0[:2200], "url": _clean(getattr(row, "url", "")),
                "date": str(getattr(row, "posted_at", "") or getattr(row, "created_at", "") or ""),
            }); raw_added += 1
        source_counts["community_raw"] = raw_added

        review_added = 0
        for review in review_rows:
            product = _clean(getattr(review, "product_name", ""))
            if not product:
                continue
            parts = [
                product,
                "CONS " + " ; ".join(str(x) for x in (getattr(review, "cons", None) or []) if x),
                "CHURN " + " ; ".join(str(x) for x in (getattr(review, "churn_reasons", None) or []) if x),
                "FEATURE_REQUESTS " + " ; ".join(str(x) for x in (getattr(review, "feature_requests", None) or []) if x),
            ]
            text0 = _clean(" ".join(x for x in parts if x))
            if len(text0) < 40:
                continue
            docs.append({
                "source": "product_review", "table": "product_reviews", "pk": str(getattr(review, "id", "") or ""),
                "title": f"{product} product review summary"[:500], "text": text0[:2200], "url": "",
                "date": str(getattr(review, "updated_at", "") or getattr(review, "calculated_at", "") or ""),
            }); review_added += 1
        source_counts["product_review"] = review_added

        # V10 expands the world SignalForge can see before opportunity formation.
        # Public source adapters are bounded, read-only, cached, and fail-soft.
        try:
            from processors.opportunity_source_portfolio import refresh_source_portfolio
            external_docs, source_health = await asyncio.to_thread(refresh_source_portfolio, force=False)
            self.source_portfolio_health = dict(source_health or {})
            existing = {_doc_id(d) for d in docs}
            ext_added = 0
            for d in external_docs:
                did = _doc_id(d)
                if did in existing:
                    continue
                existing.add(did); docs.append({**d, "text": _clean(d.get("text"))[:2200]}); ext_added += 1
                src = str(d.get("source") or "external")
                source_counts[src] = int(source_counts.get(src, 0)) + 1
            self.source_portfolio_health["docs_merged_into_discovery"] = ext_added
        except Exception as exc:
            self.source_portfolio_health = {"status": "DEGRADED", "error": f"{type(exc).__name__}: {exc}", "docs_merged_into_discovery": 0}
        return docs, source_counts

    async def _screen(self, units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        screened = model_accepts = hard_rejects = malformed = 0
        for start in range(0, len(units), MAX_PER_LLM_CALL):
            if self.llm_calls >= self.ai_call_allowance:
                break
            batch = units[start:start + MAX_PER_LLM_CALL]
            payload = []; idmap: dict[str, dict[str, Any]] = {}
            for i, unit in enumerate(batch):
                pid = f"P{i+1}"; idmap[pid] = unit
                pdoc = unit["problem_doc"]; cdoc = unit.get("context_doc"); t = unit["truth"]
                payload.append({
                    "id": pid,
                    "lane": unit["lane"],
                    "problem_source": str(pdoc.get("source") or ""),
                    "problem_title": _clean(pdoc.get("title"))[:180],
                    "actor_span": _clean(t.get("actor")),
                    "workflow_span": _clean(t.get("workflow_exact")),
                    "problem_span": _clean(t.get("problem_sentence")),
                    "workaround_span": _clean(t.get("workaround_sentence")),
                    "burden_or_friction_span": _clean(t.get("consequence_sentence")),
                    "context_source": str((cdoc or {}).get("source") or ""),
                    "change_or_supply_span": _clean(t.get("change_sentence")) or _clean(t.get("supply_sentence")) or _clean(t.get("second_order_sentence")),
                    "vertical": t.get("vertical"),
                    "corroboration_problem_span": _clean(t.get("corroboration_problem_sentence")),
                    "corroboration_ref": _clean(t.get("corroboration_ref")),
                })
            prompt = f"""You are the final COHERENCE veto for a SOLO-FOUNDER opportunity radar.

Every field below has already passed deterministic ROLE LOCKS.
You cannot create, repair, reinterpret, or add any fact.
Your only job is to reject a unit if its existing exact spans do not describe ONE coherent market/workflow.

INPUT:
{json.dumps(payload, ensure_ascii=False)}

Reject if:
- actor, workflow, problem, workaround/burden do not refer to the same real-world situation;
- corroboration_problem_span is not the same recurring pain/workflow in a second document;
- context/change/supply is merely a specific tool/repo/product that does not establish the lane;
- paired sources are only lexically similar but belong to different markets;
- the "problem" span is actually solution marketing, a research-paper method/result, job qualification prose, or generic productivity language;
- PROVEN_MARKET_WEDGE lacks a genuinely paid/supplied market for the same vertical;
- TRANSITION_GAP lacks a real temporal/structural change applicable to the exact lagging workflow;
- MICRO_FRICTION is not a directly observed recurring user behavior/workaround;
- BORING_OPS is merely a job responsibility without evidence of current burden;
- SECOND_ORDER_PAIN does not explicitly connect adoption/use to the new downstream pain.

False positives are much worse than omissions.

OUTPUT compact NDJSON, exactly one object per id, same order, no array, no markdown:
{{"i":"P1","a":0}}
or
{{"i":"P1","a":1}}
No confidence and no other keys.
"""
            self.llm_calls += 1
            raw = await call_llm(
                prompt=prompt,
                system_message="Veto incoherent opportunity units. Never generate facts. Prefer reject when uncertain.",
                model="mini", parse_json=False, usage_tracker=self.usage, max_tokens=1800, temperature=0.0,
            )
            returned = _parse_llm_items(raw); screened += len(batch)
            by_id = {str(x.get("i") or x.get("id") or ""): x for x in returned if isinstance(x, dict)}
            for pid, unit in idmap.items():
                item = by_id.get(pid)
                if not isinstance(item, dict):
                    malformed += 1
                    continue
                if item.get("a") not in (1, True, "1", "true", "TRUE"):
                    hard_rejects += 1
                    continue
                model_accepts += 1
                unit = dict(unit)
                unit["confidence"] = _deterministic_confidence(unit)
                accepted.append(unit)

        accepted.sort(key=lambda u: (_semantic_specificity(u), float(u.get("confidence", 0)), float(u.get("score", 0))), reverse=True)
        out: list[dict[str, Any]] = []; seen: set[str] = set(); lane_counts: Counter = Counter()
        for u in accepted:
            if not _valid_unit_deterministic(u):
                continue
            k = _unit_key(u)
            if k in seen:
                continue
            if lane_counts[u["lane"]] >= 3:
                continue
            seen.add(k); lane_counts[u["lane"]] += 1; out.append(u)
            if len(out) >= self.max_persist:
                break
        return out, {
            "pairs_screened": screened,
            "model_accepts": model_accepts,
            "hard_rejects": hard_rejects,
            "malformed_or_missing": malformed,
            "unscreened_due_to_budget": max(0, len(units) - screened),
            "accepted_by_lane": dict(Counter(u["lane"] for u in out)),
            "model_output_contract": "ACCEPT_REJECT_ONLY_NO_CONFIDENCE",
        }

    def _fingerprint(self, unit: dict[str, Any]) -> dict[str, Any]:
        t = unit["truth"]; lane = unit["lane"]; pdoc = unit["problem_doc"]; cdoc = unit.get("context_doc")
        problem_sentence = _clean(t.get("problem_sentence"))
        consequence = _clean(t.get("consequence_sentence")) or "UNKNOWN"
        workaround = _clean(t.get("workaround_sentence")) or "UNKNOWN"
        buyer = _clean(t.get("buyer_sentence")) or "UNKNOWN"
        change = _clean(t.get("change_sentence")) or "UNKNOWN"
        supply = _clean(t.get("supply_sentence")) or "UNKNOWN"
        second = _clean(t.get("second_order_sentence")) or "UNKNOWN"
        refs = [_doc_id(pdoc)] + ([_doc_id(cdoc)] if cdoc else [])
        fp = {
            "actionable_problem": True,
            "opportunity_unit_ready": True,
            "opinion_or_news_only": False,
            "confidence": float(unit.get("confidence", 0) or 0),
            "actor": _clean(t.get("actor")) or "UNKNOWN",
            "actor_category": _clean(t.get("actor_category")) or "other",
            "task": _clean(t.get("workflow_exact")) or _clean(t.get("workflow_tag")) or "UNKNOWN",
            "object": _clean(t.get("workflow_tag")) or "UNKNOWN",
            "failure_mode": problem_sentence,
            "consequence": consequence,
            "workaround": workaround,
            "buyer_context": buyer,
            "canonical_problem": problem_sentence,
            "severity": 3 if t.get("economic_explicit") else 2,
            "discovery_mode": "MULTI_LANE_EVIDENCE_LOCKED",
            "opportunity_classes": list(t.get("opportunity_classes") or [lane]),
            "primary_opportunity_class": lane,
            "opportunity_discovery_version": ENGINE_VERSION,
            "evidence_locked": True,
            "role_locked": True,
            "role_local": True,
            "corroborated_discovery": bool(t.get("corroborated")),
            "corroboration_ref": _clean(t.get("corroboration_ref")) or "UNKNOWN",
            "corroboration_score": float(t.get("corroboration_score",0) or 0),
            "evidence_locked_fields": {
                "problem_statement": {"ref": _doc_id(pdoc), "text": problem_sentence},
                "actor": {"ref": _doc_id(pdoc), "text": _clean(t.get("actor")), "explicit": bool(t.get("actor_explicit"))},
                "workflow": {"ref": _doc_id(pdoc), "text": _clean(t.get("workflow_exact"))},
                "workaround": {"ref": _doc_id(pdoc), "text": workaround},
                "consequence": {"ref": _doc_id(pdoc), "text": consequence},
                "buyer_context": {"ref": _doc_id(pdoc), "text": buyer},
                "context": {"ref": _doc_id(cdoc) if cdoc else "", "change": change, "supply": supply, "second_order": second},
                "corroboration": {"ref": _clean(t.get("corroboration_ref")), "problem": _clean(t.get("corroboration_problem_sentence"))},
            },
            "evidence_refs": refs,
            "actor_evidence_explicit": bool(t.get("actor_explicit")),
            "economic_evidence_explicit": bool(t.get("economic_explicit")),
            "friction_evidence_explicit": bool(t.get("friction_explicit")),
            "frequency_evidence_explicit": bool(t.get("frequency_explicit")),
            "workaround_evidence_verified": _known(workaround),
            "transition_evidence_verified": lane == "TRANSITION_GAP" and _known(change),
            "market_supply_evidence_verified": lane in {"PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"} and _known(supply),
            "distribution_gap_evidence_explicit": lane == "DISTRIBUTION_MODEL_GAP" and bool(t.get("distribution_gap_explicit")),
            "second_order_evidence_verified": lane == "SECOND_ORDER_PAIN" and _known(second),
            "change_signal": change,
            "market_supply_signal": supply,
            "second_order_signal": second,
            "economic_signal": consequence if t.get("economic_explicit") else "UNKNOWN",
            "truth_boundary": "V9: role-local problem facts + same-market context + second-document pain corroboration; LLM is veto-only and emits no confidence/facts.",
            "confidence_contract": "DETERMINISTIC_EVIDENCE_COMPLETENESS_NOT_MODEL_CONFIDENCE",
        }
        return fp

    async def _quarantine_invalidated_discovery(self) -> dict[str, int]:
        changed_v61=changed_v7=changed_v8=0
        async with async_session() as session:
            rows=list((await session.execute(select(ProblemCandidate))).scalars().all())
            for row in rows:
                fp=dict(getattr(row,"fingerprint",None) or {})
                v61=fp.get("transition_discovery_version")==V61_ENGINE
                v7=fp.get("opportunity_discovery_version")==V7_ENGINE
                v8=fp.get("opportunity_discovery_version")==V8_ENGINE
                if not (v61 or v7 or v8) or fp.get("quarantined") is True: continue
                if v61: reason="V6.1 allowed LLM-generated candidate truth; superseded."
                elif v7: reason="V7 exact-source spans were not field-role locked; superseded."
                else: reason="V8 role locks were document-wide for actor/context and allowed unrelated change/supply plus single-source operational pain; superseded by V9 role-local corroborated formation."
                fp.update({"quarantined":True,"quarantine_reason":reason,"actionable_problem":False,"opportunity_unit_ready":False})
                row.fingerprint=fp
                try: row.confidence_score=0.0
                except Exception: pass
                if v61: changed_v61+=1
                if v7: changed_v7+=1
                if v8: changed_v8+=1
            await session.commit()
        return {"v61_candidates_quarantined":changed_v61,"v7_candidates_quarantined":changed_v7,"v8_candidates_quarantined":changed_v8}


    async def _persist(self, units: list[dict[str, Any]]) -> dict[str, int]:
        inserted = updated = evidence_rows = 0
        async with async_session() as session:
            for unit in units:
                fp = self._fingerprint(unit)
                if not fingerprint_is_founder_unit(fp):
                    continue
                lane = unit["lane"]; pdoc = unit["problem_doc"]; cdoc = unit.get("context_doc")
                canonical_key = "op8_" + hashlib.sha1(_unit_key(unit).encode("utf-8")).hexdigest()[:21]
                existing = (await session.execute(select(ProblemCandidate).where(ProblemCandidate.canonical_key == canonical_key))).scalar_one_or_none()
                src = Counter(str(d.get("source") or "unknown") for d in unit["docs"] if d)
                values = {
                    "canonical_key": canonical_key,
                    "title": fp["canonical_problem"][:500],
                    "problem_statement": fp["canonical_problem"][:1000],
                    "actor": fp["actor"][:500],
                    "actor_category": fp["actor_category"][:100],
                    "task": fp["task"][:800],
                    "object": fp["object"][:500],
                    "failure_mode": fp["failure_mode"][:1000],
                    "consequence": fp["consequence"][:1000],
                    "buyer_context": fp["buyer_context"][:800],
                    "workaround": fp["workaround"][:1000],
                    "community_platform": "role_locked_portfolio",
                    "discussion_key": canonical_key,
                    "community_evidence_count": 0,
                    "community_user_count": 0,
                    "stage": "candidate",
                    "market_score": 0.0,
                    "confidence_score": round(float(fp.get("confidence", 0)) * 100, 1),
                    "community_problem_score": 0.0,
                    "corroboration_score": 0.0,
                    "buyer_demand_score": 0.0,
                    "supply_gap_score": 0.0,
                    "cross_source_score": round(float(fp.get("confidence", 0)) * 100, 1) if cdoc else 0.0,
                    "source_support": dict(src),
                    "relation_support": {"evidence_locked": 1, "role_locked": 1, "opportunity_class": lane, "problem_specificity_score": 85.0},
                    "fingerprint": fp,
                    "first_seen_at": None,
                    "last_seen_at": None,
                    "calculated_at": datetime.utcnow(),
                }
                stmt = pg_insert(ProblemCandidate).values(**values)
                updates = {k: getattr(stmt.excluded, k) for k in values if k not in {"canonical_key", "founder_status"}}
                candidate_id = (await session.execute(
                    stmt.on_conflict_do_update(index_elements=[ProblemCandidate.canonical_key], set_=updates).returning(ProblemCandidate.id)
                )).scalar_one()
                if existing is None: inserted += 1
                else: updated += 1

                evidence_specs = [(pdoc, "direct_problem_corroboration", "Role-local problem/workaround source")]
                corr=unit.get("corroboration_doc")
                if corr:
                    evidence_specs.append((corr, "independent_problem_corroboration", "Second role-qualified pain document used for discovery corroboration"))
                if cdoc and lane == "TRANSITION_GAP":
                    evidence_specs.append((cdoc, "why_now", "Evidence-locked observed change source"))
                elif cdoc and lane in {"PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"}:
                    evidence_specs.append((cdoc, "solution_supply", "Evidence-locked existing market/supply source"))
                existing_evidence = list((await session.execute(select(CandidateEvidence).where(CandidateEvidence.candidate_id == candidate_id))).scalars().all())
                by_key = {(_clean(e.source_type), _clean(e.source_table), _clean(e.source_ref), _clean(e.relation)): e for e in existing_evidence}
                for doc, relation, reason in evidence_specs:
                    key = (_clean(doc.get("source")), _clean(doc.get("table")), _clean(doc.get("pk")), relation)
                    excerpt = " | ".join(_best_evidence_sentences(doc.get("text", ""), (BUYER_RE, CONSUMER_RE, WORKFLOW_RE, LEGACY_RE, ECONOMIC_RE, FRICTION_RE, DISSATISFACTION_RE, CHANGE_TRIGGER_RE, PAY_SIGNAL_RE), 5))[:900]
                    payload = {
                        "candidate_id": candidate_id, "source_type": key[0], "source_table": key[1], "source_ref": key[2], "relation": relation,
                        "title": _clean(doc.get("title"))[:500] or None, "excerpt": excerpt, "url": _clean(doc.get("url")) or None,
                        "retrieval_score": float(unit.get("score", 0) or 0), "verified": True,
                        "verification_confidence": float(unit.get("confidence", 0) or 0),
                        "evidence_metadata": {
                            "date": doc.get("date"), "reason": reason, "opportunity_class": lane,
                            "opportunity_discovery_version": ENGINE_VERSION, "evidence_locked": True,
                            "verification_scope": "ROLE_LOCAL_SOURCE_SPAN_PLUS_DISCOVERY_CORROBORATION_NOT_MARKET_GROUND_TRUTH",
                        },
                    }
                    row = by_key.get(key)
                    if row is None:
                        session.add(CandidateEvidence(**payload)); evidence_rows += 1
                    else:
                        row.title = payload["title"]; row.excerpt = payload["excerpt"]; row.url = payload["url"]
                        row.retrieval_score = payload["retrieval_score"]; row.verified = True; row.verification_confidence = payload["verification_confidence"]
                        meta = dict(row.evidence_metadata or {}); meta.update(payload["evidence_metadata"]); row.evidence_metadata = meta
            await session.commit()
        return {"inserted": inserted, "updated": updated, "evidence_rows": evidence_rows}

    async def run(self) -> dict[str, Any]:
        t0=time.perf_counter(); docs,source_counts=await self._load_docs(); t1=time.perf_counter()
        units,formation=build_portfolio_units(docs); t2=time.perf_counter()
        quarantine=await self._quarantine_invalidated_discovery() if self.persist_enabled else {"v61_candidates_quarantined":0,"v7_candidates_quarantined":0,"v8_candidates_quarantined":0}; t3=time.perf_counter()
        accepted,screening=await self._screen(units); t4=time.perf_counter()
        persisted=await self._persist(accepted) if self.persist_enabled and accepted else {"inserted":0,"updated":0,"evidence_rows":0}; t5=time.perf_counter()
        summaries=[]
        for u in accepted:
            fp=self._fingerprint(u)
            summaries.append({
                "lane":u["lane"],"problem":fp.get("canonical_problem"),"actor":fp.get("actor"),"workflow":fp.get("task"),
                "workaround":fp.get("workaround"),"economic_or_friction":fp.get("economic_signal") if fp.get("economic_signal")!="UNKNOWN" else fp.get("consequence"),
                "context":fp.get("change_signal") if fp.get("change_signal")!="UNKNOWN" else (fp.get("market_supply_signal") if fp.get("market_supply_signal")!="UNKNOWN" else fp.get("second_order_signal")),
                "corroboration":fp.get("evidence_locked_fields",{}).get("corroboration"),
                "refs":fp.get("evidence_refs"),"confidence":fp.get("confidence"),"evidence_locked":True,"role_locked":True,"role_local":True,
            })
        result={
            "engine_version":ENGINE_VERSION,"status":"PASS","source_counts":source_counts,"documents_seen":len(docs),"formation":formation,"screen_pool":len(units),
            "accepted":len(accepted),"screening":screening,"accepted_summaries":summaries,**quarantine,**persisted,
            "phase_seconds":{"load_docs":round(t1-t0,3),"formation":round(t2-t1,3),"quarantine":round(t3-t2,3),"screen":round(t4-t3,3),"persist":round(t5-t4,3),"total":round(t5-t0,3)},
            "llm_calls":self.llm_calls,"llm_tokens":int(getattr(self.usage,"total_tokens",0) or 0),"llm_cost_usd":round(float(getattr(self.usage,"estimated_cost_usd",0) or 0),6),
            "source_portfolio_health": self.source_portfolio_health,
            "truth_contract":"EXPANDED_SOURCE_PORTFOLIO; ROLE_LOCAL_EXACT_SPANS; SAME_MARKET_CONTEXT; SECOND_DOCUMENT_PAIN_CORROBORATION; LLM_VETO_ONLY",
        }
        CACHE_PATH.parent.mkdir(parents=True,exist_ok=True); CACHE_PATH.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
        return result


async def run_transition_gap_discovery(*, ai_call_allowance: int = 2, max_persist: int = MAX_PERSIST_PER_RUN, persist: bool = True) -> dict[str, Any]:
    """Backward-compatible entry point; now runs V10 source-expanded multi-lane role-local corroborated portfolio discovery."""
    return await OpportunityPortfolioDiscovery(ai_call_allowance=ai_call_allowance, max_persist=max_persist, persist=persist).run()


async def run_opportunity_portfolio_discovery(*, ai_call_allowance: int = 2, max_persist: int = MAX_PERSIST_PER_RUN, persist: bool = True) -> dict[str, Any]:
    return await OpportunityPortfolioDiscovery(ai_call_allowance=ai_call_allowance, max_persist=max_persist, persist=persist).run()
