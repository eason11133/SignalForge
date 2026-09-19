import json,sqlite3,tempfile,hashlib
from pathlib import Path
import processors.discovery_knowledge_contracts_u23 as c
import processors.discovery_event_ledger_u23 as l
import processors.discovery_framegraph_projection_u23 as p
import processors.discovery_legacy_adapter_u23 as a
import processors.discovery_shadow_foundation_u23 as f

def ck(n,x,d=""):
    if not x: raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Contract-level pre-mortem.
fake={"basis":"THIS_IS_NOT_AN_EXPLICIT_SIGNATURE","basis_class":"FALLBACK_TEXT","basis_score":999}
route,_=a.route_granularity(fake)
ck("U23_PM01_NUMERIC_SCORE_NOT_ANCHOR",route!="DIRECT_SIGNATURE_ANCHOR",route)
ck("U23_PM04_UNKNOWN_FIRST_CLASS","UNKNOWN" in c.VERDICTS)

try:
    c.make_event(event_type="EVIDENCE_SPAN_PROPOSED",stream_type="x",stream_id="1",
                 producer="bad",producer_version="1",producer_plane="INTELLIGENCE",payload={})
    raise AssertionError("authority should fail")
except c.ContractError:
    print("U23_PM10_DOWNSTREAM_UPSTREAM_AUTHORITY_BLOCKED: PASS")

with tempfile.TemporaryDirectory() as td:
    root=Path(td);(root/".radar_runtime").mkdir()
    db=root/".radar_runtime"/"fixture.sqlite3"
    con=sqlite3.connect(db)
    con.execute("CREATE TABLE items(doc_key TEXT PRIMARY KEY,payload TEXT)")
    rows=[]
    # Keep semantics intentionally mixed; explicit signatures are weak labels, fallback text stays fallback.
    sigs=["SLOW_DELAY","CRASH_FREEZE","STATE_LOSS","ACCESS_UNAVAILABLE"]
    for i in range(420):
        if i<220:
            payload={"need_frame":{"version":"need-frame-v1","problem_signature":sigs[i%4],
                                   "problem":"users report "+sigs[i%4].lower().replace("_"," ")},
                     "source_type":"github_issues","metadata":{"package_name":"package_name"}}
        else:
            payload={"evidence_atom":{"text":f"Users describe a manual workflow problem number {i} with repeated handoffs and review"},
                     "title":f"Workflow complaint {i}","source_type":"hackernews",
                     "metadata":{"schema_version":"v3","padding":"x"*120}}
        rows.append((f"doc-{i}",json.dumps(payload)))
    con.executemany("INSERT INTO items VALUES(?,?)",rows);con.commit();con.close()
    selection={"path":str(db),"table":"items","rows":420,"columns":["doc_key","payload"]}

    raw_before=sha(db)
    events,diag=a.build_events(root,limit=1000,selection=selection)
    ck("U23_U21_BASIS_PASS",diag["status"]=="PASS",str(diag.get("basis_quality")))
    ck("U23_PM03_FAMILY_FORMATION_NOT_CALLED",diag["family_formation_called"] is False)
    ck("U23_PM16_WEAK_LABEL_ONLY",diag["weak_anchor_observations"]>0)
    ck("U23_PM11_VALID_TIME_NOT_FABRICATED",
       all(e.get("valid_at") is None for e in events if e["event_type"]=="EVIDENCE_SPAN_PROPOSED"))

    auth=c.make_event(event_type="INTERPRETATION_PROVIDER_ELIGIBILITY_CHANGED",
        stream_type="provider",stream_id="DKF_U23",producer="test",producer_version="1",
        producer_plane="CONTROL",payload={"provider":"DKF_U23","level":"L1_SHADOW"})
    first=l.append_events(root,[auth]+events)
    n1=l.count_events(root)
    second=l.append_events(root,[auth]+events);n2=l.count_events(root)
    ck("U23_PM06_IDEMPOTENT_APPEND",second["inserted"]==0 and n1==n2,str((first,second,n1,n2)))

    con=l.connect(root)
    try:
        con.execute("UPDATE events SET producer='x' WHERE event_id=1");con.commit()
        raise AssertionError("update must fail")
    except sqlite3.DatabaseError:
        print("U23_PM05_APPEND_ONLY_UPDATE_BLOCKED: PASS")
        con.rollback()
    try:
        con.execute("DELETE FROM events WHERE event_id=1");con.commit()
        raise AssertionError("delete must fail")
    except sqlite3.DatabaseError:
        print("U23_PM05_APPEND_ONLY_DELETE_BLOCKED: PASS")
        con.rollback()
    con.close()

    pr1=p.rebuild(root);h1=pr1["projection_hash"]
    pr2=p.rebuild(root);h2=pr2["projection_hash"]
    ck("U23_PM07_PROJECTION_REBUILD_DETERMINISTIC",h1==h2,h1)

    # Revision coexists historically; projection shows current.
    j1=c.make_event(event_type="CONSTRAINT_JUDGED",stream_type="constraint",stream_id="C1",
        producer="judge",producer_version="1",producer_plane="INTERPRETATION",
        payload={"constraint_id":"C1","aspect":"MECHANISM","left_id":"A","right_id":"B","verdict":"SAME"})
    j2=c.make_event(event_type="CONSTRAINT_REVISED",stream_type="constraint",stream_id="C1",
        producer="judge",producer_version="2",producer_plane="CONTROL",causation_event_key=j1["event_key"],
        payload={"constraint_id":"C1","aspect":"MECHANISM","left_id":"A","right_id":"B","verdict":"DISTINCT"})
    l.append_events(root,[j1,j2]);p.rebuild(root)
    econ=l.connect(root)
    hist=econ.execute("SELECT COUNT(*) FROM events WHERE stream_id='C1'").fetchone()[0];econ.close()
    pc=sqlite3.connect(root/p.DB)
    cur=pc.execute("SELECT verdict FROM constraints_current WHERE constraint_id='C1'").fetchone()[0];pc.close()
    ck("U23_CONFLICT_REVISION_HISTORY_PRESERVED",hist==2 and cur=="DISTINCT",str((hist,cur)))

    # Justification invalidation propagation.
    claim=c.make_event(event_type="CLAIM_PROPOSED",stream_type="claim",stream_id="CL1",
        producer="frames",producer_version="1",producer_plane="INTERPRETATION",
        payload={"claim_id":"CL1","claim":{"subject":"X","relation":"CAUSES","object":"Y"}})
    just=c.make_event(event_type="JUSTIFICATION_ATTACHED",stream_type="claim",stream_id="CL1",
        producer="frames",producer_version="1",producer_plane="INTERPRETATION",
        payload={"claim_id":"CL1","justification_id":"J1","depends_on_event_keys":[events[0]["event_key"]]})
    l.append_events(root,[claim,just]);p.rebuild(root)
    pc=sqlite3.connect(root/p.DB);s1=pc.execute("SELECT status FROM claims WHERE claim_id='CL1'").fetchone()[0];pc.close()
    inv=c.make_event(event_type="JUSTIFICATION_INVALIDATED",stream_type="claim",stream_id="CL1",
        producer="control",producer_version="1",producer_plane="CONTROL",
        payload={"claim_id":"CL1","justification_id":"J1","reason":"adversarial_test"})
    l.append_events(root,[inv]);p.rebuild(root)
    pc=sqlite3.connect(root/p.DB);s2=pc.execute("SELECT status FROM claims WHERE claim_id='CL1'").fetchone()[0];pc.close()
    ck("U23_PM08_INVALIDATION_PROPAGATES",s1=="SUPPORTED" and s2=="UNSUPPORTED",str((s1,s2)))

    # Unknown schema fails closed before append.
    bad=dict(events[0]);bad["event_key"]="evt_bad";bad["schema_version"]="future-v99"
    try:
        l.append_events(root,[bad]);raise AssertionError("schema should block")
    except c.ContractError:
        print("U23_PM09_UNKNOWN_SCHEMA_BLOCKED: PASS")

    ck("U23_PM12_RAW_CACHE_UNCHANGED",sha(db)==raw_before)

    # Intelligence hypothesis may exist, but cannot mutate constraint/evidence projection.
    hyp=c.make_event(event_type="ANALOGY_HYPOTHESIS_CREATED",stream_type="hypothesis",stream_id="H1",
        producer="lab",producer_version="1",producer_plane="INTELLIGENCE",
        payload={"hypothesis_id":"H1","kind":"STRUCTURAL_ANALOGY","note":"diagnostic only"})
    before=p.summary(root)
    l.append_events(root,[hyp]);p.rebuild(root)
    after=p.summary(root)
    pc=sqlite3.connect(root/p.DB)
    hn=pc.execute("SELECT COUNT(*) FROM intelligence_hypotheses").fetchone()[0];pc.close()
    ck("U23_INTELLIGENCE_HYPOTHESIS_ISOLATED",hn==1 and
       before["active_evidence_spans"]==after["active_evidence_spans"] and
       before["weak_anchor_observations"]==after["weak_anchor_observations"])

    print("U23_LOCAL_ACCEPTANCE_ALL_PASS",f.ENGINE_VERSION)
