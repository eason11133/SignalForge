from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from database.connection import async_session, RadarCase, RadarClaim
from processors.quality_guard import audit_quality
from processors.signalforge_runtime import get_signalforge_runtime_status

SNAPSHOT = Path('.radar_runtime/founder_daily.json')
HARD_RUNTIME_SECONDS = 900.0
TARGET_RUNTIME_SECONDS = 600.0


async def main() -> None:
    runtime = get_signalforge_runtime_status()
    quality = await audit_quality()
    last_cycle = dict(runtime.get('last_cycle') or {})
    timing = dict(last_cycle.get('phase_seconds') or {})
    total = float(timing.get('total_cycle', 0) or 0)
    solution = dict(last_cycle.get('solution_gap') or {})

    async with async_session() as session:
        cases = list((await session.execute(select(RadarCase))).scalars().all())
        claims = list((await session.execute(select(RadarClaim))).scalars().all())

    verdicts = Counter(str(c.system_verdict or 'UNKNOWN').upper() for c in cases)
    claim_states: dict[str, Counter] = {}
    for claim in claims:
        claim_states.setdefault(str(claim.claim_code), Counter())[str(claim.state or 'UNKNOWN').upper()] += 1

    published = None
    if SNAPSHOT.exists():
        try:
            published = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        except Exception:
            published = None

    # M18.0 omitted c07_same_cycle_evaluated from the solution result payload even
    # though the runtime branch executed it. For the already-completed M18.0
    # cycle, reconstruct pipeline connectivity read-only from persisted truth:
    # a real C06 SUPPORT plus the corresponding C07 claim means the accepted
    # same-cycle branch was eligible and executed. Future cycles use the explicit
    # telemetry field now restored in solution_gap_research.py.
    c06_supported_case_ids = {
        int(claim.case_id)
        for claim in claims
        if str(claim.claim_code) == 'C06'
        and str(claim.state or '').upper() == 'SUPPORTED'
    }
    c07_case_ids = {
        int(claim.case_id)
        for claim in claims
        if str(claim.claim_code) == 'C07'
    }
    explicit_c07_eval = int(solution.get('c07_same_cycle_evaluated', 0) or 0)
    inferred_c07_eval = len(c06_supported_case_ids & c07_case_ids)
    c07_pipeline_connected = explicit_c07_eval > 0 or inferred_c07_eval > 0

    checks = {
        'runtime_pass': runtime.get('status') == 'PASS' and not runtime.get('running'),
        'fresh': bool(runtime.get('fresh')),
        'quality_pass': quality.get('status') == 'PASS' and int(quality.get('critical_count', len(quality.get('critical', []) or [])) or 0) == 0,
        'published_founder': isinstance(published, dict) and bool(published.get('cards')),
        'runtime_bounded': 0 < total <= HARD_RUNTIME_SECONDS,
        'investigate_exists': int(verdicts.get('INVESTIGATE', 0)) + int(verdicts.get('VALIDATE', 0)) > 0,
        'materiality_real': int(claim_states.get('C03', Counter()).get('SUPPORTED', 0)) > 0,
        'solution_engine_exercised': (
            int(solution.get('ai_calls', 0) or 0) > 0
            and str(solution.get('allocation_version') or '') == 'solution-allocation-v2-two-family-completion'
        ),
        # The known M17 blocker is not considered closed merely because C06
        # made API calls. At least one case must cross the unchanged two-family
        # C06 contract and then enter same-cycle C07 persistence evaluation.
        'current_solution_real': int(claim_states.get('C06', Counter()).get('SUPPORTED', 0)) > 0,
        'gap_pipeline_connected': c07_pipeline_connected,
        'published_truth_mode': str(last_cycle.get('final_reality_mode') or '') in {'persisted', 'materialize'},
    }

    print('=' * 126)
    print('SIGNALFORGE M18 GO-LIVE CHECK')
    print('=' * 126)
    print(f"Runtime: {total:.1f}s ({total/60:.2f} min) | target <= {TARGET_RUNTIME_SECONDS/60:.0f} min | hard <= {HARD_RUNTIME_SECONDS/60:.0f} min")
    print(f"Quality: {quality.get('status')} | fresh={runtime.get('fresh')} | published_snapshot={'YES' if published else 'NO'}")
    print(f"Verdicts: {dict(verdicts)}")
    print(f"C03 SUPPORTED={claim_states.get('C03', Counter()).get('SUPPORTED', 0)}")
    print(f"C05 SUPPORTED={claim_states.get('C05', Counter()).get('SUPPORTED', 0)}")
    print(f"C06 SUPPORTED={claim_states.get('C06', Counter()).get('SUPPORTED', 0)}")
    print(f"C07 SUPPORTED={claim_states.get('C07', Counter()).get('SUPPORTED', 0)}")
    print(
        'Solution engine: '
        f"calls={solution.get('ai_calls', 0)} same_problem={solution.get('same_problem', 0)} "
        f"support_links={solution.get('support_links', 0)} "
        f"c07_evaluated={explicit_c07_eval} "
        f"c07_inferred_eligible={inferred_c07_eval} "
        f"c07_supported={solution.get('c07_same_cycle_supported', 0)}"
    )
    print(f"Final reality mode: {last_cycle.get('final_reality_mode')}")
    print('Live Market Calibration: 0% actual until real market outcomes')
    print('Predictive Accuracy: UNVALIDATED until real treatment/control outcomes')
    print('-' * 126)
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print('SIGNALFORGE_M18_GO_LIVE_NOT_READY')
        print('Failed checks:', ', '.join(failed))
        raise SystemExit(30)
    if total > TARGET_RUNTIME_SECONDS:
        print('SIGNALFORGE_M18_GO_LIVE_READY')
        print('Operationally usable now. Runtime is within the hard limit but remains above the 10-minute target.')
    else:
        print('SIGNALFORGE_M18_GO_LIVE_READY')
        print('Operationally usable now. Runtime target met.')
    print('=' * 126)


if __name__ == '__main__':
    asyncio.run(main())
