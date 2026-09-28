from __future__ import annotations
from pathlib import Path
import json, py_compile, sys
ROOT=Path(__file__).resolve().parent
checks={}
route=(ROOT/'api/routes/signalforge.py').read_text(encoding='utf-8')
client=(ROOT/'dashboard/src/api/client.ts').read_text(encoding='utf-8')
detail=(ROOT/'dashboard/src/pages/CandidateDetail.tsx').read_text(encoding='utf-8')
checks['published_evidence_api']='"published_evidence": published_evidence' in route and 'if not bool(link.validated)' in route
checks['published_evidence_type']='published_evidence:SignalForgeOpportunityEvidence[]' in client
checks['handoff_validated_only']='forgeDetail?.published_evidence' in detail and '.filter((item: any) => item.validated)' in detail
checks['candidate_evidence_not_in_handoff']='...evidence.map((item: any)' not in detail and 'evidenceSolutions' not in detail and 'evidenceCompetition' not in detail
checks['confirmed_gap_support_only']='confirmedGapSupport' in detail and 'String(item.stance || "").toUpperCase() === "SUPPORT"' in detail
checks['truth_boundary_copy']='unvalidated candidate evidence 不會混進 handoff' in detail and 'validated ledger evidence' in detail
checks['research_state_api']='/research-state' in route and 'published_truth_changed' in route
checks['research_more_api']='/research-more' in route and 'FounderDirectedExecutor' in route
checks['research_more_nonblocking']='await asyncio.to_thread(executor.execute' in route and '_research_more_lock = asyncio.Lock()' in route
checks['truth_snapshot_ui']='TRUTH SNAPSHOT' in detail and 'CONTRADICTED' in detail and 'UNKNOWN ·' in detail
checks['shadow_boundary_ui']='Retrieved candidate' in detail and 'Published truth' in detail
checks['discussion_handoff']='與 ChatGPT 討論' in detail and 'buildDiscussionPrompt' in detail
checks['no_product_ideation']='不要自動替我產生 7 天產品 wedge 或 30 天 MVP' in detail
py_compile.compile(str(ROOT/'api/routes/signalforge.py'), doraise=True)
failed=[k for k,v in checks.items() if not v]
print('SIGNALFORGE_USABLE_BETA_V1_1_ACCEPTANCE', json.dumps(checks,ensure_ascii=False,sort_keys=True))
if failed:
    print('FAIL',failed); sys.exit(2)
print('SIGNALFORGE_USABLE_BETA_V1_1_STATIC_PASS')
