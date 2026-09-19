from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from processors.signalforge_chatgpt_integration import (
    confirm_decision_artifact,
    integration_status,
    list_decision_artifacts,
    prepare_decision_artifact,
    reject_decision_artifact,
)
from processors.signalforge_founder_memory import list_founder_reasoning

passes=[]
fails=[]
def check(name, ok, detail=None):
    (passes if ok else fails).append((name,detail))
    print(("PASS" if ok else "FAIL"), name, (f"— {detail}" if detail is not None else ""))

print("="*104)
print("SIGNALFORGE PART 5 — CHATGPT INTEGRATION — FOUNDER CONFIRMATION ACCEPTANCE")
print("="*104)

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    payload={
        "subject_key":"rfq comparator",
        "subject_label":"RFQ Comparator",
        "thesis_id":"thesis-rfq",
        "discussion_summary":"Discussed wedge size and agreed to test the smallest paid workflow before building a platform.",
        "entries":[
            {"entry_type":"DECISION","statement":"Probe the RFQ comparison wedge before building a procurement platform.","reason":"It is the smallest decision-changing paid test."},
            {"entry_type":"HYPOTHESIS","statement":"SMB procurement teams may pay to avoid manual quote normalization."},
            {"entry_type":"CONSTRAINT","statement":"First test must fit within one week."},
            {"entry_type":"QUESTION","statement":"Will at least two target buyers agree to a paid pilot?"},
        ],
    }
    prepared=prepare_decision_artifact(root=root,source="CHATGPT_ACCEPTANCE",**payload)
    artifact=prepared.get("artifact") or {}
    aid=str(artifact.get("artifact_id") or "")
    check("conversation produces pending Decision Artifact", prepared.get("status")=="PREPARED" and aid.startswith("da_"), artifact.get("status"))
    check("prepared artifact has zero Market Truth writes", prepared.get("market_truth_writes")==0 and artifact.get("market_truth_writes")==0)
    before=list_founder_reasoning(subject_key="rfq comparator",thesis_id="thesis-rfq",root=root)
    check("prepare does not write Founder Memory", before.get("count")==0, before.get("count"))
    try:
        confirm_decision_artifact(artifact_id=aid,founder_confirmed=False,root=root)
        false_block=False
    except ValueError:
        false_block=True
    check("confirmation cannot be inferred or omitted", false_block)
    still=list_founder_reasoning(subject_key="rfq comparator",thesis_id="thesis-rfq",root=root)
    check("failed confirmation still writes nothing", still.get("count")==0)
    confirmed=confirm_decision_artifact(artifact_id=aid,founder_confirmed=True,root=root)
    check("explicit Founder confirmation commits artifact", confirmed.get("status")=="CONFIRMED", (confirmed.get("artifact") or {}).get("status"))
    after=list_founder_reasoning(subject_key="rfq comparator",thesis_id="thesis-rfq",root=root)
    check("confirmed entries append to Founder Memory", after.get("count")==4, after.get("count"))
    check("Founder Memory write remains zero market authority", all(x.get("market_authority")=="NONE" and x.get("market_truth_impact")=="NONE" for x in after.get("items") or []))
    check("write-back keeps Decision reason", any(x.get("entry_type")=="DECISION" and x.get("reason")=="It is the smallest decision-changing paid test." for x in after.get("items") or []))
    check("write-back is traceable to artifact", all(f"decision_artifact:{aid}" in (x.get("tags") or []) for x in after.get("items") or []))
    again=confirm_decision_artifact(artifact_id=aid,founder_confirmed=True,root=root)
    after2=list_founder_reasoning(subject_key="rfq comparator",thesis_id="thesis-rfq",root=root)
    check("re-confirm is idempotent", again.get("status")=="ALREADY_CONFIRMED" and after2.get("count")==4, after2.get("count"))

    p2=prepare_decision_artifact(root=root,subject_key="memory product",entries=[{"entry_type":"REJECTED_DIRECTION","statement":"Do not build a generic memory wrapper.","reason":"Commodity surface with weak right-to-win."}])
    aid2=str((p2.get("artifact") or {}).get("artifact_id") or "")
    rejected=reject_decision_artifact(artifact_id=aid2,reason="Founder chose not to write this discussion outcome",root=root)
    check("Founder can reject pending artifact", rejected.get("status")=="REJECTED")
    try:
        confirm_decision_artifact(artifact_id=aid2,founder_confirmed=True,root=root)
        reject_blocks=False
    except ValueError:
        reject_blocks=True
    check("rejected artifact cannot later commit", reject_blocks)

    try:
        prepare_decision_artifact(root=root,subject_key="unsafe",entries=[{"entry_type":"HYPOTHESIS","statement":"x y z","market_truth":"SUPPORTED"}])
        forbidden=False
    except ValueError:
        forbidden=True
    check("Decision Artifact rejects Market Truth fields", forbidden)

    listing=list_decision_artifacts(root=root)
    check("artifact store is append-only and statusful", listing.get("append_only") is True and listing.get("count")==2, listing.get("count"))

    db=root/'.radar_runtime/signalforge_chatgpt_decision_artifacts.sqlite3'
    conn=sqlite3.connect(db)
    raw=conn.execute('SELECT payload_json FROM decision_artifact_events WHERE seq=1').fetchone()[0]
    tampered=json.loads(raw); tampered['subject_label']='TAMPERED'
    conn.execute('UPDATE decision_artifact_events SET payload_json=? WHERE seq=1',(json.dumps(tampered,ensure_ascii=False,sort_keys=True,separators=(',',':')),))
    conn.commit(); conn.close()
    try:
        list_decision_artifacts(root=root)
        tamper_visible=False
    except RuntimeError:
        tamper_visible=True
    check("tampered Decision Artifact SQLite hash-chain fails visibly", tamper_visible)

# Fake the optional MCP package so we can inspect tool registration + annotations without installing the dependency.
class FakeToolAnnotations:
    def __init__(self,**kwargs): self.__dict__.update(kwargs)
class FakeMCPServer:
    def __init__(self,name): self.name=name; self.tools=[]; self.annotations={}
    def tool(self,**kwargs):
        def deco(fn): self.tools.append(fn.__name__); self.annotations[fn.__name__]=kwargs.get('annotations'); return fn
        return deco
    def run(self,*args,**kwargs): return None
fake_pkg=types.ModuleType('mcp')
fake_server=types.ModuleType('mcp.server')
fake_types=types.ModuleType('mcp.types')
fake_server.MCPServer=FakeMCPServer
fake_types.ToolAnnotations=FakeToolAnnotations
old_mcp=sys.modules.get('mcp'); old_server=sys.modules.get('mcp.server'); old_types=sys.modules.get('mcp.types')
sys.modules['mcp']=fake_pkg; sys.modules['mcp.server']=fake_server; sys.modules['mcp.types']=fake_types
try:
    spec=importlib.util.spec_from_file_location('sf_part5_mcp_acceptance',ROOT/'signalforge_mcp_server.py')
    mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
    server=mod.build_mcp_server()
    tools=set(server.tools); annotations=server.annotations
finally:
    if old_mcp is None: sys.modules.pop('mcp',None)
    else: sys.modules['mcp']=old_mcp
    if old_server is None: sys.modules.pop('mcp.server',None)
    else: sys.modules['mcp.server']=old_server
    if old_types is None: sys.modules.pop('mcp.types',None)
    else: sys.modules['mcp.types']=old_types

expected={
    'signalforge_search','signalforge_get_thesis','signalforge_probe_idea','signalforge_falsify',
    'signalforge_compare','signalforge_prepare_decision_artifact','signalforge_pending_decision_artifacts'
}
check("MCP adapter exposes required Part 1-4 read tools", expected.issubset(tools), sorted(tools))
check("MCP adapter exposes prepare Decision Artifact", 'signalforge_prepare_decision_artifact' in tools)
check("MCP adapter deliberately exposes no confirm/commit tool", not any('confirm' in x or 'commit' in x for x in tools), sorted(tools))

status=integration_status()
check("integration status declares Secure MCP Tunnel only", status.get('supported_deployment_mode')=='SECURE_MCP_TUNNEL_ONLY' and status.get('public_remote_endpoint')=='NOT_SUPPORTED_UNAUTHENTICATED')
check("integration status declares Founder-only write-back", 'FOUNDER_CONFIRMS_IN_SIGNALFORGE_UI' in str(status.get('writeback_policy')))
check("prepare tool is classified WRITE/MODIFY", status.get('tool_permission_contract',{}).get('signalforge_prepare_decision_artifact')=='WRITE_MODIFY_PENDING_ARTIFACT' and getattr(annotations.get('signalforge_prepare_decision_artifact'), 'read_only_hint', None) is False)
check("live ChatGPT acceptance separated from engineering", status.get('engineering_acceptance') in {'PASS','FAIL'} and 'LIVE_ACCEPTANCE_PENDING' in str(status.get('live_chatgpt_acceptance')))
check("integration status reports zero Market Truth writes", status.get('market_truth_writes')==0)

api=(ROOT/'api/routes/signalforge.py').read_text(encoding='utf-8')
client=(ROOT/'dashboard/src/api/client.ts').read_text(encoding='utf-8')
hooks=(ROOT/'dashboard/src/api/hooks.ts').read_text(encoding='utf-8')
page=(ROOT/'dashboard/src/pages/Discussion.tsx').read_text(encoding='utf-8')
app=(ROOT/'dashboard/src/App.tsx').read_text(encoding='utf-8')
sidebar=(ROOT/'dashboard/src/components/Sidebar.tsx').read_text(encoding='utf-8')
processor=(ROOT/'processors/signalforge_chatgpt_integration.py').read_text(encoding='utf-8')
mcp_src=(ROOT/'signalforge_mcp_server.py').read_text(encoding='utf-8')

check("API exposes integration status + discussion packet", "/chatgpt/status" in api and "/chatgpt/discussion-packet/{thesis_id}" in api)
check("API exposes prepare/list/confirm/reject artifact workflow", all(x in api for x in ["/chatgpt/decision-artifacts","/{artifact_id}/confirm","/{artifact_id}/reject"]))
check("API confirm requires explicit founder_confirmed true", "payload.get('founder_confirmed') is not True" in api)
check("processor has no Market Truth writer import", 'from processors.radar_ledger import' not in processor and 'import radar_ledger' not in processor and 'update_claim(' not in processor and 'publish_claim' not in processor)
check("MCP source has no Founder Memory confirm tool", 'signalforge_confirm_decision_artifact' not in mcp_src and 'def confirm' not in mcp_src)
check("client exposes Part 5 workflow", all(x in client for x in ['signalforgeChatGPTStatus','signalforgeDiscussionPacket','prepareSignalForgeDecisionArtifact','confirmSignalForgeDecisionArtifact']))
check("hooks expose Part 5 workflow", all(x in hooks for x in ['useSignalForgeChatGPTStatus','useSignalForgeDiscussionPacket','useSignalForgeDecisionArtifacts','useConfirmSignalForgeDecisionArtifact']))
check("Discussion UI makes Founder confirmation first-class", '確認寫入 Founder Memory' in page and 'window.confirm' in page)
check("Discussion UI makes Market Truth boundary visible", 'Market Truth writes: <b>0</b>' in page and 'MCP confirm tool: <b>不存在</b>' in page)
check("Discussion UI separates Engineering vs Live ChatGPT acceptance", 'Live ChatGPT:' in page and 'Secure MCP Tunnel' in page and 'WRITE/MODIFY' in page)
check("Discussion UI has manual plan-limit fallback without direct write", 'CHATGPT_MANUAL_FALLBACK' in page and '建立 Pending Artifact' in page)
check("Discussion route and sidebar are first-class", 'path="discuss"' in app and '跟 ChatGPT 討論' in sidebar)

print('-'*104)
print(f"RESULT: {len(passes)}/{len(passes)+len(fails)} PASS")
if fails:
    for name,detail in fails: print('FAILED:',name,detail)
    raise SystemExit(1)
print('FINAL_STATUS: SIGNALFORGE_CHATGPT_INTEGRATION_PART5_ACCEPTANCE_PASS')
