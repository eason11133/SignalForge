from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone

ENGINE_VERSION="signalforge-discovery-knowledge-foundation-u23-v1"
EVENT_SCHEMA_VERSION="discovery-event-v1"

AUTHORITY_LEVELS=("L0_OFF","L1_SHADOW","L2_READ_ASSIST","L3_RESEARCH_SEED","L4_ACTIVE_INTERPRETATION")
VERDICTS=("SAME","RELATED","DISTINCT","UNKNOWN")
ANCHOR_STATES=("WEAK_LABEL_ONLY","TRUSTED_ANCHOR","PROVISIONAL_ANCHOR","CONFLICTED_ANCHOR","INSUFFICIENT_SUPPORT")

TRUTH_INVARIANTS=(
    "NO_EVIDENCE_NO_EDGE",
    "UNKNOWN_IS_NOT_FALSE",
    "PROVISIONAL_IS_NOT_CONFIRMED",
    "FRAMEGRAPH_IS_DERIVED_NOT_CANONICAL",
    "TAXONOMY_NODE_IS_NOT_OPPORTUNITY",
    "NOVELTY_IS_NOT_DEMAND",
    "SIMILARITY_IS_NOT_SAME_MECHANISM",
    "LLM_JUDGMENT_IS_NOT_GROUND_TRUTH",
    "NO_UPSTREAM_WRITE_FROM_DOWNSTREAM_INFERENCE",
    "PRODUCT_IDEATION_0_UNTIL_FOUNDER_REQUEST",
)

EVENT_AUTHORITY={
    "EVIDENCE_SPAN_PROPOSED":{"INTERPRETATION"},
    "EVIDENCE_SPAN_INVALIDATED":{"CONTROL"},
    "WEAK_ANCHOR_OBSERVED":{"INTERPRETATION"},
    "GRANULARITY_ROUTED":{"INTERPRETATION"},
    "CONSTRAINT_JUDGED":{"INTERPRETATION"},
    "CONSTRAINT_REVISED":{"INTERPRETATION","CONTROL"},
    "CLAIM_PROPOSED":{"INTERPRETATION"},
    "JUSTIFICATION_ATTACHED":{"INTERPRETATION"},
    "JUSTIFICATION_INVALIDATED":{"CONTROL"},
    "TAXONOMY_NODE_PROPOSED":{"INTERPRETATION"},
    "TAXONOMY_NODE_STATE_CHANGED":{"CONTROL"},
    "INTERPRETATION_PROVIDER_ELIGIBILITY_CHANGED":{"CONTROL"},
    "ANALOGY_HYPOTHESIS_CREATED":{"INTELLIGENCE"},
}
FORBIDDEN_MARKET_CLAIM_TERMS=("DEMAND_CONFIRMED","WTP_CONFIRMED","OPPORTUNITY_CONFIRMED","BUILD_RECOMMENDED","MARKET_TRUTH")

class ContractError(ValueError): pass

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def canonical_json(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def normalize_signature(x:str)->str:
    s=str(x or "").strip()
    s=re.sub(r"(?<=[a-z0-9])(?=[A-Z])","_",s)
    s=re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+","_",s)
    return re.sub(r"_+","_",s).strip("_").upper()

def validate_authority(event_type:str, producer_plane:str):
    if event_type not in EVENT_AUTHORITY:
        raise ContractError("UNKNOWN_EVENT_TYPE:"+str(event_type))
    if producer_plane not in EVENT_AUTHORITY[event_type]:
        raise ContractError(f"AUTHORITY_DENIED:{producer_plane}:{event_type}")
    upper=event_type.upper()
    if any(t in upper for t in FORBIDDEN_MARKET_CLAIM_TERMS):
        raise ContractError("FORBIDDEN_MARKET_TRUTH_EVENT:"+event_type)

def make_event(*,event_type,stream_type,stream_id,producer,producer_version,producer_plane,
               source_observation_key=None,payload=None,valid_at=None,causation_event_key=None,
               correlation_id=None,recorded_at=None,schema_version=EVENT_SCHEMA_VERSION,stream_seq=1):
    validate_authority(event_type,producer_plane)
    payload=dict(payload or {})
    payload_json=canonical_json(payload)
    payload_sha=sha256_text(payload_json)
    identity={
        "event_type":event_type,"stream_type":stream_type,"stream_id":stream_id,
        "schema_version":schema_version,"producer":producer,"producer_version":producer_version,
        "producer_plane":producer_plane,"source_observation_key":source_observation_key,
        "valid_at":valid_at,"causation_event_key":causation_event_key,
        "correlation_id":correlation_id,"payload_sha256":payload_sha,
    }
    event_key="evt_"+sha256_text(canonical_json(identity))[:32]
    return {
        "event_key":event_key,"stream_type":stream_type,"stream_id":stream_id,"stream_seq":int(stream_seq),
        "event_type":event_type,"schema_version":schema_version,
        "recorded_at":recorded_at or utc_now(),"valid_at":valid_at,
        "producer":producer,"producer_version":producer_version,"producer_plane":producer_plane,
        "source_observation_key":source_observation_key,
        "causation_event_key":causation_event_key,"correlation_id":correlation_id,
        "payload_json":payload_json,"payload_sha256":payload_sha,
    }

def validate_event(e:dict):
    required=("event_key","stream_type","stream_id","stream_seq","event_type","schema_version","recorded_at",
              "producer","producer_version","producer_plane","payload_json","payload_sha256")
    missing=[k for k in required if k not in e]
    if missing: raise ContractError("EVENT_MISSING_FIELDS:"+",".join(missing))
    if e["schema_version"]!=EVENT_SCHEMA_VERSION:
        raise ContractError("UNSUPPORTED_EVENT_SCHEMA:"+str(e["schema_version"]))
    validate_authority(e["event_type"],e["producer_plane"])
    if sha256_text(e["payload_json"])!=e["payload_sha256"]:
        raise ContractError("EVENT_PAYLOAD_HASH_MISMATCH:"+e["event_key"])
    try: json.loads(e["payload_json"])
    except Exception as ex: raise ContractError("EVENT_PAYLOAD_JSON_INVALID:"+str(ex))
    return True
