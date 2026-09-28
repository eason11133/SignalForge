from __future__ import annotations
from pathlib import Path
import json, py_compile, sys
ROOT=Path(__file__).resolve().parent
checks={}
route=(ROOT/'api/routes/signalforge.py').read_text(encoding='utf-8')
client=(ROOT/'dashboard/src/api/client.ts').read_text(encoding='utf-8')
hooks=(ROOT/'dashboard/src/api/hooks.ts').read_text(encoding='utf-8')
detail=(ROOT/'dashboard/src/pages/CandidateDetail.tsx').read_text(encoding='utf-8')
checks['research_state_api']="/research-state" in route and "published_truth_changed" in route
checks['research_more_api']="/research-more" in route and "FounderDirectedExecutor" in route
checks['research_more_nonblocking']="await asyncio.to_thread(executor.execute" in route and "_research_more_lock = asyncio.Lock()" in route
checks['u14_u15_lazy_import']="founder_thesis_research_control_u14" in route and "founder_directed_research_u15" in route
checks['truth_snapshot_ui']="TRUTH SNAPSHOT" in detail and "CONTRADICTED" in detail and "UNKNOWN ·" in detail
checks['research_more_ui']="RESEARCH MORE · SHADOW" in detail and "補研究 1 次" in detail
checks['shadow_boundary_ui']="Retrieved candidate" in detail and "Published truth" in detail
checks['refresh_ui']="重新掃描 / 更新 Published" in detail and "useTriggerSignalForge" in detail
checks['discussion_handoff']="與 ChatGPT 討論" in detail and "buildDiscussionPrompt" in detail
checks['client_hooks']="signalforgeResearchMore" in client and "useSignalForgeResearchMore" in hooks
checks['no_product_ideation']="不要自動替我產生 7 天產品 wedge 或 30 天 MVP" in detail
py_compile.compile(str(ROOT/'api/routes/signalforge.py'), doraise=True)
failed=[k for k,v in checks.items() if not v]
print('SIGNALFORGE_USABLE_BETA_V1_ACCEPTANCE', json.dumps(checks,ensure_ascii=False,sort_keys=True))
if failed:
    print('FAIL',failed); sys.exit(2)
print('SIGNALFORGE_USABLE_BETA_V1_STATIC_PASS')
