# SignalForge Usability Convergence Cut U4

U4 is a convergence cut, not a single-bug patch.

Adopted mature-method changes:
- entity-resolution pipeline: blocking/matching -> canonicalization -> one canonical hypothesis key;
- broad legacy signatures are target-guarded so structurally distinct concrete failures cannot collide back into one identity;
- bounded local evidence spans for feedback-role / Need-Frame semantics to avoid full-post regex cost and context leakage;
- cached observation rows migrate in-place to the new evidence schema without forcing a full raw parser invalidation;
- source recovery uses a fresh bounded per-run budget; cumulative request telemetry is not a lifetime quota;
- Market State, External Enabler, User-Innovation and Need evidence remain separate truth objects;
- Founder Discussion Cards combine only linked evidence/context and preserve unknowns.

Truth boundary: problem hypotheses can be evidence-backed; opportunity attractiveness, WTP, causal why-now linkage, founder captureability and market validation remain separate evidence/test questions.
