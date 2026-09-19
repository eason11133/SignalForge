from __future__ import annotations
import hashlib,json,re,sqlite3
from collections import Counter
from pathlib import Path
import processors.semantic_basis_contract_u21 as u21
from processors.discovery_knowledge_contracts_u23 import make_event, normalize_signature

PRODUCER="DKF_U23_LEGACY_U21_ADAPTER"
PRODUCER_VERSION="u23-v1"

def _sha(s):return hashlib.sha256(str(s).encode("utf-8")).hexdigest()

def _row_keys(selection:dict,limit:int):
    con=sqlite3.connect(selection["path"]);con.row_factory=sqlite3.Row
    rows=con.execute(f'SELECT * FROM "{selection["table"]}" LIMIT ?', (limit,)).fetchall();con.close()
    out=[]
    for i,r in enumerate(rows):
        d=dict(r);key=d.get("doc_key") or d.get("id") or d.get("key") or f"row:{i}"
        out.append(str(key))
    return out

def route_granularity(record:dict):
    text=str(record.get("basis") or "")
    cls=record.get("basis_class")
    reasons=[]
    if cls=="EXPLICIT_SIGNATURE":
        return "DIRECT_SIGNATURE_ANCHOR",["EXPLICIT_SIGNATURE_CLASS"]
    units=re.findall(r"[A-Za-z0-9\u3400-\u9fff]+",text)
    clause=sum(text.lower().count(x) for x in (" and "," but "," because "," while ",";","\n","•"," - "))
    if len(units)<3 or len(text)<16:
        return "INSUFFICIENT_CONTEXT",["TOO_SHORT_FOR_STRUCTURE"]
    if len(text)>320 or len(units)>55 or clause>=3:
        reasons.append("MULTI_CLAUSE_OR_LONG_TEXT")
        return "COMPOSITE_CANDIDATE",reasons
    if cls=="FALLBACK_TEXT":
        reasons.append("LEGACY_FALLBACK_TEXT")
    return "SINGLE_BASIS_CANDIDATE",reasons or ["BOUNDED_SEMANTIC_BASIS"]

def _selection(root:Path):
    loc=u21.u19.locate_observation_table(root)
    if loc.get("status")!="FOUND":
        raise RuntimeError("U23_NO_OBSERVATION_CACHE:"+str(loc))
    return loc["selected"]

def build_events(root:Path,limit:int=15000,selection:dict|None=None):
    selection=selection or _selection(root)
    records,bq=u21.read_semantic_records(selection,limit)
    if bq.get("status")!="PASS":
        return [],{"status":"BLOCKED_U21_SEMANTIC_BASIS","basis_quality":bq,"selection":selection}
    keys=_row_keys(selection,limit)
    timestamp_trusted=(bq.get("timestamp_yield") or 0)>=0.60
    events=[];anchors=Counter();routes=Counter()
    for r in records:
        idx=int(r["row_index"])
        obs_key=keys[idx] if idx<len(keys) else f"row:{idx}"
        text=str(r["basis"])
        span_id="span_"+_sha(obs_key+"|"+str(r["basis_path"])+"|"+text)[:24]
        valid_at=None
        valid_status="UNKNOWN_CORPUS_TIMESTAMP_COVERAGE_LOW"
        if timestamp_trusted and r.get("timestamp") is not None:
            valid_at=str(r["timestamp"]);valid_status="SOURCE_TIME_AVAILABLE"
        payload={
            "span_id":span_id,"text":text,"basis_path":r["basis_path"],"basis_class":r["basis_class"],
            "source":r.get("source") or "unknown",
            "locator":{"type":"FIELD_PATH","path":r["basis_path"]},
            "valid_time_status":valid_status,
            "legacy_basis_score_observed_but_not_semantically_consumed":r.get("basis_score"),
        }
        events.append(make_event(
            event_type="EVIDENCE_SPAN_PROPOSED",stream_type="evidence_span",stream_id=span_id,
            producer=PRODUCER,producer_version=PRODUCER_VERSION,producer_plane="INTERPRETATION",
            source_observation_key=obs_key,payload=payload,valid_at=valid_at,correlation_id="u23-foundation-ingest"))
        route,reasons=route_granularity(r);routes[route]+=1
        events.append(make_event(
            event_type="GRANULARITY_ROUTED",stream_type="observation",stream_id=obs_key,
            producer=PRODUCER,producer_version=PRODUCER_VERSION,producer_plane="INTERPRETATION",
            source_observation_key=obs_key,payload={"route":route,"reasons":reasons},
            correlation_id="u23-foundation-ingest"))
        # Critical pre-mortem control: only the explicit ENUM from U21 can make a weak anchor.
        # basis_score is intentionally ignored.
        if r.get("basis_class")=="EXPLICIT_SIGNATURE":
            sig=normalize_signature(text)
            if sig:
                anchors[sig]+=1
                events.append(make_event(
                    event_type="WEAK_ANCHOR_OBSERVED",stream_type="weak_anchor",stream_id=obs_key,
                    producer=PRODUCER,producer_version=PRODUCER_VERSION,producer_plane="INTERPRETATION",
                    source_observation_key=obs_key,
                    payload={"signature":sig,"label_status":"WEAK_LABEL_ONLY",
                             "truth_boundary":"EXPLICIT_SIGNATURE_IS_WEAK_LABEL_NOT_GROUND_TRUTH"},
                    correlation_id="u23-foundation-ingest"))
    diag={"status":"PASS","selection":selection,"basis_quality":bq,"semantic_records":len(records),
          "weak_anchor_observations":sum(anchors.values()),"distinct_weak_anchor_signatures":len(anchors),
          "top_weak_anchor_groups":anchors.most_common(20),"granularity_routes":dict(routes),
          "timestamp_trusted_for_valid_time":timestamp_trusted,
          "family_formation_called":False,"basis_score_consumed_as_anchor_contract":False}
    return events,diag
