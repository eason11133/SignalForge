from pathlib import Path
import json

def main():
    mp=Path('.radar_runtime/recovery_query_memory_u10.json');gp=Path('.radar_runtime/opportunity_evidence_graph_r1.json')
    try:m=json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else {}
    except Exception:m={}
    try:g=json.loads(gp.read_text(encoding='utf-8')) if gp.exists() else {}
    except Exception:g={}
    print('='*120)
    print('SIGNALFORGE U12 RUNTIME + ASSIMILATION AUDIT')
    print('acquisition_policy:',m.get('policy'))
    print('source_utility:',m.get('sources') or {})
    print('graph_cache:',{'nodes':g.get('nodes'),'edge_count':g.get('edge_count'),'observation_signature':g.get('observation_signature')})
    print('truth_boundary: runtime graph caching and source utility affect cost/acquisition priority only; they never promote demand, WTP, or opportunity truth.')
    print('='*120)
if __name__=='__main__':main()
