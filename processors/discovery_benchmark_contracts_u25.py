from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ENGINE_VERSION="signalforge-benchmark-decontamination-u25-v1"
STATE=Path(".radar_runtime/discovery_benchmark_decontamination_u25.json")
DB=Path(".radar_runtime/discovery_benchmark_decontamination_v1.sqlite3")
TRUTH_BOUNDARY=(
    "U25_SEPARATES_WEAK_LABELS_FROM_REPRESENTATION_INPUTS. EXPLICIT_SIGNATURE_FIELDS_MAY DEFINE ONLY WEAK_LABELS "
    "AND ARE FORBIDDEN AS BENCHMARK_CONTENT. RECOVERED_CONTENT_IS_STILL_NOT_GROUND_TRUTH. "
    "U24_WEAK_LABEL_SCORES_ARE_INVALID_FOR_MODEL_COMPARISON_WHERE_LABEL_TEXT_LEAKED_INTO_INPUT. "
    "NO_FAMILY_DEMAND_WTP_OPPORTUNITY_OR_BUILD_CLAIM_IS_CREATED; PRODUCT_IDEATION=0"
)
def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
def norm(x):
    s=str(x or "").strip().lower()
    s=re.sub(r"(?<=[a-z0-9])(?=[A-Z])","_",s)
    s=re.sub(r"[^a-z0-9\u3400-\u9fff]+","_",s)
    return re.sub(r"_+","_",s).strip("_")
