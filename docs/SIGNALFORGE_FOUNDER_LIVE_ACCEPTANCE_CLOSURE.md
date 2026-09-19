# SignalForge Founder Live Acceptance Closure

This closure responds only to the live Founder workflow defects observed with an RFQ Quote Comparator hypothesis. It does not add UI/UX scope or expand Part 6.

## Fixed

1. Founder hypothesis -> Published thesis binding is fail-closed and exposes four compatibility axes: problem semantic, workflow, actor/buyer, and economic-job. No compatible match means Published Money Trail, buyer, spend, and paid dissatisfaction remain UNKNOWN.
2. Complete bounded zero-trace probe distinguishes Founder-hypothesis PARK from targeted domain research. It never converts a fresh search stop into Published Market Truth KILL.
3. HN / Stack Overflow / GitHub Issues / GitHub Repositories use source-specific bounded query compilation. GitHub search stays below the documented 256-character query limit; HN stays below the Algolia 512-byte query limit. Live transport acceptance separately checks real HTTP requests and hard-fails only query-contract rejections (HTTP 400/422).
4. Founder Idea probe durably hands off to Part 4 through a SQLite Founder Hypothesis registry. Provenance remains FOUNDER_HYPOTHESIS, market authority NONE, independent market recurrence 0, and market track UNVALIDATED until separately validated.
5. Buyer / next action can inherit Published data only through an accepted compatible Published binding.

## Live acceptance separation

Engineering/adversarial acceptance is deterministic. `run_signalforge_live_source_adapter_acceptance.py` is a separate real-network check.

- HTTP 2xx: source request accepted.
- HTTP 400/422: query contract defect -> installation fails and rolls back.
- DNS/timeout/5xx/401/403/429: live acceptance remains PENDING or ACCESS_LIMITED; installation may complete but the receipt must not claim live source PASS.

The live source test validates request/adapter transport only. It does not validate market evidence, market absence, or market success.

## Truth boundary

- Fresh traces remain UNVALIDATED.
- Founder hypotheses have zero Market Truth authority and zero independent market recurrence.
- Published evidence is reused only after compatible binding.
- Part 6 Evidence Promotion remains the only path in this package that can ultimately delegate validated market outcomes into existing Market Ground Truth authority.
- General Market Calibration remains UNVALIDATED until eligible real preregistered outcomes exist.
