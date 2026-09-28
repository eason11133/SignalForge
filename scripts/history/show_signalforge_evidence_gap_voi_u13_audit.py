from __future__ import annotations
import json
from pathlib import Path

def main():
    p=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
    x=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    f=x.get('evidence_recovery_funnel') or {};ledger=f.get('evidence_gap_ledger') or {};rows=ledger.get('rows') or []
    print('='*122)
    print('SIGNALFORGE U13 EVIDENCE-GAP / VOI AUDIT')
    print('gap_rows:',len(rows))
    for r in rows[:12]:
        print({'anchor_key':r.get('anchor_key'),'gap':r.get('evidence_gap'),'attempts':r.get('attempts'),'new_docs':r.get('new_docs'),'evidence_docs':r.get('downstream_evidence_docs'),'voi':(r.get('voi') or {}).get('expected_information_value'),'zero_utility_streak':r.get('zero_utility_streak')})
    print('truth_boundary: gap telemetry and VOI guide search priority only; retrieved candidates do not establish demand, WTP, gap closure, or opportunity truth.')
    print('='*122)
if __name__=='__main__':main()
