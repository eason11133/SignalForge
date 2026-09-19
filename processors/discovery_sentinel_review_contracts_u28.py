from __future__ import annotations
import hashlib,json
from pathlib import Path

ENGINE_VERSION="signalforge-sentinel-review-u28-v1"
STATE=Path(".radar_runtime/discovery_sentinel_review_u28.json")
DB=Path(".radar_runtime/discovery_sentinel_candidate_v1.sqlite3")
U26_DB=Path(".radar_runtime/discovery_boundary_sentinel_v1.sqlite3")
U27_DB=Path(".radar_runtime/discovery_symmetric_judge_v1.sqlite3")
ASPECTS=("WORKFLOW","FRICTION","MECHANISM","CONSTRAINT","CONSEQUENCE")
VERDICTS=("SAME","RELATED","DISTINCT","UNKNOWN")
TRUTH_BOUNDARY=(
    "U28_PERFORMS_AN_INDEPENDENT_SECOND_PASS_REVIEW_OF_U27_STABLE_ASPECT_JUDGMENTS_ON_THE_EXACT_FROZEN_U26_TEXTS. "
    "THE REVIEWER_CANNOT_SEE_WEAK_SIGNATURES, CANDIDATE_KIND, U27_FORWARD_REVERSE_VERDICTS, OR PRIOR_CASE_STATUS. "
    "SENTINEL_CANDIDATES_ARE CASE_X_ASPECT_UNITS, NOT WHOLE_CASE_GOLD_LABELS. "
    "SAME_MODEL_WITH_DISTINCT_PROMPT_CONTEXT_IS_EXPLICITLY_NOT_CALLED_MODEL_INDEPENDENT. "
    "U28_CREATES_ONLY_SENTINEL_V1_CANDIDATES; IT DOES_NOT_FREEZE_SENTINEL_V1 OR PROMOTE_REPRESENTATION_AUTHORITY. "
    "NO_MARKET_DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM_IS_CREATED; PRODUCT_IDEATION=0"
)
def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
def sha256_text(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()
def norm_space(s):
    return " ".join(str(s or "").split())
