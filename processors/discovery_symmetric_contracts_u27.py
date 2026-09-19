from __future__ import annotations
import hashlib,json
from pathlib import Path

ENGINE_VERSION="signalforge-criteria-first-symmetric-judge-u27-v1"
STATE=Path(".radar_runtime/discovery_symmetric_judge_u27.json")
DB=Path(".radar_runtime/discovery_symmetric_judge_v1.sqlite3")
U26_DB=Path(".radar_runtime/discovery_boundary_sentinel_v1.sqlite3")

ASPECTS=("WORKFLOW","FRICTION","MECHANISM","CONSTRAINT","CONSEQUENCE")
VERDICTS=("SAME","RELATED","DISTINCT","UNKNOWN")

TRUTH_BOUNDARY=(
    "U27_TESTS_A_CRITERIA_FIRST_SYMMETRIC_ADJUDICATION_PROTOCOL_ON_THE_EXACT_FROZEN_U26_CASES. "
    "WEAK_SIGNATURES_AND_CANDIDATE_KIND_ARE HIDDEN_FROM_BOTH_CRITERIA_BUILDER_AND_VERDICT_JUDGE. "
    "SHARED_CRITERIA_ARE_BUILT_ONCE_PER_CASE_IN_CANONICAL_HASH_ORDER_AND_REUSED_UNCHANGED_FOR_FORWARD_AND_REVERSE JUDGMENTS. "
    "LLM_OUTPUT_IS_NOT_GROUND_TRUTH; U27_CANNOT_PROMOTE_SENTINEL_OR_REPRESENTATION_AUTHORITY. "
    "NO_MARKET_DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM_IS_CREATED; PRODUCT_IDEATION=0"
)

def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

def sha256_text(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()

def norm_space(s):
    return " ".join(str(s or "").split())
