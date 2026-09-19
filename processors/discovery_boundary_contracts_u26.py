from __future__ import annotations
import hashlib,json
from pathlib import Path

ENGINE_VERSION="signalforge-boundary-sentinel-u26-v1"
STATE=Path(".radar_runtime/discovery_boundary_sentinel_u26.json")
DB=Path(".radar_runtime/discovery_boundary_sentinel_v1.sqlite3")

ASPECTS=("WORKFLOW","FRICTION","MECHANISM","CONSTRAINT","CONSEQUENCE")
VERDICTS=("SAME","RELATED","DISTINCT","UNKNOWN")
CASE_STATUSES=("PROVISIONAL_SENTINEL_SEED","CHALLENGE_ONLY","INSUFFICIENT")

TRUTH_BOUNDARY=(
    "U26_BUILDS_A_PROVISIONAL_BOUNDARY_SENTINEL_SEED_FROM_DECONTAMINATED_FROZEN_CONTENT. "
    "WEAK_SIGNATURES_ARE USED ONLY TO SAMPLE HARD CASES AND ARE HIDDEN FROM THE JUDGE. "
    "LLM_JUDGMENTS_ARE NOT GROUND_TRUTH; BIDIRECTIONAL_CONSISTENCY_AND_EVIDENCE_GROUNDING ARE QUALITY_GATES ONLY. "
    "NO_REPRESENTATION_ARM_CAN_BE_PROMOTED_FROM_U26. NO_MARKET_DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM_IS_CREATED. PRODUCT_IDEATION=0"
)

def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

def sha256_text(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()

def stable_id(prefix,*parts,n=24):
    return prefix+"_"+sha256_text("|".join(str(x) for x in parts))[:n]

def norm_space(s):
    return " ".join(str(s or "").split())

def freeze_hash(text):
    return sha256_text(norm_space(text))
