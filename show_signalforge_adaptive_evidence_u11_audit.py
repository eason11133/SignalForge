from pathlib import Path
import json

def main():
    p=Path('.radar_runtime/recovery_query_memory_u10.json')
    try:m=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    except Exception:m={}
    print('='*120)
    print('SIGNALFORGE U11 ADAPTIVE EVIDENCE AUDIT')
    print('policy:',m.get('policy'))
    print('tracked_queries:',len(m.get('queries') or {}))
    print('source_yield:',m.get('sources') or {})
    print('truth_boundary: source yield changes acquisition priority only; it never promotes demand, WTP, or opportunity truth.')
    print('='*120)
if __name__=='__main__':main()
