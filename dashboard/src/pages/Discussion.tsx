import { useMemo, useState } from "react";
import { CheckCircle2, Clipboard, MessageSquareText, PlugZap, ShieldCheck, XCircle } from "lucide-react";
import {
  useConfirmSignalForgeDecisionArtifact,
  usePrepareSignalForgeDecisionArtifact,
  useRejectSignalForgeDecisionArtifact,
  useSignalForgeChatGPTStatus,
  useSignalForgeDecisionArtifacts,
  useSignalForgeDecisionPortfolio,
  useSignalForgeDiscussionPacket,
} from "../api/hooks";
import type { SignalForgeDecisionArtifactEntry, SignalForgeFounderMemoryEntryType } from "../api/client";

const entryTypes: SignalForgeFounderMemoryEntryType[] = ["DECISION","HYPOTHESIS","REJECTED_DIRECTION","CONSTRAINT","QUESTION","ASSUMPTION","REASON"];

export default function Discussion() {
  const status = useSignalForgeChatGPTStatus();
  const portfolio = useSignalForgeDecisionPortfolio({ limit: 50, weekly_hours: 10, cash_need: "HIGH", long_term: "HIGH" });
  const [thesisId,setThesisId]=useState("");
  const packet=useSignalForgeDiscussionPacket(thesisId);
  const artifacts=useSignalForgeDecisionArtifacts();
  const prepare=usePrepareSignalForgeDecisionArtifact();
  const confirm=useConfirmSignalForgeDecisionArtifact();
  const reject=useRejectSignalForgeDecisionArtifact();
  const [manualJson,setManualJson]=useState("");
  const items=portfolio.data?.items || [];
  const selected=useMemo(()=>items.find(x=>x.thesis_id===thesisId),[items,thesisId]);

  const copyPacket=async()=>{
    if(!packet.data) return;
    await navigator.clipboard.writeText(JSON.stringify(packet.data,null,2));
  };

  const prepareManual=()=>{
    try{
      const raw=JSON.parse(manualJson) as {subject_key?:string;subject_label?:string;thesis_id?:string;discussion_summary?:string;entries?:SignalForgeDecisionArtifactEntry[]};
      if(!raw.subject_key || !Array.isArray(raw.entries) || !raw.entries.length) throw new Error("需要 subject_key 與 entries[]");
      prepare.mutate({subject_key:raw.subject_key,subject_label:raw.subject_label,thesis_id:raw.thesis_id,discussion_summary:raw.discussion_summary,entries:raw.entries,source:"CHATGPT_MANUAL_FALLBACK"});
    }catch(err){ window.alert(`Decision Artifact JSON 無法使用：${String(err)}`); }
  };

  return <div className="mx-auto max-w-7xl space-y-5 p-5 lg:p-7">
    <header>
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-txt-info"><MessageSquareText size={13}/> Part 5 · ChatGPT Integration</div>
      <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-text-primary">把 SignalForge truth 帶進討論，決策確認後才寫回。</h1>
      <p className="mt-1 max-w-4xl text-xs text-text-secondary">ChatGPT/MCP 可以讀、Probe、Falsify、Compare、準備 Decision Artifact；Founder Memory 的真正寫入只能由你在這裡明確確認。Market Truth 永遠不可由這條路徑修改。</p>
    </header>

    <section className="grid gap-3 md:grid-cols-3">
      <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="flex items-center gap-2 text-xs font-semibold text-text-primary"><PlugZap size={14}/> MCP Engineering</div><div className="mt-2 text-sm font-semibold text-text-primary">{status.data?.engineering_acceptance || status.data?.mcp_adapter || "CHECKING"}</div><div className="mt-1 text-[10px] text-text-tertiary">Live ChatGPT: {status.data?.live_chatgpt_acceptance || "LIVE_ACCEPTANCE_PENDING"}<br/>Python SDK: {status.data?.mcp_python_dependency || "—"}</div></div>
      <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="text-xs font-semibold text-text-primary">Deployment / permissions</div><div className="mt-2 text-[11px] text-text-secondary">{status.data?.supported_deployment_mode || "SECURE_MCP_TUNNEL_ONLY"}<br/>Prepare artifact = <b>WRITE/MODIFY</b><br/>{status.data?.writeback_policy || "Founder confirmation required"}</div></div>
      <div className="rounded-2xl border border-success/20 bg-success/5 p-4"><div className="flex items-center gap-2 text-xs font-semibold text-txt-success"><ShieldCheck size={14}/> Authority</div><div className="mt-2 text-[11px] text-text-secondary">MCP confirm tool: <b>不存在</b><br/>Market Truth writes: <b>0</b></div></div>
    </section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <div className="text-sm font-semibold text-text-primary">Discussion Packet</div>
      <p className="mt-1 text-[10px] text-text-tertiary">Published Market Truth、Money Trail、Evidence Replay、Decision projection、Founder Memory/Delta 一次整理，但 authority 保持分離。</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <select value={thesisId} onChange={e=>setThesisId(e.target.value)} className="min-w-[280px] flex-1 rounded-xl border border-border-secondary bg-bg-secondary px-3 py-2.5 text-xs text-text-primary">
          <option value="">選一個 Published direction</option>
          {items.map(x=><option key={x.thesis_id || x.title} value={x.thesis_id || ""}>{x.current_track} · {x.title}</option>)}
        </select>
        <button onClick={copyPacket} disabled={!packet.data} className="rounded-xl border border-border-secondary px-4 py-2 text-xs font-semibold text-text-primary disabled:opacity-40"><Clipboard size={13} className="mr-1 inline"/>Copy packet</button>
      </div>
      {selected ? <div className="mt-3 rounded-xl bg-bg-secondary p-3 text-[11px] text-text-secondary"><b className="text-text-primary">{selected.current_track} · {selected.title}</b><br/>{selected.rank_explanation?.band} · Revenue {selected.revenue_wedge_decision} · Spend {selected.existing_spend}</div> : null}
      {packet.data ? <details className="mt-3"><summary className="cursor-pointer text-[10px] text-txt-info">查看實際 Discussion Packet</summary><pre className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl bg-bg-secondary p-3 text-[10px] text-text-secondary">{JSON.stringify(packet.data,null,2)}</pre></details> : null}
    </section>

    <section className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <div className="text-sm font-semibold text-text-primary">Pending Decision Artifacts</div>
      <p className="mt-1 text-[10px] text-text-tertiary">ChatGPT 可以準備，但「Prepare」本身是 persistent WRITE/MODIFY Pending Artifact；你在這裡看完內容後按確認，才會 append 到 Founder Memory。Market Truth 仍是 0 writes。</p>
      <div className="mt-3 space-y-3">
        {(artifacts.data?.items || []).length ? (artifacts.data?.items || []).map(a=><article key={a.artifact_id} className="rounded-xl border border-border-secondary bg-bg-secondary p-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="text-[9px] uppercase tracking-[0.1em] text-text-tertiary">{a.status}</span><div className="text-xs font-semibold text-text-primary">{a.subject_label || a.subject_key}</div></div><span className="text-[9px] text-text-tertiary">{a.artifact_id}</span></div>
          {a.discussion_summary ? <p className="mt-2 text-[10px] text-text-secondary">{a.discussion_summary}</p> : null}
          <div className="mt-2 space-y-1">{(a.entries || []).map((e,i)=><div key={i} className="rounded-lg border border-border-secondary bg-bg-primary p-2 text-[10px]"><b className="text-text-primary">{e.entry_type}</b> <span className="text-text-secondary">{e.statement}</span>{e.reason ? <div className="mt-1 text-text-tertiary">Why: {e.reason}</div> : null}</div>)}</div>
          {a.status === "PENDING_FOUNDER_CONFIRMATION" ? <div className="mt-3 flex gap-2"><button onClick={()=>{if(window.confirm("確認把這份 Decision Artifact 寫入 Founder Memory？Market Truth 不會被修改。")) confirm.mutate(a.artifact_id);}} className="rounded-lg bg-text-primary px-3 py-2 text-[10px] font-semibold text-bg-primary"><CheckCircle2 size={12} className="mr-1 inline"/>確認寫入 Founder Memory</button><button onClick={()=>reject.mutate({artifactId:a.artifact_id,reason:"Founder rejected in SignalForge UI"})} className="rounded-lg border border-border-secondary px-3 py-2 text-[10px] text-text-secondary"><XCircle size={12} className="mr-1 inline"/>拒絕</button></div> : null}
        </article>) : <div className="text-xs text-text-tertiary">目前沒有 Decision Artifact。</div>}
      </div>
    </section>

    <details className="rounded-2xl border border-border-secondary bg-bg-primary p-4">
      <summary className="cursor-pointer text-xs font-semibold text-text-primary">目前方案無法直接接 full MCP write 時的手動 fallback</summary>
      <p className="mt-2 text-[10px] text-text-tertiary">把 ChatGPT 產出的 Decision Artifact JSON 貼進來，只會建立 Pending artifact，仍然不會直接寫 Founder Memory。</p>
      <div className="mt-2 flex flex-wrap gap-2">{entryTypes.map(x=><span key={x} className="rounded-lg border border-border-secondary bg-bg-secondary px-2 py-1 text-[9px] text-text-tertiary">{x}</span>)}</div>
      <textarea value={manualJson} onChange={e=>setManualJson(e.target.value)} rows={9} placeholder={'{"subject_key":"rfq comparator","entries":[{"entry_type":"DECISION","statement":"先做 paid probe","reason":"最小可驗證 wedge"}]}'} className="mt-3 w-full rounded-xl border border-border-secondary bg-bg-secondary p-3 font-mono text-[10px] text-text-primary"/>
      <button onClick={prepareManual} disabled={!manualJson.trim() || prepare.isPending} className="mt-2 rounded-xl border border-border-secondary px-4 py-2 text-xs font-semibold text-text-primary disabled:opacity-40">建立 Pending Artifact</button>
    </details>

    <footer className="rounded-2xl border border-warning/20 bg-warning/5 p-4 text-[10px] text-text-secondary">Part 5 Engineering acceptance 與 Live ChatGPT acceptance 分開。這版唯一支援的 deployment contract 是 Secure MCP Tunnel；不支援 unauthenticated public remote endpoint。若目前 ChatGPT plan/workspace 不支援 full custom MCP，狀態應維持 PLATFORM_BLOCKED / LIVE_ACCEPTANCE_PENDING。</footer>
  </div>;
}
