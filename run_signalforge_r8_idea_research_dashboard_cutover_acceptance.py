from __future__ import annotations
from pathlib import Path
import json, sys

ROOT = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT

def text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")

checks: list[tuple[str, bool]] = []
def ck(name: str, cond: bool) -> None:
    checks.append((name, bool(cond)))
    print(("OK" if cond else "FAIL"), name)

app = text("dashboard/src/App.tsx")
side = text("dashboard/src/components/Sidebar.tsx")
page = text("dashboard/src/pages/IdeaResearch.tsx")
route = text("api/routes/signalforge.py")
loop = text("processors/signalforge_founder_idea_loop.py")

ck("home uses IdeaResearch", 'Route index element={<IdeaResearch />}' in app and 'import IdeaResearch from "./pages/IdeaResearch"' in app)
ck("Money Trail is legacy only", 'path="legacy-money-trail" element={<MoneyTrail />}' in app and 'Route index element={<MoneyTrail />}' not in app)
ck("sidebar primary research entry", 'label: "研究一個 idea"' in side and 'label: "今天錢在哪"' not in side)
ck("sidebar no Money Trail positioning", '找得到錢，也知道怎麼驗' not in side and '先查市場，再決定要不要做' in side)
ck("page invokes canonical founder idea probe", 'useProbeSignalForgeFounderIdea' in page and 'probe.mutate' in page)
ck("page renders FIX5 research_brief", 'payload?.research_brief' in page)
ck("page renders human comments", 'title="真人留言"' in page and 'brief.human_comments' in page)
ck("page renders products", 'title="產品 / 服務 / 作者提出的方案"' in page and 'brief.similar_products' in page)
ck("page renders repos separately", 'title="Repo / 開源方案"' in page and 'brief.repo_solutions' in page)
ck("page renders supporting evidence", 'title="其他有用資料"' in page and 'brief.supporting_evidence' in page)
ck("page renders counter evidence", 'title="反面 / 不支持資料"' in page and 'brief.counter_evidence' in page)
ck("page renders gaps", '目前缺口' in page and 'brief.gaps' in page)
ck("page renders search diagnostics", '搜尋診斷' in page and 'failed_sources' in page and 'query_bridge' in page)
ck("related results are visibly marked", 'match_level' in page and '>相關<' in page)
ck("legacy Money Trail result is rejected", 'hasLegacyOnlyResponse' in page and '後端回傳的不是 FIX5 research_brief' in page)
ck("page does not render retired decision fields", 'published_money_trail' not in page and 'decision_frontier' not in page and 'Opportunity Score' not in page)
ck("API route still invokes founder idea loop", '/founder-idea/probe' in route and 'probe_founder_idea' in route)
ck("FIX5 processor exposes research_brief", '"research_brief": brief' in loop and '"mode": "IDEA_RESEARCH"' in loop)
ck("FIX5 no market truth write", '"market_truth_writes": 0' in loop)

failed = [name for name, ok in checks if not ok]
print("-" * 90)
print(json.dumps({"total": len(checks), "ok": len(checks)-len(failed), "failed": failed}, ensure_ascii=False))
if failed:
    raise SystemExit(2)
print("IDEA_RESEARCH_DASHBOARD_CUTOVER_ACCEPTANCE_OK")
