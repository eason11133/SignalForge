import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, ChevronDown, FlaskConical, ShieldCheck, Sparkles } from "lucide-react";
import { useSignalForgeBrainThesis } from "../api/hooks";
import { CardSkeleton } from "../components/common/Skeleton";

function tone(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (["SUPPORTED", "BOTH", "READY"].includes(v)) return "border-success/20 bg-bg-success/45 text-txt-success";
  if (["REFUTED", "BLOCKED"].includes(v)) return "border-danger/20 bg-bg-danger/35 text-danger";
  if (["PARTIAL", "INSUFFICIENT", "RESEARCH_READY"].includes(v)) return "border-warning/20 bg-bg-warning/35 text-txt-warning";
  return "border-border-secondary bg-bg-secondary text-text-secondary";
}

function trackLabel(value?: string) {
  const v = String(value || "NEITHER").toUpperCase();
  if (v === "BOTH") return "最值得看";
  if (v === "ZIP2_STRUCTURAL") return "結構性機會";
  if (v === "FAST_VALIDATION") return "可快速驗證";
  return "還不能下注";
}

function actionLabel(value?: string) {
  const v = String(value || "").toUpperCase();
  if (v.includes("IDENTIFY_REACHABLE_BUYER_CHANNEL")) return "找出你真的接觸得到的買家管道";
  if (v.includes("BUYER") && v.includes("CHANNEL")) return "找出你真的接觸得到的買家管道";
  if (v.includes("WTP") || v.includes("PAYMENT")) return "確認客戶是否真的願意付錢";
  if (v.includes("INTERVIEW")) return "訪談真正承受問題的人";
  return value ? value.replaceAll("_", " ") : "目前先不要做任何事";
}

function reasonLabel(value?: string) {
  const v = String(value || "").toUpperCase();
  if (v.includes("BUYER_ACCESS_NOT_ESTABLISHED")) return "我們還不知道去哪裡找到真正會買的人。";
  if (v.includes("BUYER")) return "買家與預算還沒有被證明。";
  if (v.includes("TRUST") || v.includes("LEGITIMACY")) return "信任或資格門檻還沒有被解決。";
  return value ? value.replaceAll("_", " ") : "還缺一個會改變決策的關鍵答案。";
}

function distanceLabel(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (v.includes("CORE_OR_ADJACENT")) return "跟你現在能力很接近";
  if (v.includes("CORE")) return "就在你現有能力圈";
  if (v.includes("ADJACENT")) return "相鄰能力，補一點就能做";
  if (v.includes("DISTANT")) return "離你現在能力較遠";
  return "還不確定";
}

function trustLabel(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (v.includes("LOW_TO_MEDIUM")) return "低到中等";
  if (v === "LOW") return "低";
  if (v === "MEDIUM") return "中等";
  if (v === "HIGH") return "高";
  return "還不確定";
}

function blockerLabel(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (v.includes("BUYER_ACCESS")) return "找不找得到真正買家";
  if (v.includes("DOMAIN")) return "領域理解還不夠";
  if (v.includes("LEGITIMACY")) return "信任／資格還沒建立";
  if (v.includes("RIGHT_TO_WIN")) return "還沒有足夠理由相信你能贏";
  return value ? value.replaceAll("_", " ") : "沒有明確阻塞點";
}

export default function ThesisDetail() {
  const { id = "" } = useParams();
  const { data, isLoading, error } = useSignalForgeBrainThesis(id);
  if (isLoading) return <div className="max-w-[1080px] mx-auto space-y-3"><CardSkeleton /><CardSkeleton /></div>;
  if (error || !data || (data as { status?: string }).status === "NOT_FOUND") return <div className="max-w-[1080px] mx-auto rounded-2xl border border-danger/25 bg-bg-danger p-5 text-sm text-danger">這個商機方向目前讀不到。SignalForge 不會拿別的 Candidate 冒充。</div>;

  const addr = data.founder_addressability;
  const dims = addr?.dimensions || {};
  const next = data.best_next_action;
  const candidates = data.member_candidate_ids || [];
  const structuralDims = data.dimensions || {};
  const blocker = addr?.blocking_unknowns?.[0];
  const right = addr?.first_person_addressability_state || dims.right_to_win?.state || "UNKNOWN";
  const status = trackLabel(data.strategic_track);

  return (
    <div className="max-w-[1080px] mx-auto space-y-5 pb-12">
      <header className="pb-2">
        <Link to="/" className="inline-flex items-center gap-1 text-[11px] text-text-secondary hover:underline"><ArrowLeft size={11}/> 回今天的商機</Link>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${tone(data.strategic_track)}`}>{status}</span>
          {data.classification === "LEAD_USER_WEDGE" ? <span className="text-[10px] text-text-tertiary">先從重度使用者切入</span> : null}
        </div>
        <h1 className="mt-3 text-2xl md:text-[28px] leading-tight font-semibold tracking-[-0.02em] text-text-primary">{data.representative_title || data.representative_problem || data.thesis_id}</h1>
        {data.representative_problem ? <p className="mt-3 text-sm leading-6 text-text-secondary">{data.representative_problem}</p> : null}
      </header>

      <section className="rounded-3xl border border-success/20 bg-bg-success/35 p-6">
        <div className="flex items-center gap-2 text-[11px] font-semibold text-txt-success"><FlaskConical size={14}/> SignalForge 現在要你做什麼</div>
        <h2 className="mt-2 text-xl font-semibold text-text-primary">{actionLabel(next?.action)}</h2>
        <p className="mt-2 text-sm leading-6 text-text-secondary">{reasonLabel(next?.reason)}</p>
        <p className="mt-3 text-xs text-text-tertiary">這是下一個決策測試，不代表這個商機已成立。</p>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SimpleBox title="跟你能力距離" value={distanceLabel(addr?.learning_distance)} />
        <SimpleBox title="信任門檻" value={trustLabel(addr?.trust_burden)} />
        <SimpleBox title="目前最大缺口" value={blockerLabel(blocker)} />
        <SimpleBox title="你現在有沒有優勢" value={right === "SUPPORTED" ? "有初步優勢" : right === "REFUTED" ? "目前沒有" : "還不能證明"} />
      </section>

      <section className="rounded-2xl border border-border-secondary bg-bg-primary p-5">
        <div className="flex items-center gap-2"><ShieldCheck size={14} className="text-text-tertiary"/><h2 className="text-sm font-semibold text-text-primary">為什麼現在還不能直接做</h2></div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {Object.entries(dims).map(([key, row]) => <div key={key} className="rounded-xl bg-bg-secondary/40 p-3.5"><div className="flex items-center justify-between gap-3"><div className="text-[11px] font-medium text-text-primary">{dimensionLabel(key)}</div><span className={`rounded-full border px-2 py-0.5 text-[9px] font-medium ${tone(row.state)}`}>{stateLabel(row.state)}</span></div><div className="mt-2 text-[11px] leading-5 text-text-secondary">{row.basis}</div></div>)}
        </div>
      </section>

      <details className="rounded-2xl border border-border-secondary bg-bg-primary">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-medium text-text-secondary"><span>進階：結構判斷與原始證據</span><ChevronDown size={14} className="text-text-tertiary"/></summary>
        <div className="border-t border-border-secondary px-5 pb-5 pt-4">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{Object.entries(structuralDims).map(([key, row]) => <div key={key} className="flex items-center justify-between gap-2 rounded-xl border border-border-secondary bg-bg-secondary/25 px-3 py-2.5"><span className="text-[11px] text-text-secondary">{key.replaceAll("_", " ")}</span><span className={`rounded-full border px-2 py-0.5 text-[9px] ${tone(String(row?.state || "UNKNOWN"))}`}>{String(row?.state || "UNKNOWN")}</span></div>)}</div>
          <div className="mt-5 border-t border-border-secondary pt-4">
            <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-text-primary">支撐這個方向的 Candidate</h3><p className="mt-1 text-xs text-text-secondary">這些只是底層證據物件，不是商機排名。</p></div><Link to="/research" className="text-[11px] text-info hover:underline">看 AI 研究進度</Link></div>
            <div className="mt-3 flex flex-wrap gap-2">{candidates.length ? candidates.map((cid) => <Link key={cid} to={`/candidates/${cid}`} className="inline-flex items-center gap-1 rounded-lg border border-border-secondary bg-bg-secondary px-3 py-2 text-[11px] text-text-primary hover:bg-bg-primary">Candidate {cid}<ArrowRight size={11}/></Link>) : <span className="text-xs text-text-tertiary">目前沒有 member candidates。</span>}</div>
          </div>
          <div className="mt-5 flex items-center gap-2 text-[10px] leading-5 text-text-tertiary"><Sparkles size={11}/>{addr?.truth_boundary}</div>
        </div>
      </details>
    </div>
  );
}

function dimensionLabel(key: string) {
  const value = key.toUpperCase();
  if (value === "TASK_CAPABILITY") return "你做不做得出來";
  if (value === "DOMAIN_KNOWLEDGE") return "你懂不懂這個領域";
  if (value === "BUYER_ACCESS") return "你找不找得到買家";
  if (value === "LEGITIMACY") return "市場會不會相信你";
  if (value === "BRIDGEABILITY") return "缺的東西能不能快速補";
  if (value === "RIGHT_TO_WIN") return "你有沒有理由能贏";
  return key.replaceAll("_", " ");
}

function stateLabel(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (v === "SUPPORTED") return "有證據";
  if (v === "PARTIAL") return "部分成立";
  if (v === "INSUFFICIENT") return "證據不夠";
  if (v === "REFUTED") return "不成立";
  return "未知";
}

function SimpleBox({ title, value }: { title: string; value: string }) {
  return <div className="rounded-2xl border border-border-secondary bg-bg-primary p-4"><div className="text-[10px] text-text-tertiary">{title}</div><div className="mt-2 text-sm font-semibold text-text-primary">{value}</div></div>;
}
