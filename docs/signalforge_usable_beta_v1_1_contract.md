# SignalForge Usable Beta v1.1 — Founder Handoff Truth Closure

## Purpose

v1 engineering/build passed, but product-acceptance source review found one truth-boundary weakness in the Founder surface: unvalidated `CandidateEvidence` and unvalidated C06/C07 rows could be displayed inside solution/evidence/handoff surfaces without their unvalidated status surviving the transformation.

That conflicts with the canonical boundaries:

- retrieved candidate != confirmed evidence;
- evidence count != confidence;
- UNKNOWN / INSUFFICIENT != weak support;
- SHADOW research must not leak into published thesis/handoff.

## v1.1 closure

1. `/signalforge/opportunity/{candidate_id}` now exposes `published_evidence` containing only `RadarClaimEvidence.validated == true` rows from the current RadarCase.
2. Founder Discussion Handoff uses only `published_evidence`.
3. CandidateEvidence metadata is no longer promoted into named current-solution / competition truth surfaces.
4. C07 confirmed persistence reasons use validated `SUPPORT` evidence only.
5. Unvalidated C07 rows may still be counted as pending context, but are explicitly described as pending and cannot enter the handoff as confirmed evidence.
6. Research More remains SHADOW and retains zero direct authority over C01-C14, WTP, opportunity verdict, or build recommendation.
7. A live acceptance runner now executes one bounded Research More request and compares published truth before/after.

## Acceptance levels

- Engineering Gate: installer/source/build passes.
- Automated Product Acceptance: live API + one real Research More request + no published mutation + handoff source boundary passes.
- Founder visual acceptance: human can visually confirm the page is understandable; this is UX acceptance, not market truth.
- Live Market Calibration: remains `0 / UNVALIDATED` until real market outcomes exist.
