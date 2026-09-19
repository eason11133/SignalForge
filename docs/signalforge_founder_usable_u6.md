# SignalForge Founder-Usable U6 — Runtime Truth Convergence

U6 preserves U5 evidence-quality contracts and replaces monolithic cache/state serialization with memory-bounded runtime persistence.

- Observation cache stores derived fields only; raw source text/raw_doc are hydrated from the current source corpus.
- Cache writes are dirty-only and atomic streaming; clean all-hit runs do not rewrite the cache.
- Source snapshots and discovery state use atomic streaming JSON instead of building giant `json.dumps` strings.
- Cache persistence is an optimization boundary: a persistence failure preserves the previous cache/state and does not manufacture market truth.
- Recovery remains incremental and bounded; U5 dependence/source-role/Founder-readiness rules remain intact.
