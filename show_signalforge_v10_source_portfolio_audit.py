from __future__ import annotations
import json
from pathlib import Path

SOURCE = Path('.radar_runtime/source_portfolio_v10.json')
DISC = Path('.radar_runtime/transition_gap_discovery.json')
FOUNDER = Path('.radar_runtime/founder_daily.json')

def load(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return {}

def main():
    s=load(SOURCE); d=load(DISC); f=load(FOUNDER)
    health=s.get('health') or {}
    formation=d.get('formation') or {}
    screening=d.get('screening') or {}
    print('='*118)
    print('SIGNALFORGE V10 — SOURCE PORTFOLIO + OPPORTUNITY DISCOVERY AUDIT')
    print('='*118)
    print(f"Source portfolio: {health.get('status','MISSING')} | cache={health.get('cache','?')} | docs={health.get('total_docs',0)} | requests={health.get('requests_used',0)}")
    print(f"External source counts: {health.get('source_counts',{})}")
    print(f"External family counts: {health.get('family_counts',{})}")
    print('Adapter health:')
    for name,v in (health.get('adapters') or {}).items():
        print(f"  {name:18s} requests={v.get('requests',0):2} docs={v.get('docs',0):4} failures={v.get('failures',0):2} seconds={v.get('seconds',0)}")
    print('-'*118)
    print(f"Discovery engine: {d.get('engine_version','MISSING')}")
    print(f"Documents seen: {d.get('documents_seen',0)} | screen_pool={d.get('screen_pool',0)} | accepted={d.get('accepted',0)}")
    print(f"Source counts (merged): {d.get('source_counts',{})}")
    print(f"Raw lane units: {formation.get('raw_lane_units',{})}")
    print(f"Corroborated lane units: {formation.get('corroborated_lane_units',{})}")
    print('Lane source gaps:')
    for lane,v in (formation.get('source_gap_by_lane') or {}).items():
        print(f"  {lane:25s} raw={v.get('pre_corroboration',0):3} corroborated={v.get('corroborated_role_locked',0):3} status={v.get('status')}")
    print('-'*118)
    print('Screening integrity:')
    print(f"  screened={screening.get('pairs_screened',0)} unscreened={screening.get('unscreened_due_to_budget',0)} malformed={screening.get('malformed_or_missing',0)}")
    print(f"  model_accepts={screening.get('model_accepts',0)} hard_rejects={screening.get('hard_rejects',0)} contract={screening.get('model_output_contract')}")
    print(f"  accepted_by_lane={screening.get('accepted_by_lane',{})}")
    print('-'*118)
    gate=f.get('solo_founder_gate') or {}
    print(f"Founder surface present: {bool(f)} | ready={gate.get('ready',0)} watch={gate.get('watch',0)} parked={gate.get('research_themes_parked',0)}")
    print('Coverage boundaries (truth, not completion claims):')
    print('  community / workflow pain: Reddit RSS + cross-domain Stack Exchange + existing corpus')
    print('  software product reviews: Apple public customer-review RSS')
    print('  software paid supply: Apple iTunes Search metadata when explicit paid price exists')
    print('  physical-product marketplace reviews: NOT_CONNECTED')
    print('  dedicated B2B review marketplaces: NOT_CONNECTED')
    print('  live market outcomes / predictive accuracy: UNVALIDATED until real external tests close')
    print('='*118)

if __name__=='__main__': main()
