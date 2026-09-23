from processors.signalforge_behavior_tracking import (
    BEHAVIOR_TRACKING_VERSION,
    classify_evidence,
    enrich_material,
    migrate_behavior_state,
    record_behavior_cycle,
)


def trust_row(author, title, excerpt, url, family="behavior_routines", solution_type=""):
    return {
        "author": author,
        "title": title,
        "excerpt": excerpt,
        "url": url,
        "source": "youtube",
        "tracking_family": family,
        "solution_type": solution_type,
        "evidence_trust": {"verdict": "RELATED"},
    }


def require(cond, name):
    print(f"{name}={'PASS' if cond else 'FAIL'}")
    if not cond:
        raise AssertionError(name)


item = {}
require(migrate_behavior_state(item), "migration_additive")
require(item["behavior_tracking_version"] == BEHAVIOR_TRACKING_VERSION, "migration_version")

# Behavior without complaint language remains behavior evidence.
plain = trust_row("@alex", "My AI research workflow", "Every week I download lectures, run Whisper, then paste the transcript into my assistant.", "https://youtube.com/watch?v=a")
require(classify_evidence(plain) == "WORKAROUND", "behavior_without_complaint_is_kept")
enriched = enrich_material(plain, observed_at="2026-09-20T00:00:00+00:00")
require(enriched["behavior"]["explicit_frequency"] is True, "explicit_frequency_only_when_stated")

# Same actor across cycles must stay one actor and accumulate observations.
record_behavior_cycle(item, [plain], "2026-09-20T00:00:00+00:00")
second = trust_row("@alex", "Research setup update", "I still download files and transcribe them before using my assistant.", "https://youtube.com/watch?v=b")
record_behavior_cycle(item, [second], "2026-09-21T00:00:00+00:00")
require(len(item["actor_index"]) == 1, "same_actor_not_duplicated")
actor = next(iter(item["actor_index"].values()))
require(actor["observation_count"] == 2, "actor_observation_count_increments")

# Three independent actors surface a repeated workaround pattern.
for i, handle in enumerate(("@bea", "@cara"), start=2):
    row = trust_row(handle, "My workflow", "Every week I download the video and transcribe it before analysis.", f"https://youtube.com/watch?v={i}")
    record_behavior_cycle(item, [row], f"2026-09-{20+i:02d}T00:00:00+00:00")
require(any(p["independent_actor_count"] >= 3 for p in item["repeated_patterns"]), "pattern_requires_independent_actors")

# Generic unrelated consumer behavior: not Link2AI hard-coded.
pilates = {}
migrate_behavior_state(pilates)
rows = [
    trust_row("@p1", "Pilates morning routine", "Every class I use grip socks in my setup.", "https://youtube.com/watch?v=p1"),
    trust_row("@p2", "What I use for Pilates", "My weekly Pilates routine always includes grip socks.", "https://youtube.com/watch?v=p2"),
    trust_row("@p3", "Pilates setup", "I use grip socks every week for reformer class.", "https://youtube.com/watch?v=p3"),
]
record_behavior_cycle(pilates, rows, "2026-09-23T00:00:00+00:00")
require(len(pilates["actor_index"]) == 3, "generic_unrelated_direction_actor_tracking")
require("7d" in pilates["behavior_windows"] and "30d" in pilates["behavior_windows"], "rolling_windows_present")
require(pilates.get("market_truth_writes", 0) == 0, "market_truth_zero")

print("SIGNALFORGE_BEHAVIOR_TRACKING_V1_REGRESSION_PASS")

# Persistence survives store reload/restart boundary.
import tempfile
from processors.signalforge_research_backlog import add_ideas, load_store, save_store
with tempfile.TemporaryDirectory() as td:
    created = add_ideas(td, [{"title": "Behavior persistence test", "description": "Track repeated public workflow behavior"}])
    persisted_id = created["added_ids"][0]
    store = load_store(td, repair_worker=False)
    persisted_item = store["items"][persisted_id]
    p_rows = [
        trust_row("@r1", "Workflow", "Every week I download then transcribe the source.", "https://youtube.com/watch?v=r1"),
        trust_row("@r2", "Workflow", "Every week I download then transcribe the source.", "https://youtube.com/watch?v=r2"),
        trust_row("@r3", "Workflow", "Every week I download then transcribe the source.", "https://youtube.com/watch?v=r3"),
    ]
    record_behavior_cycle(persisted_item, p_rows, "2026-09-23T02:00:00+00:00")
    save_store(td, store)
    reloaded = load_store(td, repair_worker=False)["items"][persisted_id]
    require(len(reloaded["actor_index"]) == 3, "actor_state_persists_across_restart")
    require(bool(reloaded["repeated_patterns"]), "pattern_state_persists_across_restart")
