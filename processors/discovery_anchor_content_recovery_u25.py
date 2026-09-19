from __future__ import annotations
import json,re,sqlite3
from collections import Counter
from pathlib import Path
import processors.semantic_basis_contract_u21 as u21
from processors.discovery_framegraph_projection_u23 import DB as PROJ_DB
from processors.discovery_benchmark_contracts_u25 import norm

ALLOWED_CONTENT_CLASSES={"STRONG_TEXT","FRAME_CONTENT","FALLBACK_TEXT"}

def load_weak_labels(root:Path):
    con=sqlite3.connect(root/PROJ_DB);con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute("""
      SELECT a.observation_key,a.signature,e.text AS leaked_input_text,e.basis_path AS leaked_input_path,
             e.basis_class AS leaked_input_class,e.source
      FROM weak_anchors a
      JOIN evidence_spans e ON e.observation_key=a.observation_key AND e.active=1
      ORDER BY a.signature,a.observation_key
    """)]
    con.close()
    # U23 has exactly one active selected span per observation today; de-duplicate defensively.
    out=[];seen=set()
    for r in rows:
        if r["observation_key"] in seen:continue
        seen.add(r["observation_key"]);out.append(r)
    return out

def _inspect_candidate(path:Path, preferred_table=None):
    if not path.exists() or not path.is_file():
        return None
    try:
        con=sqlite3.connect(str(path));con.row_factory=sqlite3.Row
        tables=[r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        if preferred_table and preferred_table in tables:
            tables=[preferred_table]+[t for t in tables if t!=preferred_table]
        results=[]
        for table in tables:
            try:
                cur=con.execute(f'SELECT * FROM "{table}" LIMIT 0')
                cols=[str(d[0]) for d in (cur.description or [])]
                key=next((x for x in ("doc_key","id","key") if x in cols),None)
                if not key or "payload" not in cols:
                    continue
                n=int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                results.append({
                    "path":str(path),"table":table,"rows":n,"columns":cols,
                    "resolved_key_column":key,"raw_source_contract":True,
                })
            except Exception:
                continue
        con.close()
        if not results:
            return None
        results.sort(key=lambda x:(x["table"]=="items",x["rows"]),reverse=True)
        return results[0]
    except Exception:
        return None

def locate_raw_cache(root:Path):
    runtime=root/".radar_runtime"
    diagnostics=[]

    # 1) Highest authority: U23 live foundation recorded and hash-checked the actual observation cache.
    u23_state=runtime/"discovery_knowledge_foundation_u23.json"
    if u23_state.exists():
        try:
            state=json.loads(u23_state.read_text(encoding="utf-8"))
            p=(state.get("source_cache") or {}).get("path")
            if p:
                pp=Path(p)
                if not pp.is_absolute():
                    pp=root/pp
                cand=_inspect_candidate(pp,"items")
                diagnostics.append({"source":"U23_LIVE_STATE","path":str(pp),"accepted":bool(cand)})
                if cand:
                    cand["locator_source"]="U23_LIVE_STATE"
                    cand["locator_diagnostics"]=diagnostics
                    return cand
        except Exception as e:
            diagnostics.append({"source":"U23_LIVE_STATE","error":f"{type(e).__name__}:{e}"[:300]})

    # 2) Canonical live filename.
    exact=runtime/"opportunity_observation_cache_v3.sqlite3"
    cand=_inspect_candidate(exact,"items")
    diagnostics.append({"source":"CANONICAL_FILENAME","path":str(exact),"accepted":bool(cand)})
    if cand:
        cand["locator_source"]="CANONICAL_FILENAME"
        cand["locator_diagnostics"]=diagnostics
        return cand

    # 3) Strict fallback only among files satisfying raw-observation schema.
    candidates=[]
    for pat in ("**/*.sqlite","**/*.sqlite3","**/*.db"):
        for p in runtime.glob(pat):
            low=p.name.lower()
            if any(x in low for x in (
                "discovery_knowledge_events","projection","evaluation","benchmark",
                "representation_lab","install_manifest","audit"
            )):
                continue
            c=_inspect_candidate(p,"items")
            if c:
                candidates.append(c)
    if candidates:
        candidates.sort(key=lambda x:(
            Path(x["path"]).name=="opportunity_observation_cache_v3.sqlite3",
            x["table"]=="items",x["rows"]),reverse=True)
        cand=candidates[0]
        diagnostics.append({"source":"STRICT_FILTERED_FALLBACK","accepted":True,
                            "candidate_count":len(candidates),"selected":cand["path"]})
        cand["locator_source"]="STRICT_FILTERED_FALLBACK"
        cand["locator_diagnostics"]=diagnostics
        return cand

    raise RuntimeError("U25_RAW_CACHE_NOT_FOUND_STRICT:"+json.dumps(diagnostics,sort_keys=True))

def _resolve_key_column(con, selection):
    table=selection["table"]
    locator_cols=[str(x) for x in (selection.get("columns") or [])]
    cursor_cols=[]
    pragma_cols=[]
    try:
        cur=con.execute(f'SELECT * FROM "{table}" LIMIT 0')
        cursor_cols=[str(d[0]) for d in (cur.description or [])]
    except Exception:
        pass
    try:
        pragma_cols=[str(r[1]) for r in con.execute(f'PRAGMA table_info("{table}")')]
    except Exception:
        pass

    resolved=None
    resolved_from=None
    for source, cols in (
        ("LOCATOR_COLUMNS", locator_cols),
        ("CURSOR_DESCRIPTION", cursor_cols),
        ("PRAGMA_TABLE_INFO", pragma_cols),
    ):
        for candidate in ("doc_key","id","key"):
            if candidate in cols:
                resolved=candidate
                resolved_from=source
                break
        if resolved:
            break

    return resolved, {
        "locator_columns": locator_cols,
        "cursor_columns": cursor_cols,
        "pragma_columns": pragma_cols,
        "resolved_key_column": resolved,
        "resolved_from": resolved_from,
    }

def _parse_payload_row(d):
    objects=[d]
    for v in d.values():
        j=u21._maybe_json(v)
        if j is not None:objects.append(j)
    flat=[]
    for o in objects:flat.extend(u21._flatten(o))
    return flat

def _best_nonlabel_content(flat,signature):
    rejects=Counter();cands=[]
    nsig=norm(signature)
    for path,val in flat:
        c=u21.classify_leaf(path,val)
        if not c.get("eligible"):
            rejects[c.get("reason","REJECTED")]+=1;continue
        if c.get("path_class")=="EXPLICIT_SIGNATURE":
            rejects["EXPLICIT_SIGNATURE_FORBIDDEN_AS_CONTENT"]+=1;continue
        if c.get("path_class") not in ALLOWED_CONTENT_CLASSES:
            rejects["NON_CONTENT_CLASS"]+=1;continue
        value=str(c.get("value") or "").strip()
        nv=norm(value)
        if not nv:
            rejects["EMPTY_NORMALIZED"]+=1;continue
        if nv==nsig:
            rejects["EXACT_LABEL_VALUE_FORBIDDEN"]+=1;continue
        # Forbid trivial rendering of the signature such as "slow delay" / "slow-delay".
        sig_tokens=[x for x in nsig.split("_") if x]
        val_tokens=[x for x in nv.split("_") if x]
        if sig_tokens and val_tokens and set(val_tokens)<=set(sig_tokens) and len(val_tokens)<=len(sig_tokens)+1:
            rejects["LABEL_ONLY_RENDERING_FORBIDDEN"]+=1;continue
        c=dict(c);c["path"]=path;c["value"]=value
        cands.append(c)
    if not cands:return None,rejects
    # Prefer semantic path class first; score only breaks ties INSIDE the same explicit class semantics.
    rank={"STRONG_TEXT":3,"FRAME_CONTENT":2,"FALLBACK_TEXT":1}
    cands.sort(key=lambda x:(rank.get(x["path_class"],0),x.get("score",0),
                             len(x.get("units") or []),-len(x["value"])),reverse=True)
    return cands[0],rejects

def recover(root:Path, selection=None):
    labels=load_weak_labels(root);sel=selection or locate_raw_cache(root)
    path=Path(sel["path"])
    if not path.is_absolute():path=root/path
    con=sqlite3.connect(path);con.row_factory=sqlite3.Row
    bykey={}
    key_col,key_diag=_resolve_key_column(con,sel)
    if not key_col:
        con.close()
        raise RuntimeError("U25_RAW_CACHE_NO_STABLE_KEY:"+json.dumps(key_diag,sort_keys=True))
    wanted=[x["observation_key"] for x in labels]
    # Small anchor set; parameterized point lookups avoid loading the 89 MB cache into memory.
    for k in wanted:
        row=con.execute(f'SELECT * FROM "{sel["table"]}" WHERE "{key_col}"=? LIMIT 1',(k,)).fetchone()
        if row is not None:bykey[k]=dict(row)
    con.close()

    out=[];missing=[];pathdist=Counter();classdist=Counter();reasons=Counter()
    leaked_before=0;leaked_after=0
    for lab in labels:
        sig=lab["signature"];k=lab["observation_key"]
        if norm(lab.get("leaked_input_text"))==norm(sig) or lab.get("leaked_input_class")=="EXPLICIT_SIGNATURE":
            leaked_before+=1
        d=bykey.get(k)
        if d is None:
            missing.append({"observation_key":k,"signature":sig,"reason":"RAW_ROW_NOT_FOUND"});continue
        flat=_parse_payload_row(d)
        chosen,rj=_best_nonlabel_content(flat,sig);reasons.update(rj)
        if chosen is None:
            missing.append({"observation_key":k,"signature":sig,"reason":"NO_RECOVERABLE_NONLABEL_CONTENT"});continue
        if norm(chosen["value"])==norm(sig):leaked_after+=1
        source,ts=u21._extract_source_time(flat)
        pathdist[chosen["path"]]+=1;classdist[chosen["path_class"]]+=1
        out.append({
          "observation_key":k,"signature":sig,"text":chosen["value"],"content_path":chosen["path"],
          "content_class":chosen["path_class"],"source":source,"timestamp":ts,
          "route":"DIRECT_SIGNATURE_ANCHOR_RECOVERED_CONTENT",
          "legacy_leaked_input_text":lab.get("leaked_input_text"),
          "legacy_leaked_input_path":lab.get("leaked_input_path"),
        })
    diag={
      "weak_label_observations":len(labels),"raw_rows_found":len(bykey),"recovered_content":len(out),
      "unrecovered":len(missing),"unrecovered_examples":missing[:20],
      "legacy_label_leak_observations":leaked_before,"recovered_label_leak_observations":leaked_after,
      "legacy_label_leak_rate":round(leaked_before/max(1,len(labels)),6),
      "recovered_label_leak_rate":round(leaked_after/max(1,len(out)),6),
      "selected_path_distribution":pathdist.most_common(20),
      "selected_class_distribution":dict(classdist),"rejection_reasons":dict(reasons),
      "raw_selection":sel,
      "raw_locator_source":sel.get("locator_source","INJECTED_SELECTION"),
      "raw_locator_diagnostics":sel.get("locator_diagnostics",[]),
      "key_resolution":key_diag,
      "truth_boundary":"SIGNATURE_IS_LABEL_ONLY; SELECTED_CONTENT_EXCLUDES_EXPLICIT_SIGNATURE_PATHS",
    }
    return out,diag
