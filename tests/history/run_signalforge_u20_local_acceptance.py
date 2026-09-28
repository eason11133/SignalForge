import json,sqlite3,tempfile
from pathlib import Path
import processors.discovery_family_rebase_u20 as u20

def ck(n,c,d=""):
    if not c:raise AssertionError(n+" "+d)
    print(n+": PASS"+(" | "+d if d else ""))

# Unit-level normalization/adversarial checks.
a=u20.normalize_basis("MANUAL_REENTRY")
ck("U20_STRUCTURED_SINGLE_SIGNATURE_ACCEPTED",a["eligible"] and len(a["features"])>=1,str(a))
b=u20.normalize_basis("paperToSlides")
ck("U20_CAMELCASE_SIGNATURE_ACCEPTED",b["eligible"],str(b))
c=u20.normalize_basis("人工重複輸入造成錯誤與延遲")
ck("U20_CJK_TEXT_ACCEPTED",c["eligible"] and len(c["features"])>=2,str(c))
d=u20.normalize_basis("a3f2d9c8b7e61122aa33445566778899")
ck("U20_OPAQUE_HASH_REJECTED",not d["eligible"],str(d))

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rt=root/".radar_runtime";rt.mkdir()
    db=rt/"observation_cache.sqlite"
    con=sqlite3.connect(db)
    con.execute("CREATE TABLE observations (cache_key TEXT PRIMARY KEY, payload TEXT)")
    rows=[];idx=0
    signatures=[
        "MANUAL_REENTRY","PAPER_TO_SLIDES","PRIVACY_CONSTRAINED_WORKFLOW",
        "CONTEXT_RECONSTRUCTION","FORMAT_TRANSFORMATION","HUMAN_VERIFICATION_BOTTLENECK",
        "人工重複輸入","格式轉換摩擦","隱私限制工作流"
    ]
    for block in range(14):
        for j in range(100):
            if j<80:
                sig=signatures[j%len(signatures)]
            elif j<95:
                sig=f"RARE_WORKFLOW_{block%4}_{j%5}"
            else:
                sig=f"NOVEL_BLOCK_{block}_{j%5}"
            payload={
                "problem_signature":sig,
                "source_type":"hackernews" if j%3 else "github_issues",
                "created_at":1700000000+idx*60,
                "title":"example "+sig,
            }
            rows.append((str(idx),json.dumps(payload,ensure_ascii=False)));idx+=1
    con.executemany("INSERT INTO observations VALUES (?,?)",rows);con.commit();con.close()

    loc=u20.u19.locate_observation_table(root)
    raw,q=u20.u19.read_records(loc["selected"])
    fam,diag=u20.form_families(raw)
    ck("U20_FAMILY_RECORD_YIELD_HIGH",diag["family_record_yield"]>=0.95,str(diag))
    ck("U20_MULTIPLE_FAMILIES_FORMED",diag["families"]>=9,str(diag["families"]))
    ck("U20_FAMILY_QUALITY_GATE_PASS",diag["status"]=="PASS",str(diag))
    st=u20.stability_probe(raw)
    ck("U20_FAMILY_ASSIGNMENT_REPEATABLE",st["status"]=="PASS",str(st))
    r=u20.analyze(root)
    ck("U20_END_TO_END_PASS",r["status"]=="PASS",str(r.get("family_formation")))
    gate=r["calibration_gate"]
    ck("U20_BUDGET_FAILS_CLOSED_UNLESS_ALL_GATES",
       gate["eligible_for_exploration_budget_control"] ==
       (gate["family_formation_gate"] and gate["family_stability_gate"] and gate["historical_calibration_gate"]),
       str(gate))
    ck("U20_STATE_PERSISTED",(root/u20.STATE).exists())
    ck("U20_POLICY_PERSISTED",(root/u20.POLICY).exists())

    # Negative formation: opaque/too-short texts must not produce fake coverage.
    bad=[]
    for i in range(500):
        bad.append({"basis":"x","basis_score":5,"source":"x","timestamp":1700000000+i,"row_index":i})
    bf,bd=u20.form_families(bad)
    ck("U20_BAD_FAMILY_INPUT_FAILS_CLOSED",bd["status"]!="PASS",str(bd))
    print("U20_LOCAL_ACCEPTANCE_ALL_PASS",u20.ENGINE_VERSION)
