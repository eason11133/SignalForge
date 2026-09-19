# Radar V4.2d — Multi-source Problem Recurrence

## Decision from the V4.2 audits

The audits established:

- lowering similarity thresholds is not justified;
- using original first-hand exemplars improves retrieval somewhat but does not
  solve the current recurrence coverage problem;
- the existing local database has only two source families appropriate for
  direct problem recurrence:
  - HN/Reddit posts/discussions
  - Stack Overflow questions
- Jobs, News, GitHub repositories, package activity and YC companies are NOT
  direct recurrence evidence.

Therefore V4.2d expands direct-problem coverage without weakening gates.

## Sources

### Hacker News / Reddit
Grouped by root discussion.

One root discussion = one independence family.

### Stack Overflow
Each question = one independence family.

A question enters the direct-problem corpus only when:
- it contains an explicit problem/error/failure signal; and
- it has technical/product context.

The processor uses title + tags + any text present in raw_metadata.

## Query representation

For each Radar Case:

1. ABSTRACT
   - title
   - problem statement
   - actor
   - task
   - object
   - failure mode
   - consequence

2. EXEMPLAR
   - original first-hand community evidence text

For every retrieved document the system uses whichever representation has the
higher hybrid local similarity.

This addresses representation loss without turning AI into the default parser.

## Acceptance thresholds

UNCHANGED from V4.2.

A STRONG recurrence match still requires:
- high combined similarity;
- high word similarity;
- high character similarity;
- >=3 shared specific terms;
- shared failure-mode category;
- independent source family.

AMBIGUOUS remains non-evidence.

## AI

No AI is called by this processor.

Only AMBIGUOUS pairs can become eligible for `same_problem_verify`, after the
local method has run and the AI Budget Gate allows it.

## Evidence-role separation

Explicitly excluded from C02:
- Jobs
- News
- GitHub repositories
- package activity
- YC companies

Those sources remain useful later for Buyer, Solution, Timing and Race gates.
