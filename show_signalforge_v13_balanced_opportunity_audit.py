from __future__ import annotations
import json
from pathlib import Path
D=Path('.radar_runtime/transition_gap_discovery.json');C=Path('.radar_runtime/founder_current_portfolio.json');Q=Path('.radar_runtime/v13_current_claims.json');S=Path('.radar_runtime/opportunity_source_portfolio.json')
def load(p):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except Exception:return {}
r=load(D);f=r.get('formation') or {};g=r.get('evidence_graph') or {};oa=r.get('observation_audit') or {};c=load(C);q=load(Q);s=load(S)
print('='*122);print('SIGNALFORGE V13 — BALANCED OPPORTUNITY UNIT + CLAIM TRUTH AUDIT');print('='*122)
print(f"Observation: docs={r.get('documents_seen')} usable={oa.get('usable_observations')} by_family={oa.get('usable_by_family')}")
print(f"Graph: nodes={g.get('nodes')} edges={g.get('edges')} clusters={g.get('clusters')} kinds={g.get('edge_kind_counts')}")
print('-'*122)
print(f"Raw observation signals: {f.get('raw_lane_units',{})}")
print(f"Contract eligible:       {f.get('contract_eligible_by_lane',{})}")
print(f"Dedup opportunity units: {f.get('deduped_units_by_lane',{})}")
print(f"Selected for veto:       {f.get('selected_by_lane',{})}")
print(f"Duplicates collapsed:    {f.get('duplicates_collapsed_by_lane',{})}")
print(f"Selection policy:        {f.get('selection_policy',{})}")
print(f"Lane starvation prevented: {f.get('lane_starvation_prevented')}")
for lane,v in (f.get('lane_gaps') or {}).items():print(f"  {lane:26s} raw={v.get('raw_observation_units',0):4} eligible={v.get('contract_eligible_units',0):4} dedup={v.get('deduped_opportunity_units',0):4} selected={v.get('selected_for_veto',0):3} status={v.get('status')}")
print('-'*122)
print(f"Screening: {r.get('screening')} accepted={r.get('accepted')} accepted_by_lane={r.get('accepted_by_lane')}")
for i,x in enumerate(r.get('accepted_summaries') or [],1):print(f"  #{i:02d} [{x.get('lane')}] {x.get('problem')} | actor={x.get('actor')} workflow={x.get('workflow')} score={x.get('score')}")
print('-'*122)
print(f"Canonical current portfolio: current={c.get('current_count')} by_lane={c.get('current_by_lane')} legacy={c.get('legacy_archive_count')}")
print(f"Current claim bridge: candidates={q.get('current_candidates')} predictive={q.get('predictive_credibility')}")
print('Legacy Radar V4 remains compatibility history; V13 current-portfolio claim truth is canonical for newly discovered opportunities.')
print('Live market outcomes / predictive accuracy: UNVALIDATED')
print('='*122)
