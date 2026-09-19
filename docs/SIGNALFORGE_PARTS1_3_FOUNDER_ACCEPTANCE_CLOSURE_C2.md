# SignalForge Parts 1–3 Founder Acceptance Closure C2 Integrated

This is a narrow closure update over the already-installed Founder Idea Loop / Founder Memory / Trust-Falsification line. It does **not** redesign Parts 1–3 and does not modify Part 4 or Part 5 logic.

## Part 1 closures

- PARTIAL source coverage can no longer masquerade as complete/normal coverage or support an absence/kill-like conclusion.
- `firsthand_pain` now requires explicit first-person wording rather than any lexical pain cue.
- Paid-signal matching no longer treats generic `customer` or a bare `$` code token as payment evidence.
- Lexical cue matching uses token/phrase boundaries, preventing `custom` from matching inside `customer`.
- Paid commercial solution mentions can surface as existing-solution candidates, not only GitHub repositories.
- Common Chinese local-service / scheduling / invoice / procurement ideas receive deterministic English bridge terms.
- Unmapped Chinese input is explicitly marked `LIMITED_FOR_ENGLISH_HEAVY_SOURCES`; SignalForge must not treat missing English-heavy results as market absence.
- Long compact queries preserve decision-critical counter-search terms instead of dropping them.

## Supporting Money Trail lexical closure

Part 1 delegates spend / paid-dissatisfaction parsing to Money Trail. The closure therefore also hardens the shared deterministic matcher:

- no bare currency-symbol payment inference;
- phrase-aware payment/dissatisfaction matching;
- amount evidence must include a numeric amount or explicit payment language.

This changes only derived Founder-facing lexical classification; Market Truth authority remains unchanged.

## Part 2 closures

- Founder Memory writes are serialized with a cross-process lock, not only a process-local `threading.RLock`.
- Each acknowledged write is verified while the process lock is still held.
- Discussion checkpoints use the same cross-process mutation lock.
- Discussion Delta no longer relabels a pre-checkpoint question as `new_next_question` when no new question exists.
- Append-only decision history is preserved, but active `do_not_discuss_again` guidance contains only the latest decision rather than contradictory superseded decisions.

## Part 3 closures

- Try-to-Kill preserves the exact counter-hypothesis query when executing the fast probe; the good-enough / no-budget / switching-failure lenses cannot be compacted away.
- Counterevidence classification has bounded direction/negation guards for opposite statements such as `not good enough`, `switching cost is low`, `no security review`, and `did not shut down`.
- Evidence Replay source independence now fails closed: only explicit `source_family_key` values count as independent families. Different URLs/titles alone do not fabricate independence.
- Unknown source-family links are surfaced explicitly.

## Truth boundary

This closure adds **zero** direct C01–C14 / RadarClaim / Market Truth write authority. Fresh probes and fresh falsification results remain unvalidated search traces/candidates. Founder Memory remains Founder authority only.

## Independent closure gate

`run_signalforge_parts1_3_founder_acceptance_closure.py` executes 19 adversarial Founder-level checks, including a real multi-process Founder Memory race test.


## Part 4/5 integration correction

C2 is rebased on the installed Part 4 Founder Acceptance + Part 5 Durability Closure baseline. Founder Memory keeps the existing shared `signalforge_process_lock` and `.radar_runtime/signalforge_founder_reasoning.lock` identity while adding the Part-2 semantic fixes. This avoids creating a second lock domain during/after the closure update.
