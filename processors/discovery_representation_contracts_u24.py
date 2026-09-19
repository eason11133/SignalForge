from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ENGINE_VERSION="signalforge-representation-audit-u24-v1"
STATE=Path(".radar_runtime/discovery_representation_audit_u24.json")
RESULT_DB=Path(".radar_runtime/discovery_representation_lab_v1.sqlite3")

ARMS=(
    "R0_RAW_TEXT",
    "R1_SALIENT_CODE",
    "R2_FIXED_ATOMS",
    "R3_HYBRID_FRAME",
    "R4_FRAME_DESCRIPTION",
)

TRUTH_BOUNDARY=(
    "U24_IS_A_SHADOW_REPRESENTATION_SCREENING_AND_ANCHOR_AUDIT. "
    "EXPLICIT_SIGNATURES_ARE_WEAK_LABELS_NOT_GROUND_TRUTH; ALL REPRESENTATION SCORES_ARE_PROXIES. "
    "NO_ARM_MAY_BE_PROMOTED_TO_PRODUCTION_FROM_U24_ALONE. "
    "NO_FAMILY_MARKET_DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM_IS_CREATED; PRODUCT_IDEATION=0"
)

def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def stable_id(prefix,*parts,n=24):
    return prefix+"_"+sha256_text("|".join(str(x) for x in parts))[:n]

def clean_text(s):
    x=str(s or "").strip()
    return re.sub(r"\s+"," ",x)

def percentile(vals,p):
    vals=sorted(float(x) for x in vals)
    if not vals:return None
    if len(vals)==1:return vals[0]
    k=(len(vals)-1)*p
    lo=int(k);hi=min(lo+1,len(vals)-1);f=k-lo
    return vals[lo]*(1-f)+vals[hi]*f
