from __future__ import annotations
import json
from pathlib import Path


def read(p):
    try:return json.loads(Path(p).read_text(encoding='utf-8'))
    except:return {}

s=read('.radar_runtime/source_portfolio_v11.json')
d=read('.radar_runtime/transition_gap_discovery.json')
p=read('.radar_runtime/founder_current_portfolio.json')
print('='*122)
print('SIGNALFORGE V12 — SCALABLE OBSERVATION INTELLIGENCE AUDIT')
print('='*122)
h=s.get('health') or {};print(f"Source controller: {h.get('status')} | cache={h.get('cache')} | docs={h.get('total_docs',0)} | requests={h.get('requests_used',0)} | adaptive={h.get('adaptive_policy')}")
print(f"Source families: {h.get('family_counts',{})}")
print('Adapter health:')
for k,v in (h.get('adapters') or {}).items():print(f"  {k:18s} requests={v.get('requests',0):2d} docs={v.get('docs',0):4d} failures={v.get('failures',0):2d} 429={v.get('http_429',0):2d}")
print('-'*122)
o=d.get('observation_audit') or {};g=d.get('evidence_graph') or {};gt=g.get('telemetry') or {};f=d.get('formation') or {}
print(f"Observation layer: documents={o.get('documents',0)} observations={o.get('observations',0)} usable={o.get('usable_observations',0)}")
print(f"Usable by family: {o.get('usable_by_family',{})}")
print(f"Observation rejection reasons: {o.get('rejected_reasons',{})}")
print(f"Indexed Evidence Graph: nodes={g.get('nodes',0)} edges={g.get('edges',0)} clusters={g.get('clusters',0)} kinds={g.get('edge_kind_counts',{})}")
print(f"Graph scale: possible_pairs={gt.get('possible_pairs',0)} candidate_pairs={gt.get('candidate_pairs',0)} evaluated={gt.get('pairs_evaluated',0)} reduction={gt.get('pair_reduction_ratio')} total_seconds={gt.get('total_seconds')}")
print(f"Graph guards: pair_cap={gt.get('pair_cap')} edge_cap={gt.get('edge_cap')} truncated_buckets={gt.get('truncated_buckets',{})} max_bucket_sizes={gt.get('max_bucket_sizes',{})}")
print('-'*122)
print(f"Raw lane units: {f.get('raw_lane_units',{})}")
print(f"Formed lane units: {f.get('formed_lane_units',{})}")
print('Lane gaps:')
for lane,v in (f.get('lane_gaps') or {}).items():print(f"  {lane:26s} raw={v.get('raw_observation_units',0):4d} formed={v.get('formed_units',0):3d} status={v.get('status')}")
print(f"Lane rejections: {f.get('rejections',{})}")
sc=d.get('screening') or {};print(f"Screening: pool={d.get('screen_pool',0)} screened={sc.get('screened',0)} accepts={sc.get('model_accepts',0)} rejects={sc.get('hard_rejects',0)} malformed={sc.get('malformed',0)} unscreened={sc.get('unscreened',0)}")
print(f"Persisted: accepted={d.get('accepted',0)} inserted={d.get('inserted',0)} updated={d.get('updated',0)} evidence_rows={d.get('evidence_rows',0)} legacy_quarantined={d.get('legacy_generated_quarantined',0)}")
print(f"Phase seconds: {d.get('phase_seconds',{})}")
print('-'*122)
print(f"CURRENT Founder portfolio: current={p.get('current_count',0)} by_lane={p.get('current_by_lane',{})} | legacy archive={p.get('legacy_archive_count',0)} | predictive={p.get('predictive_credibility','UNVALIDATED')}")
print('Coverage boundaries:')
print('  physical-product marketplace reviews: NOT_CONNECTED')
print('  dedicated B2B review marketplaces: NOT_CONNECTED')
print('  live external market outcomes / predictive accuracy: UNVALIDATED')
print('='*122)
