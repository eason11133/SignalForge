from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

BEHAVIOR_TRACKING_VERSION = "BEHAVIOR_TREND_CONTINUOUS_TRACKING_V1"
PATTERN_MIN_INDEPENDENT_ACTORS = 3
MAX_OBSERVATIONS = 2000
MAX_ACTORS = 800
MAX_PATTERNS = 240
MAX_TREND_SNAPSHOTS = 500

_EVIDENCE_KINDS = {
    "PROBLEM", "WORKAROUND", "BEHAVIOR", "PRODUCT_MENTION", "CATEGORY_LANGUAGE",
    "COMPETITOR", "TREND", "SWITCHING", "PURCHASE_SIGNAL", "CONTACT_PATH",
    "COUNTEREVIDENCE", "OTHER",
}

_SPACE_RE = re.compile(r"\s+")
_HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.-]{2,64})")
_EXPLICIT_FREQ_RE = re.compile(
    r"\b(every\s+(?:day|week|month)|daily|weekly|monthly|each\s+(?:day|week|month)|"
    r"\d+\s*(?:x|times?)\s+(?:a|per)\s+(?:day|week|month))\b", re.I
)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.I)

_WORKAROUND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("copy/paste", ("copy paste", "copy-paste", "paste the transcript", "paste transcript", "copy transcript", "clipboard")),
    ("download", ("download", "save locally", "save the file", "export then")),
    ("transcribe", ("transcrib", "whisper", "speech to text", "speech-to-text", "captions", "subtitle")),
    ("screenshot", ("screenshot", "screen shot", "screen-shot")),
    ("spreadsheet/manual", ("spreadsheet", "excel", "google sheets", "manual entry", "manually", "paper")),
    ("switch tool", ("use instead", "switch to", "moved to", "went back to", "because it can't", "because it cannot")),
)

_PROBLEM_CUES = (
    "can't", "cannot", "doesn't", "does not", "won't", "unable", "broken", "issue",
    "problem", "frustrat", "annoy", "pain", "hard to", "difficult", "limitation", "missing",
)
_SWITCH_CUES = ("switch to", "moved to", "use instead", "went back to", "replaced with", "because it can't", "because it cannot")
_PURCHASE_CUES = ("paid", "paying", "subscription", "pricing", "bought", "purchase", "budget", "upgrade", "pro plan", "premium")
_CATEGORY_CUES = ("need a way to", "looking for a way", "tool for", "something that", "how do i", "how can i", "is there a way")
_TREND_CUES = ("trend", "growing", "growth", "rising", "surging", "search interest", "google trends")
_COMPETITOR_CUES = ("alternative", "competitor", "versus", " vs ", "replacement", "switch from")

_TOOL_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9][A-Za-z0-9+._-]{1,32}(?:\s+[A-Z][A-Za-z0-9+._-]{1,32}){0,2})\b"
)
_GENERIC_CAPS = {
    "The", "This", "That", "These", "Those", "How", "What", "Why", "When", "Where",
    "I", "We", "You", "My", "Our", "A", "An", "And", "But", "For", "From", "With",
}


def _clean(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _text(row: Mapping[str, Any]) -> str:
    return " ".join(
        _clean(row.get(key))
        for key in ("title", "excerpt", "snippet", "description", "text", "solution_type", "tracking_family")
        if _clean(row.get(key))
    )


def _material_key(row: Mapping[str, Any]) -> str:
    url = _clean(row.get("url"))
    if url:
        try:
            parsed = urlsplit(url)
            query = f"?{parsed.query}" if parsed.query else ""
            base = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}{query}"
            if base:
                return "url:" + base
        except Exception:
            pass
    basis = "|".join((_clean(row.get("source")), _clean(row.get("title")), _clean(row.get("excerpt"))[:260]))
    return "txt:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def classify_evidence(row: Mapping[str, Any]) -> str:
    text = _text(row).lower()
    family = _clean(row.get("tracking_family")).lower()
    solution_type = _clean(row.get("solution_type")).upper()
    if any(cue in text for cue in _TREND_CUES):
        return "TREND"
    if any(cue in text for cue in _SWITCH_CUES):
        return "SWITCHING"
    if any(cue in text for cue in _PURCHASE_CUES):
        return "PURCHASE_SIGNAL"
    if any(cue in text for cue in _CATEGORY_CUES):
        return "CATEGORY_LANGUAGE"
    if "counter" in family or any(cue in text for cue in ("not a problem", "works fine", "good enough", "no longer need")):
        return "COUNTEREVIDENCE"
    if any(label in family for label in ("manual_workaround", "workaround")) or any(
        cue in text for _, cues in _WORKAROUND_RULES for cue in cues
    ):
        return "WORKAROUND"
    if solution_type in {"PRODUCT", "SOFTWARE", "SAAS", "SERVICE", "TOOL", "PLATFORM", "VENDOR", "COMMERCIAL"}:
        return "PRODUCT_MENTION"
    if any(cue in text for cue in _COMPETITOR_CUES):
        return "COMPETITOR"
    if any(cue in text for cue in _PROBLEM_CUES):
        return "PROBLEM"
    if any(label in family for label in ("discussion", "practitioner", "forum", "social", "workflow")):
        return "BEHAVIOR"
    return "OTHER"


def _source_platform(row: Mapping[str, Any]) -> str:
    source = _clean(row.get("source"))
    url = _clean(row.get("url")).lower()
    hay = f"{source} {url}".lower()
    for key, label in (
        ("reddit", "reddit"), ("youtube", "youtube"), ("youtu.be", "youtube"),
        ("github", "github"), ("x.com", "x"), ("twitter", "x"),
        ("instagram", "instagram"), ("tiktok", "tiktok"),
        ("news.ycombinator", "hackernews"), ("linkedin", "linkedin"),
        ("stack", "stackexchange"),
    ):
        if key in hay:
            return label
    return source.lower()[:40] or "web"


def extract_actor(row: Mapping[str, Any]) -> dict[str, Any] | None:
    author = _clean(row.get("author"))
    url = _clean(row.get("url"))
    profile_url = _clean(row.get("profile_url"))
    handle = ""
    if author:
        match = _HANDLE_RE.search(author)
        handle = match.group(1) if match else author.lstrip("@").strip()
    if not handle:
        match = _HANDLE_RE.search(_text(row))
        handle = match.group(1) if match else ""
    platform = _source_platform(row)
    if not handle and not profile_url:
        return None
    actor_key_basis = f"{platform}|{handle.lower()}" if handle else f"{platform}|{profile_url.lower()}"
    actor_key = hashlib.sha256(actor_key_basis.encode("utf-8")).hexdigest()[:24]
    public_contacts: list[str] = []
    if profile_url.startswith(("http://", "https://")):
        public_contacts.append(profile_url)
    return {
        "actor_key": actor_key,
        "display_name": author or handle or None,
        "handle": handle or None,
        "platform": platform,
        "profile_url": profile_url or None,
        "public_contact_paths": public_contacts,
        "identity_confidence": "HIGH" if handle else "MEDIUM",
    }


def _workflow_steps(text: str) -> list[str]:
    low = text.lower()
    steps: list[str] = []
    for label, cues in _WORKAROUND_RULES:
        if any(cue in low for cue in cues) and label not in steps:
            steps.append(label)
    return steps[:8]


def _explicit_frequency(text: str) -> tuple[str | None, bool]:
    match = _EXPLICIT_FREQ_RE.search(text)
    return (match.group(0) if match else None, bool(match))


def _tool_mentions(text: str) -> list[str]:
    values: list[str] = []
    for match in _TOOL_PATTERN.finditer(text):
        value = _clean(match.group(1))
        if not value or value in _GENERIC_CAPS:
            continue
        if len(value) < 3 or len(value) > 60:
            continue
        if value.lower() not in {x.lower() for x in values}:
            values.append(value)
        if len(values) >= 8:
            break
    return values


def extract_behavior(row: Mapping[str, Any]) -> dict[str, Any]:
    text = _text(row)
    freq, explicit = _explicit_frequency(text)
    steps = _workflow_steps(text)
    kind = classify_evidence(row)
    friction = None
    if kind == "PROBLEM" or any(cue in text.lower() for cue in _PROBLEM_CUES):
        friction = _clean(row.get("excerpt"))[:280] or _clean(row.get("title"))[:280] or None
    workaround = " → ".join(steps) if steps else None
    return {
        "action": None,
        "object": None,
        "tool_or_product": (_tool_mentions(text) or [None])[0],
        "downstream_job": None,
        "frequency_text": freq,
        "explicit_frequency": explicit,
        "workflow_steps": steps,
        "workaround": workaround,
        "friction": friction,
    }


def enrich_material(row: Mapping[str, Any], *, observed_at: str) -> dict[str, Any]:
    enriched = dict(row)
    kind = classify_evidence(row)
    actor = extract_actor(row)
    behavior = extract_behavior(row)
    text = _text(row)
    mentions = _tool_mentions(text)
    enriched["evidence_kind"] = kind
    if actor:
        enriched["actor"] = actor
    if any(behavior.values()):
        enriched["behavior"] = behavior
    enriched["mention"] = {
        "canonical_term": mentions[0] if mentions else None,
        "raw_term": mentions[0] if mentions else None,
        "mention_type": "PRODUCT" if kind in {"PRODUCT_MENTION", "COMPETITOR"} else ("CATEGORY" if kind == "CATEGORY_LANGUAGE" else "WORKFLOW"),
        "brand_name": mentions[0] if mentions and kind in {"PRODUCT_MENTION", "COMPETITOR", "SWITCHING"} else None,
        "category_name": None,
    }
    source_published_at = (
        _clean(row.get("source_published_at"))
        or _clean(row.get("published_at"))
        or _clean(row.get("created_at"))
        or _clean(row.get("date"))
        or None
    )
    enriched["observation"] = {
        "observed_at": observed_at,
        "source_published_at": source_published_at,
        "first_seen_at": _clean(row.get("first_seen_at")) or observed_at,
        "last_seen_at": observed_at,
        "seen_count": max(1, int(row.get("seen_count") or 1)),
    }
    return enriched


def _pattern_candidates(observation: Mapping[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    kind = _clean(observation.get("evidence_kind")).upper()
    behavior = observation.get("behavior") if isinstance(observation.get("behavior"), Mapping) else {}
    mention = observation.get("mention") if isinstance(observation.get("mention"), Mapping) else {}
    workaround = _clean(behavior.get("workaround"))
    if workaround:
        result.append(("WORKAROUND", workaround))
    for step in behavior.get("workflow_steps") or []:
        step = _clean(step)
        if step:
            result.append(("BEHAVIOR", step))
    term = _clean(mention.get("canonical_term"))
    if term:
        result.append(("PRODUCT_MENTION" if kind in {"PRODUCT_MENTION", "COMPETITOR", "SWITCHING"} else "CATEGORY_LANGUAGE", term))
    return result


def _window_counts(observations: Sequence[Mapping[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    for obs in observations:
        dt = _parse_time(obs.get("source_published_at")) or _parse_time(obs.get("observed_at"))
        if dt is not None and start <= dt < end:
            rows.append(obs)
    actors = {_clean((obs.get("actor") or {}).get("actor_key")) for obs in rows if isinstance(obs.get("actor"), Mapping) and _clean((obs.get("actor") or {}).get("actor_key"))}
    repeat_counts = Counter(
        _clean((obs.get("actor") or {}).get("actor_key"))
        for obs in rows if isinstance(obs.get("actor"), Mapping) and _clean((obs.get("actor") or {}).get("actor_key"))
    )
    kinds = Counter(_clean(obs.get("evidence_kind")).upper() for obs in rows)
    return {
        "material_count": len(rows),
        "unique_actors": len(actors),
        "repeat_actor_count": sum(1 for count in repeat_counts.values() if count >= 2),
        "workaround_mentions": kinds["WORKAROUND"],
        "product_mentions": kinds["PRODUCT_MENTION"],
        "category_mentions": kinds["CATEGORY_LANGUAGE"],
        "competitor_mentions": kinds["COMPETITOR"],
        "switching_mentions": kinds["SWITCHING"],
        "contactable_actors": sum(
            1 for key in actors
            if any(
                isinstance(obs.get("actor"), Mapping)
                and _clean((obs.get("actor") or {}).get("actor_key")) == key
                and bool((obs.get("actor") or {}).get("public_contact_paths"))
                for obs in rows
            )
        ),
    }


def _delta(current: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, int]:
    keys = (
        "material_count", "unique_actors", "repeat_actor_count", "workaround_mentions",
        "product_mentions", "category_mentions", "competitor_mentions", "switching_mentions",
        "contactable_actors",
    )
    return {key: int(current.get(key) or 0) - int(previous.get(key) or 0) for key in keys}


def record_behavior_cycle(item: dict[str, Any], qualified_rows: Sequence[Mapping[str, Any]], seen_at: str) -> dict[str, Any]:
    item["behavior_tracking_version"] = BEHAVIOR_TRACKING_VERSION
    observations = item.setdefault("behavior_observations", [])
    actor_index = item.setdefault("actor_index", {})
    cycle_seen: set[str] = set()
    new_observations = 0

    for raw in qualified_rows:
        enriched = enrich_material(raw, observed_at=seen_at)
        material_key = _material_key(enriched)
        cycle_key = f"{material_key}|{seen_at}"
        if cycle_key in cycle_seen:
            continue
        cycle_seen.add(cycle_key)
        actor = enriched.get("actor") if isinstance(enriched.get("actor"), Mapping) else None
        observation_id = hashlib.sha256(cycle_key.encode("utf-8")).hexdigest()[:24]
        obs = {
            "observation_id": observation_id,
            "material_key": material_key,
            "material_url": _clean(enriched.get("url")) or None,
            "title": _clean(enriched.get("title"))[:280] or None,
            "evidence_kind": enriched.get("evidence_kind"),
            "actor": dict(actor) if actor else None,
            "behavior": dict(enriched.get("behavior") or {}),
            "mention": dict(enriched.get("mention") or {}),
            "observed_at": seen_at,
            "source_published_at": (enriched.get("observation") or {}).get("source_published_at"),
            "exact_evidence": _clean(enriched.get("excerpt"))[:700] or _clean(enriched.get("title"))[:280],
        }
        observations.append(obs)
        new_observations += 1

        if actor:
            key = _clean(actor.get("actor_key"))
            if key:
                entry = actor_index.setdefault(key, {
                    "actor_key": key,
                    "platform": actor.get("platform"),
                    "handle": actor.get("handle"),
                    "display_name": actor.get("display_name"),
                    "profile_url": actor.get("profile_url"),
                    "first_seen_at": seen_at,
                    "last_seen_at": seen_at,
                    "observation_count": 0,
                    "source_urls": [],
                    "workflows": [],
                    "workarounds": [],
                    "product_mentions": [],
                    "public_contact_paths": [],
                })
                entry["last_seen_at"] = seen_at
                entry["observation_count"] = int(entry.get("observation_count") or 0) + 1
                url = _clean(enriched.get("url"))
                if url and url not in entry["source_urls"]:
                    entry["source_urls"].append(url)
                behavior = enriched.get("behavior") or {}
                workaround = _clean(behavior.get("workaround"))
                if workaround and workaround not in entry["workarounds"]:
                    entry["workarounds"].append(workaround)
                for step in behavior.get("workflow_steps") or []:
                    step = _clean(step)
                    if step and step not in entry["workflows"]:
                        entry["workflows"].append(step)
                term = _clean((enriched.get("mention") or {}).get("canonical_term"))
                if term and term not in entry["product_mentions"]:
                    entry["product_mentions"].append(term)
                for contact in actor.get("public_contact_paths") or []:
                    contact = _clean(contact)
                    if contact and contact not in entry["public_contact_paths"]:
                        entry["public_contact_paths"].append(contact)
                for field in ("source_urls", "workflows", "workarounds", "product_mentions", "public_contact_paths"):
                    entry[field] = list(entry[field])[-60:]

    if len(observations) > MAX_OBSERVATIONS:
        del observations[: len(observations) - MAX_OBSERVATIONS]
    if len(actor_index) > MAX_ACTORS:
        oldest = sorted(actor_index.values(), key=lambda x: _clean(x.get("last_seen_at")))[: len(actor_index) - MAX_ACTORS]
        for row in oldest:
            actor_index.pop(_clean(row.get("actor_key")), None)

    pattern_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for obs in observations:
        for kind, label in _pattern_candidates(obs):
            pattern_groups[(kind, label.lower())].append(obs)
    patterns: list[dict[str, Any]] = []
    for (kind, _), rows in pattern_groups.items():
        actor_keys = {
            _clean((row.get("actor") or {}).get("actor_key"))
            for row in rows if isinstance(row.get("actor"), Mapping) and _clean((row.get("actor") or {}).get("actor_key"))
        }
        if len(actor_keys) < PATTERN_MIN_INDEPENDENT_ACTORS:
            continue
        label = next((label for obs in rows for k, label in _pattern_candidates(obs) if k == kind), kind)
        times = [_parse_time(row.get("source_published_at")) or _parse_time(row.get("observed_at")) for row in rows]
        times = [t for t in times if t is not None]
        material_ids = list(dict.fromkeys(_clean(row.get("material_key")) for row in rows if _clean(row.get("material_key"))))
        examples = [row.get("exact_evidence") for row in rows if _clean(row.get("exact_evidence"))][:3]
        pattern_id = hashlib.sha256(f"{kind}|{label.lower()}".encode("utf-8")).hexdigest()[:20]
        patterns.append({
            "pattern_id": pattern_id,
            "canonical_label": label,
            "evidence_kind": kind,
            "independent_actor_count": len(actor_keys),
            "material_count": len(material_ids),
            "first_seen": min(times).isoformat() if times else None,
            "last_seen": max(times).isoformat() if times else None,
            "supporting_material_ids": material_ids[-40:],
            "example_evidence": examples,
        })
    patterns.sort(key=lambda x: (-int(x["independent_actor_count"]), -int(x["material_count"]), _clean(x["canonical_label"]).lower()))
    item["repeated_patterns"] = patterns[:MAX_PATTERNS]

    now = _parse_time(seen_at) or datetime.now(timezone.utc)
    windows: dict[str, Any] = {}
    for days in (7, 30):
        current = _window_counts(observations, now - timedelta(days=days), now + timedelta(seconds=1))
        previous = _window_counts(observations, now - timedelta(days=days * 2), now - timedelta(days=days))
        windows[f"{days}d"] = {
            "window": f"{days}d",
            "compared_with": f"previous_{days}d",
            "current": current,
            "previous": previous,
            "delta": _delta(current, previous),
        }
    item["behavior_windows"] = windows
    item["behavior_last_cycle"] = {
        "at": seen_at,
        "new_observations": new_observations,
        "known_actor_count": len(actor_index),
        "surfaced_pattern_count": len(patterns),
        "market_truth_writes": 0,
    }
    return item["behavior_last_cycle"]


def migrate_behavior_state(item: dict[str, Any]) -> bool:
    changed = False
    defaults = {
        "behavior_tracking_version": BEHAVIOR_TRACKING_VERSION,
        "behavior_observations": [],
        "actor_index": {},
        "repeated_patterns": [],
        "behavior_windows": {},
        "behavior_last_cycle": {},
        "trend_snapshots": [],
        "trend_provider_status": {"provider": "NONE", "status": "NOT_CONFIGURED"},
    }
    for key, value in defaults.items():
        if key not in item:
            item[key] = value
            changed = True
    if item.get("behavior_tracking_version") != BEHAVIOR_TRACKING_VERSION:
        item["behavior_tracking_version"] = BEHAVIOR_TRACKING_VERSION
        changed = True
    return changed


class TrendProvider:
    provider_name = "NONE"

    def fetch_interest(self, terms: Sequence[str], geo: str, start: str, end: str, interval: str) -> list[dict[str, Any]]:
        return []


class ManualTrendsProvider(TrendProvider):
    provider_name = "MANUAL_TRENDS_IMPORT"

    @staticmethod
    def normalize(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            term = _clean(row.get("term"))
            if not term:
                continue
            normalized.append({
                "provider": "MANUAL_TRENDS_IMPORT",
                "term": term,
                "geo": _clean(row.get("geo")) or None,
                "period_start": _clean(row.get("period_start")) or None,
                "period_end": _clean(row.get("period_end")) or None,
                "interval": _clean(row.get("interval")) or None,
                "value": row.get("value"),
                "scale_type": _clean(row.get("scale_type")) or "PROVIDER_NATIVE",
                "fetched_at": _clean(row.get("fetched_at")) or datetime.now(timezone.utc).isoformat(),
                "raw_metadata": dict(row.get("raw_metadata") or {}) if isinstance(row.get("raw_metadata"), Mapping) else {},
            })
        return normalized[:MAX_TREND_SNAPSHOTS]


class TranscriptProvider:
    provider_name = "NONE"

    def fetch_transcript(self, url: str) -> dict[str, Any]:
        return {"status": "UNAVAILABLE", "provider": self.provider_name, "url": url, "text": None}
