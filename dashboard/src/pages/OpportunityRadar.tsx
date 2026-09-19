import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Circle,
  Clock3,
  Eye,
  FlaskConical,
  Gauge,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import {
  useSignalForgeDaily,
  useSignalForgeStrategicPortfolio,
  useSignalForgeOperatingQueue,
  useSignalForgeMarketActions,
  useRegisterSignalForgeMarketAction,
  useCompleteSignalForgeMarketAction,
  useSignalForgeValidationExperiments,
  useRegisterSignalForgeValidationExperiment,
  useRecordSignalForgeValidationResult,
  useTriggerSignalForge,
  useUpdateProblemCandidateStatus,
} from "../api/hooks";
import { CardSkeleton } from "../components/common/Skeleton";
import type {
  SignalForgeMarketActionSuggestion,
  SignalForgeOperatingQueueItem,
  SignalForgeStrategicThesis,
} from "../api/client";

const FX = Number(import.meta.env.VITE_USD_TWD_RATE || 31.83);

type RadarTab = "priority" | "machine" | "all";
type StageState = "SUPPORTED" | "REFUTED" | "INSUFFICIENT" | "UNKNOWN" | string;

const verdictMeta: Record<string, { label: string; description: string; tone: string; dot: string }> = {
  VALIDATE: {
    label: "需要你驗證",
    description: "證據已足夠，下一步應接觸真實市場",
    tone: "bg-bg-success text-txt-success border-success/25",
    dot: "bg-success",
  },
  INVESTIGATE: {
    label: "值得深入",
    description: "商機正在成形，值得你花時間理解",
    tone: "bg-bg-info text-txt-info border-info/25",
    dot: "bg-info",
  },
  WATCH: {
    label: "AI 研究中",
    description: "先讓 SignalForge 繼續補證據",
    tone: "bg-bg-warning text-txt-warning border-warning/25",
    dot: "bg-warning",
  },
  PARK: {
    label: "先放著",
    description: "目前不值得投入更多研究資源",
    tone: "bg-bg-secondary text-text-secondary border-border-primary",
    dot: "bg-text-tertiary",
  },
  IGNORE: {
    label: "略過",
    description: "目前證據不支持繼續投入",
    tone: "bg-bg-secondary text-text-secondary border-border-primary",
    dot: "bg-text-tertiary",
  },
};

const maturityStages = [
  { code: "C02", label: "問題" },
  { code: "C03", label: "痛點" },
  { code: "C05", label: "買家" },
  { code: "C06", label: "現有方案" },
  { code: "C07", label: "缺口" },
  { code: "MARKET", label: "市場" },
  { code: "C09", label: "執行" },
] as const;

function nt(usd?: number | null) {
  if (usd == null) return "—";
  const twd = usd * FX;
  return twd < 1 ? `NT$${twd.toFixed(2)}` : `NT$${twd.toFixed(0)}`;
}

function ageText(hours?: number | null) {
  if (hours == null) return "尚未更新";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} 分鐘前`;
  return `${hours.toFixed(1)} 小時前`;
}

function gateCopy(raw?: string | null) {
  const value = String(raw || "").toUpperCase();
  if (value.includes("UNRESOLVED_GAP") || value.includes("C07")) return "用了現有方案之後，問題到底還剩多少？";
  if (value.includes("CURRENT_SOLUTION") || value.includes("C06")) return "現在大家怎麼解？現有方案到底夠不夠好？";
  if (value.includes("BUYER_REALITY_RECHECK")) return "買家訊號有了，但還不夠穩，需要再確認。";
  if (value.includes("BUYER_REALITY") || value.includes("C05")) return "誰真的承受這個問題，而且有能力花錢解決？";
  if (value.includes("PAIN_MATERIALITY") || value.includes("C03")) return "這個問題到底痛不痛，嚴重到值得付錢嗎？";
  if (value.includes("PROBLEM_REALITY") || value.includes("C02")) return "這是不是反覆存在的真問題，而不是單一抱怨？";
  if (value.includes("DIFFERENTIATION") || value.includes("C08")) return "我們能不能做出明顯更好的解法？";
  if (value.includes("DISTRIBUTION") || value.includes("C10")) return "要去哪裡找到這群客戶？";
  if (value.includes("ECONOMIC") || value.includes("WTP") || value.includes("C11")) return "客戶願不願意付錢，而且價格是否成立？";
  if (value.includes("WINDOW") || value.includes("C12")) return "現在是不是切入這個市場的好時機？";
  if (value.includes("COMPETITION") || value.includes("C13")) return "競爭這麼多，我們還有沒有生存空間？";
  if (value.includes("SWITCH") || value.includes("C14")) return "客戶有沒有足夠理由從現有方案換過來？";
  return raw || "SignalForge 還在確認下一個最重要的未知。";
}

function humanizeMachineAction(raw?: string | null) {
  const text = String(raw || "").trim();
  const lower = text.toLowerCase();
  if (!text) return "繼續尋找能改變判斷的新證據";
  if (lower.includes("verify the gap persists")) return "確認使用現有方案後，問題是否仍持續存在";
  if (lower.includes("solution complaints") || lower.includes("failures") || lower.includes("workarounds")) return "搜尋現有方案的失敗、抱怨與替代做法";
  if (lower.includes("named buyer") || lower.includes("buyer")) return "補強具名買家、責任歸屬與預算訊號";
  if (lower.includes("material")) return "尋找能證明損失、延誤或營運影響的直接證據";
  if (lower.includes("competition")) return "建立競爭版圖，確認是否還有可生存的切入點";
  if (lower.includes("distribution")) return "尋找實際可觸及買家的取得管道";
  if (lower.includes("price") || lower.includes("wtp") || lower.includes("econom")) return "準備價格與付費意願驗證";
  return text;
}

function humanizeWhy(raw: string) {
  const text = raw.trim();
  const lower = text.toLowerCase();
  if (lower.includes("named buyer") || lower.includes("budget signal")) return "已找到具名買家或預算訊號";
  if (lower.includes("solution-market")) return "現有方案與市場訊號已出現";
  if (lower.includes("timing")) return "時機訊號正在形成";
  if (lower.includes("problem-search coverage saturated")) return "問題搜尋已接近飽和，不只是單一來源";
  if (lower.includes("problem")) return "問題訊號已被多來源觀察到";
  return text;
}

function humanizeActionType(raw?: string | null) {
  const value = String(raw || "").toUpperCase();
  if (value === "IDENTIFY_REACHABLE_BUYER_CHANNEL") return "找出你真的接觸得到的買家管道";
  if (value.includes("BUYER") && value.includes("CHANNEL")) return "找出你真的接觸得到的買家管道";
  if (value.includes("WTP") || value.includes("PAYMENT") || value.includes("PRICE")) return "確認客戶是否真的願意付錢";
  if (value.includes("OUTREACH")) return "直接接觸潛在買家測反應";
  if (value.includes("PROTOTYPE")) return "用最小原型測真實使用意願";
  if (value.includes("INTERVIEW")) return "訪談真正承受問題的人";
  if (value.includes("FOUNDER")) return "補一個只有你能確認的市場未知";
  return raw ? raw.replaceAll("_", " ") : "補一個真人市場未知";
}

function humanizeReason(raw?: string | null) {
  const value = String(raw || "").toUpperCase();
  if (value.includes("BUYER_ACCESS_NOT_ESTABLISHED")) return "我們還不知道去哪裡找到真正會買的人。";
  if (value.includes("BUYER")) return "買家是誰、誰有預算，現在還沒有被證明。";
  if (value.includes("WTP") || value.includes("PAYMENT")) return "有人覺得痛，不代表有人願意付錢。";
  if (value.includes("CHANNEL") || value.includes("DISTRIBUTION")) return "我們還沒有可重複觸及目標買家的管道。";
  if (value.includes("TRUST") || value.includes("LEGITIMACY")) return "這個市場需要的信任或資格，目前還沒有建立。";
  return raw ? raw.replaceAll("_", " ") : "還缺一個會改變是否值得做的關鍵答案。";
}

function humanizeSignal(raw?: string | null, kind: "success" | "failure" = "success") {
  const value = String(raw || "").trim();
  const lower = value.toLowerCase();
  if (!value) return kind === "success" ? "取得足以改變下一步決策的真實證據" : "限定嘗試後仍沒有取得支持訊號";
  if (lower.includes("repeatable channel") && lower.includes("qualified target buyers")) {
    return kind === "success" ? "至少找到 1 個可重複觸及合格買家的管道" : "限定嘗試後仍找不到可觸及的合格買家管道";
  }
  if (lower.includes("no reachable qualified buyer channel")) return "限定嘗試後仍找不到可觸及的合格買家管道";
  return value;
}

function trackCopy(track?: string | null) {
  const value = String(track || "NEITHER").toUpperCase();
  if (value === "BOTH") return { label: "最值得看", tone: "border-success/25 bg-bg-success text-txt-success", description: "同時有結構性上升空間，也能快速取得市場答案" };
  if (value === "ZIP2_STRUCTURAL") return { label: "結構性機會", tone: "border-info/25 bg-bg-info text-txt-info", description: "值得長線追蹤的大結構變化" };
  if (value === "FAST_VALIDATION") return { label: "可快速驗證", tone: "border-warning/25 bg-bg-warning text-txt-warning", description: "適合用低成本市場測試快速判生死" };
  return { label: "還不能下注", tone: "border-border-secondary bg-bg-secondary text-text-secondary", description: "值得保留，但證據還不足以投入產品" };
}

function distanceCopy(raw?: string | null) {
  const value = String(raw || "UNKNOWN").toUpperCase();
  if (value.includes("CORE_OR_ADJACENT")) return "跟你現在能力很接近";
  if (value.includes("CORE")) return "就在你現有能力圈";
  if (value.includes("ADJACENT")) return "相鄰能力，補一點就能做";
  if (value.includes("DISTANT")) return "離你現在能力較遠";
  return "還不確定";
}

function trustCopy(raw?: string | null) {
  const value = String(raw || "UNKNOWN").toUpperCase();
  if (value.includes("LOW_TO_MEDIUM")) return "低到中等";
  if (value === "LOW") return "低";
  if (value === "MEDIUM") return "中等";
  if (value === "HIGH") return "高";
  return "還不確定";
}

function blockingUnknownCopy(raw?: string | null) {
  const value = String(raw || "UNKNOWN").toUpperCase();
  if (value.includes("BUYER_ACCESS")) return "找不找得到真正買家";
  if (value.includes("DOMAIN")) return "領域理解還不夠";
  if (value.includes("LEGITIMACY")) return "信任／資格還沒建立";
  if (value.includes("RIGHT_TO_WIN")) return "還沒有足夠理由相信你能贏";
  return raw ? raw.replaceAll("_", " ") : "還沒有明確阻塞點";
}

function boundaryCopy(raw?: string | null) {
  const value = String(raw || "").toUpperCase();
  if (value.includes("FOUNDER_ACTION_NOW")) return "現在需要你真人驗證";
  if (value.includes("PREBUILT")) return "驗證計畫已備妥，等待證據過關";
  if (value.includes("MACHINE_FIRST")) return "先由 SignalForge 自動研究";
  return raw || "系統持續研究";
}

function aggregateMarketState(claims: Record<string, string>) {
  const states = ["C10", "C11", "C12", "C13", "C14"].map((code) => claims[code] || "UNKNOWN");
  if (states.some((state) => state === "REFUTED")) return "REFUTED";
  if (states.every((state) => state === "SUPPORTED")) return "SUPPORTED";
  if (states.some((state) => state === "SUPPORTED")) return "INSUFFICIENT";
  if (states.some((state) => state === "INSUFFICIENT")) return "INSUFFICIENT";
  return "UNKNOWN";
}

function stageState(claims: Record<string, string>, code: string): StageState {
  return code === "MARKET" ? aggregateMarketState(claims) : claims[code] || "UNKNOWN";
}

function stageVisual(state: StageState) {
  if (state === "SUPPORTED") return { dot: "bg-success", text: "text-txt-success", ring: "border-success/30", icon: <Check size={11} /> };
  if (state === "REFUTED") return { dot: "bg-danger", text: "text-danger", ring: "border-danger/30", icon: <X size={11} /> };
  if (state === "INSUFFICIENT") return { dot: "bg-warning", text: "text-txt-warning", ring: "border-warning/25", icon: <Circle size={8} fill="currentColor" /> };
  return { dot: "bg-text-tertiary", text: "text-text-tertiary", ring: "border-border-primary", icon: <Circle size={8} /> };
}

function isFounderPriority(verdict: string) {
  return verdict === "VALIDATE" || verdict === "INVESTIGATE";
}

function queueCount(queue: import("../api/client").SignalForgeOperatingQueue | undefined, key: keyof import("../api/client").SignalForgeOperatingQueue) {
  const explicit = queue?.counts?.[String(key)];
  if (typeof explicit === "number") return explicit;
  const value = queue?.[key];
  return Array.isArray(value) ? value.length : 0;
}

export default function OpportunityRadar() {
  const { data, isLoading, error } = useSignalForgeDaily();
  const { data: strategic, isLoading: strategicLoading } = useSignalForgeStrategicPortfolio();
  const { data: operatingLoop } = useSignalForgeOperatingQueue();
  const { data: marketActions } = useSignalForgeMarketActions();
  const { data: validationExperiments } = useSignalForgeValidationExperiments();
  const registerAction = useRegisterSignalForgeMarketAction();
  const trigger = useTriggerSignalForge();
  const update = useUpdateProblemCandidateStatus();
  const [tab, setTab] = useState<RadarTab>("priority");

  const cards = data?.cards || [];
  const priorityCards = useMemo(() => cards.filter((card) => isFounderPriority(card.verdict)), [cards]);
  const machineCards = useMemo(() => cards.filter((card) => !isFounderPriority(card.verdict)), [cards]);
  const visibleCards = tab === "priority" ? priorityCards : tab === "machine" ? machineCards : cards;

  if (isLoading) {
    return <div className="max-w-[1180px] mx-auto space-y-4"><CardSkeleton /><CardSkeleton /><CardSkeleton /></div>;
  }

  if (error || !data) {
    return (
      <div className="max-w-[1180px] mx-auto rounded-2xl border border-danger/25 bg-bg-danger px-5 py-4 text-sm text-danger">
        SignalForge 現在讀不到決策資料。先不要相信舊畫面，也不用自己查 log。
      </div>
    );
  }

  const runtime = data.runtime;
  const qualityOk = data.quality?.status === "PASS";
  const spend = data.spending;
  const sourceHealth = runtime?.last_cycle?.source_health;
  const recurrence = runtime?.last_cycle?.recurrence;
  const soloGate = data.solo_founder_gate || { ready: cards.length, watch: 0, research_themes_parked: 0, empty_is_valid: true };
  const queue = operatingLoop?.operating_queue;
  const suggestedActions = marketActions?.suggested?.items || operatingLoop?.market_action_queue?.items || [];
  const primaryAction = suggestedActions[0];
  const strategicItems = strategic?.items || [];
  const activeTracks = strategic?.strategic_summary?.strategic_track_counts || {};
  const promisingCount = Number(activeTracks.BOTH || 0) + Number(activeTracks.ZIP2_STRUCTURAL || 0) + Number(activeTracks.FAST_VALIDATION || 0);
  const machineCount = queueCount(queue, "machine_research");
  const waitingCount = queueCount(queue, "waiting");
  const parkedCount = queueCount(queue, "parked") + queueCount(queue, "monitor");
  const founderTaskCount = suggestedActions.length;
  const openMarketActions = (marketActions?.registry?.rows || []).filter((x) => ["REGISTERED", "RUNNING"].includes(String(x.status || "").toUpperCase()));
  const pendingAtomic = (validationExperiments?.rows || []).filter((x) => String(x.status || "").toUpperCase() === "PENDING");

  const headline = primaryAction
    ? `今天有 ${founderTaskCount} 件事值得你親自處理`
    : promisingCount > 0
      ? `目前有 ${promisingCount} 個方向值得往下一步推`
      : strategicItems.length > 0
        ? "目前還沒有成熟到值得下注的商機"
        : "今天沒有值得你投入的商機";

  const headlineBody = primaryAction
    ? "現在最有價值的不是再寫產品，也不是再查技術，而是補一個只有真實市場能回答的問題。"
    : promisingCount > 0
      ? "SignalForge 已把雜訊收斂成少量方向。先看下面的下一步，不用碰底層研究佇列。"
      : strategicItems.length > 0
        ? `保留 ${strategicItems.length} 個方向繼續觀察；其餘研究交給 AI 自己跑。`
        : "沒有就是沒有。SignalForge 不會為了讓首頁好看硬湊商機。";

  return (
    <div className="max-w-[1180px] mx-auto pb-12">
      <section className="pt-1 pb-5">
        <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-5">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-[0.12em] uppercase text-text-tertiary">
              <Sparkles size={13} className="text-success" /> 今日商機
            </div>
            <h1 className="mt-2 text-[30px] leading-tight font-semibold tracking-[-0.025em] text-text-primary">你今天要不要對任何商機出手？</h1>
            <p className="mt-2 text-sm leading-6 text-text-secondary">首頁只回答三件事：有沒有值得做、為什麼、今天要做什麼。其餘工程細節全部收起來。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SystemPill icon={<ShieldCheck size={13} />} strong={qualityOk} label={qualityOk ? "系統正常" : "系統異常"} />
            <SystemPill icon={<Clock3 size={13} />} strong={Boolean(runtime?.fresh)} label={runtime?.fresh ? `資料 ${ageText(runtime?.data_age_hours)}` : "資料過期"} />
            <SystemPill icon={<Gauge size={13} />} label={`AI 花費 ${nt(spend?.total_spent_usd)}`} />
            <button
              type="button"
              disabled={trigger.isPending || runtime?.running}
              onClick={() => trigger.mutate()}
              className="inline-flex items-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3.5 py-2 text-xs font-medium text-text-primary hover:bg-bg-secondary focus:outline-none focus:ring-2 focus:ring-info/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw size={13} className={trigger.isPending || runtime?.running ? "animate-spin" : ""} />
              {runtime?.running ? "AI 正在研究" : "更新一次"}
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-border-secondary bg-bg-primary p-6 md:p-7 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
          <div className="max-w-3xl">
            <div className="text-[11px] font-semibold text-success">SIGNALFORGE 結論</div>
            <h2 className="mt-2 text-2xl md:text-[28px] leading-tight font-semibold tracking-[-0.02em] text-text-primary">{headline}</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-text-secondary">{headlineBody}</p>
          </div>
          <div className="grid min-w-[280px] grid-cols-3 gap-2">
            <SummaryNumber label="待你處理" value={founderTaskCount} emphasis={founderTaskCount > 0} />
            <SummaryNumber label="AI 自己查" value={machineCount} />
            <SummaryNumber label="值得往下推" value={promisingCount} />
          </div>
        </div>
      </section>

      {primaryAction ? (
        <section id="today-action" className="mt-5 rounded-3xl border border-success/25 bg-bg-success/45 p-6 md:p-7">
          <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
            <div className="max-w-3xl">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-txt-success"><FlaskConical size={14} /> 今天只做這件事</div>
              <h2 className="mt-2 text-xl md:text-2xl font-semibold tracking-[-0.02em] text-text-primary">{humanizeActionType(primaryAction.action_type)}</h2>
              <p className="mt-2 text-sm leading-6 text-text-secondary">{humanizeReason(primaryAction.reason)}</p>

              <div className="mt-5 grid gap-3 md:grid-cols-3">
                <PlainFact label="你要做什麼" value={actionInstruction(primaryAction)} />
                <PlainFact label="做到什麼算有進展" value={humanizeSignal(primaryAction.template?.success_signal, "success")} />
                <PlainFact label="什麼結果代表先放棄" value={humanizeSignal(primaryAction.template?.failure_signal, "failure")} />
              </div>

              <div className="mt-4 text-xs leading-5 text-text-secondary">
                這不是「證明商機成立」。這只是下一個最便宜、最能改變決策的測試。
              </div>
            </div>
            <div className="flex shrink-0 flex-col gap-2 lg:w-[190px]">
              <button
                type="button"
                disabled={Boolean(primaryAction.registered_action_id) || registerAction.isPending}
                onClick={() => registerAction.mutate({ thesis_id: primaryAction.thesis_id, action_type: primaryAction.action_type, sample_target: primaryAction.template?.default_sample })}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-text-primary px-4 py-3 text-xs font-semibold text-bg-primary hover:opacity-90 disabled:opacity-50"
              >
                {primaryAction.registered_action_id ? "已開始驗證" : "開始這個驗證"} <ArrowRight size={13} />
              </button>
              <Link to={`/theses/${encodeURIComponent(primaryAction.thesis_id)}`} className="inline-flex items-center justify-center gap-2 rounded-xl border border-border-primary bg-bg-primary/70 px-4 py-2.5 text-xs font-medium text-text-secondary hover:bg-bg-primary">
                看完整判斷
              </Link>
            </div>
          </div>
        </section>
      ) : null}

      {openMarketActions.length > 0 ? (
        <section className="mt-5 rounded-3xl border border-border-secondary bg-bg-primary p-5 md:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-text-primary">你正在做的真人驗證</h2>
              <p className="mt-1 text-xs text-text-secondary">做完再回來記結果。沒有真實觀察，就不會被算成市場證據。</p>
            </div>
            <span className="text-xs text-text-tertiary">{openMarketActions.length} 個進行中</span>
          </div>
          <div className="mt-4 space-y-3">
            {openMarketActions.slice(0, 8).map((record) => <MarketActionExecutionCard key={record.action_id} record={record} />)}
          </div>
        </section>
      ) : null}

      <section className="mt-7">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">值得保留的方向</h2>
            <p className="mt-1 text-xs text-text-secondary">這裡是「還值得想」，不是「已經值得做」。</p>
          </div>
          <div className="text-xs text-text-tertiary">目前 {strategicItems.length} 個方向 · 真正成熟 {promisingCount} 個</div>
        </div>

        {strategicLoading ? <CardSkeleton /> : strategicItems.length === 0 ? (
          <div className="rounded-2xl border border-border-secondary bg-bg-primary px-6 py-9 text-center">
            <Sparkles size={20} className="mx-auto text-text-tertiary" />
            <div className="mt-3 text-sm font-medium text-text-primary">目前沒有值得保留的方向</div>
            <div className="mt-1 text-xs text-text-secondary">這是正常答案，不需要為了湊數硬找商機。</div>
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {strategicItems.slice(0, 6).map((thesis) => <FounderThesisCard key={thesis.thesis_id} thesis={thesis} />)}
          </div>
        )}
      </section>

      <section className="mt-7 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-2xl border border-border-secondary bg-bg-primary p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-text-primary">AI 自己在忙什麼</h2>
              <p className="mt-1 text-xs leading-5 text-text-secondary">這些不用你處理。只有當它真的找到值得你出手的下一步，才會被拉到上面。</p>
            </div>
            <span className="rounded-full bg-bg-secondary px-2.5 py-1 text-xs font-medium text-text-secondary">{machineCount} 個研究中</span>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <PlainStat label="AI 研究" value={machineCount} />
            <PlainStat label="等新證據" value={waitingCount} />
            <PlainStat label="先放著" value={parkedCount} />
          </div>
          {(queue?.machine_research || []).length > 0 ? (
            <details className="mt-4 rounded-xl border border-border-secondary bg-bg-secondary/25 px-4 py-3">
              <summary className="cursor-pointer list-none text-xs font-medium text-text-secondary">想看 AI 正在查哪些東西</summary>
              <div className="mt-3 space-y-2 border-t border-border-secondary pt-3">
                {(queue?.machine_research || []).slice(0, 5).map((item, index) => (
                  <div key={`${item.case_id || index}`} className="text-xs leading-5 text-text-secondary">
                    <span className="font-medium text-text-primary">{item.title || `Case ${item.case_id || "?"}`}</span>
                    <span className="text-text-tertiary"> — {humanizeMachineAction(item.action || item.current_gate)}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </div>

        <div className="rounded-2xl border border-border-secondary bg-bg-primary p-5">
          <h2 className="text-base font-semibold text-text-primary">現在的真實狀態</h2>
          <div className="mt-4 space-y-3">
            <StatusRow label="值得往下一步推" value={promisingCount > 0 ? `${promisingCount} 個` : "0 個"} good={promisingCount > 0} />
            <StatusRow label="需要你補市場答案" value={`${founderTaskCount} 個`} good={founderTaskCount > 0} />
            <StatusRow label="市場校準" value={data.calibration?.status || "UNVALIDATED"} />
            <StatusRow label="系統資料" value={runtime?.fresh ? "最新" : "需要更新"} good={Boolean(runtime?.fresh)} />
          </div>
          <p className="mt-4 text-[11px] leading-5 text-text-tertiary">工程 PASS 不等於商機成立；真人驗證也不會自動把未知改成真。</p>
        </div>
      </section>

      {(data.claim_validation_ready || []).length > 0 || pendingAtomic.length > 0 ? (
        <section className="mt-7 rounded-2xl border border-info/20 bg-bg-info/25 p-5">
          <div>
            <h2 className="text-base font-semibold text-text-primary">需要正式記錄的市場實驗</h2>
            <p className="mt-1 text-xs text-text-secondary">只有這裡的預先註冊實驗，才可能在完成後成為 C10 / C11 / C14 的市場證據。</p>
          </div>
          {(data.claim_validation_ready || []).length > 0 ? (
            <div className="mt-4 grid gap-3 xl:grid-cols-2">
              {(data.claim_validation_ready || []).slice(0, 8).map((ready) => (
                <ClaimValidationReadyCard key={ready.case_id} ready={ready} pending={validationExperiments?.rows || []} />
              ))}
            </div>
          ) : null}
          {pendingAtomic.length > 0 ? (
            <div className="mt-4 space-y-3 border-t border-border-secondary pt-4">
              {pendingAtomic.slice(0, 8).map((record) => <ClaimValidationExecutionCard key={record.experiment_id} record={record} />)}
            </div>
          ) : null}
        </section>
      ) : null}

      <details className="mt-8 rounded-2xl border border-border-secondary bg-bg-primary">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 text-sm font-medium text-text-secondary">
          <span>進階：看系統路由、候選案例與證據細節</span>
          <ChevronDown size={15} className="text-text-tertiary" />
        </summary>
        <div className="border-t border-border-secondary px-5 pb-6 pt-5">
          <div className="mb-5">
            <div className="text-[10px] uppercase tracking-[0.12em] text-text-tertiary">系統工作路由</div>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-6">
              <OperatingLane title="AI 研究" count={queueCount(queue, "machine_research")} items={queue?.machine_research || []} />
              <OperatingLane title="AI backlog" count={queueCount(queue, "machine_research_backlog")} items={queue?.machine_research_backlog || []} />
              <OperatingLane title="市場行動" count={queueCount(queue, "market_action")} items={queue?.market_action || []} emphasis />
              <OperatingLane title="Founder 補答案" count={queueCount(queue, "founder_discovery")} items={queue?.founder_discovery || []} emphasis />
              <OperatingLane title="等待" count={queueCount(queue, "waiting")} items={queue?.waiting || []} />
              <OperatingLane title="停放 / 觀察" count={parkedCount} items={[...(queue?.parked || []), ...(queue?.monitor || [])]} />
            </div>
          </div>

          <div className="border-t border-border-secondary pt-5">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-4">
              <div>
                <h3 className="text-sm font-semibold text-text-primary">Candidate evidence queue</h3>
                <p className="mt-1 text-[11px] text-text-secondary">這是證據 drill-down，不是商機排行榜。</p>
              </div>
              <div className="inline-flex self-start rounded-xl border border-border-primary bg-bg-primary p-1" role="tablist" aria-label="商機篩選">
                <RadarTabButton active={tab === "priority"} onClick={() => setTab("priority")}>值得看 {priorityCards.length}</RadarTabButton>
                <RadarTabButton active={tab === "machine"} onClick={() => setTab("machine")}>AI 研究 {machineCards.length}</RadarTabButton>
                <RadarTabButton active={tab === "all"} onClick={() => setTab("all")}>全部 {cards.length}</RadarTabButton>
              </div>
            </div>

            {visibleCards.length === 0 ? (
              <div className="rounded-2xl border border-border-secondary bg-bg-secondary/25 px-6 py-9 text-center">
                <Sparkles size={20} className="mx-auto text-text-tertiary" />
                <div className="mt-3 text-sm font-medium text-text-primary">這個篩選目前沒有案例</div>
              </div>
            ) : (
              <div className="space-y-3">
                {visibleCards.map((card, index) => {
                  const meta = verdictMeta[card.verdict] || verdictMeta.WATCH;
                  const candidateId = card.candidate_id;
                  const nextEvidence = card.next_evidence_queries?.[0];
                  const why = (card.why_now || []).map(humanizeWhy).filter(Boolean);
                  const buyers = card.buyer_organizations || [];

                  return (
                    <article key={card.case_id} className="rounded-2xl border border-border-secondary bg-bg-primary p-5">
                      <div className="flex flex-col xl:flex-row gap-5">
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[11px] font-mono text-text-tertiary">#{index + 1}</span>
                            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${meta.tone}`}>
                              <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />{meta.label}
                            </span>
                            <span className="text-[11px] text-text-tertiary">Case {card.case_id}</span>
                          </div>
                          <h4 className="mt-3 text-base font-semibold text-text-primary">{card.title}</h4>
                          <div className="mt-4 grid gap-3 lg:grid-cols-3">
                            <FounderBlock eyebrow="為什麼值得看" icon={<Sparkles size={14} />} emphasis>{why.length ? why.slice(0, 3).join(" · ") : card.decision_reason || "目前正在累積直接證據。"}</FounderBlock>
                            <FounderBlock eyebrow="目前卡在" icon={<Search size={14} />}>{gateCopy(card.biggest_unknown)}</FounderBlock>
                            <FounderBlock eyebrow="AI 正在做" icon={<FlaskConical size={14} />}>{humanizeMachineAction(card.machine_action)}</FounderBlock>
                          </div>
                          <MaturityRail claims={card.claims || {}} />
                          {buyers.length ? <div className="mt-4 text-[11px] text-text-secondary">具名買家：{buyers.slice(0, 4).join(" · ")}{buyers.length > 4 ? ` +${buyers.length - 4}` : ""}</div> : null}
                          <details className="mt-4 rounded-xl border border-border-secondary bg-bg-secondary/25 px-3.5 py-3">
                            <summary className="cursor-pointer list-none text-[11px] font-medium text-text-secondary">看下一個關鍵證據與 C01–C14</summary>
                            <div className="pt-3 mt-3 border-t border-border-secondary space-y-3">
                              <div className="text-[11px] leading-5 text-text-secondary"><span className="font-medium text-text-primary">下一個關鍵證據：</span>{nextEvidence?.query || "目前沒有額外 research query。"}</div>
                              <div className="flex flex-wrap gap-1.5">{Object.entries(card.claims || {}).map(([code, state]) => <span key={code} className="rounded-md border border-border-secondary bg-bg-primary px-2 py-1 text-[10px] text-text-secondary">{code} {state}</span>)}</div>
                              <div className="text-[10px] text-text-tertiary">驗證邊界：{boundaryCopy(card.market_validation_boundary)}</div>
                            </div>
                          </details>
                        </div>
                        <div className="xl:w-[160px] shrink-0 flex xl:flex-col gap-2">
                          {candidateId ? <Link to={`/candidates/${candidateId}`} className="inline-flex flex-1 xl:flex-none items-center justify-center gap-2 rounded-xl bg-text-primary px-3 py-2.5 text-[11px] font-medium text-bg-primary">看證據 <ArrowRight size={13} /></Link> : null}
                          {candidateId ? <button type="button" onClick={() => update.mutate({ id: candidateId, status: "watch" })} className="inline-flex flex-1 xl:flex-none items-center justify-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-secondary hover:bg-bg-secondary"><Eye size={13} /> 繼續追蹤</button> : null}
                          {candidateId ? <button type="button" onClick={() => update.mutate({ id: candidateId, status: "dismissed" })} className="inline-flex flex-1 xl:flex-none items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] text-text-tertiary hover:bg-bg-danger hover:text-danger"><X size={13} /> 暫時略過</button> : null}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </details>

      <section className="mt-6 border-t border-border-secondary pt-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-[10px] text-text-tertiary">
          <span>上次成功：{runtime?.last_success_at ? new Date(runtime.last_success_at).toLocaleString() : "尚無"}</span>
          <span>來源：{sourceHealth?.groups_passed?.length ? sourceHealth.groups_passed.join(", ") : "使用既有新鮮資料"}</span>
          <span>問題重複驗證：{recurrence?.supported ?? 0} supported · {recurrence?.coverage_gap ?? 0} gaps</span>
          <span>市場預測可信度：{data.calibration?.status || "UNVALIDATED"}</span>
          <span>舊 Candidate gate：{soloGate.ready} ready · {soloGate.watch} watch</span>
          {runtime?.last_error ? <span className="text-danger">最近錯誤：{runtime.last_error}</span> : null}
        </div>
      </section>
    </div>
  );
}

function actionInstruction(action: SignalForgeMarketActionSuggestion) {
  const sample = action.template?.default_sample;
  const type = String(action.action_type || "").toUpperCase();
  if (type.includes("BUYER") && type.includes("CHANNEL")) return `列出並實際探測 ${sample || 10} 個你接觸得到的潛在買家／管道`;
  if (type.includes("WTP") || type.includes("PAYMENT")) return `用 ${sample || 10} 個真實對象測付費或承諾行為`;
  if (type.includes("INTERVIEW")) return `找 ${sample || 10} 個真正承受問題的人做短訪談`;
  return `完成一個 ${sample ? `${sample} 個樣本的` : "小樣本"}真人驗證`;
}

function SummaryNumber({ label, value, emphasis = false }: { label: string; value: number; emphasis?: boolean }) {
  return <div className={`rounded-2xl border px-3 py-3 text-center ${emphasis ? "border-success/25 bg-bg-success/55" : "border-border-secondary bg-bg-secondary/35"}`}>
    <div className={`text-xl font-semibold ${emphasis ? "text-txt-success" : "text-text-primary"}`}>{value}</div>
    <div className="mt-1 text-[10px] text-text-tertiary">{label}</div>
  </div>;
}

function PlainFact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl border border-success/15 bg-bg-primary/70 p-4">
    <div className="text-[10px] font-medium text-text-tertiary">{label}</div>
    <div className="mt-2 text-xs leading-5 font-medium text-text-primary">{value}</div>
  </div>;
}

function PlainStat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl bg-bg-secondary/55 px-3 py-3 text-center">
    <div className="text-lg font-semibold text-text-primary">{value}</div>
    <div className="mt-1 text-[10px] text-text-tertiary">{label}</div>
  </div>;
}

function StatusRow({ label, value, good = false }: { label: string; value: string; good?: boolean }) {
  return <div className="flex items-center justify-between gap-4 border-b border-border-secondary pb-2.5 last:border-b-0 last:pb-0">
    <span className="text-xs text-text-secondary">{label}</span>
    <span className={`text-xs font-medium ${good ? "text-txt-success" : "text-text-primary"}`}>{value}</span>
  </div>;
}

function FounderThesisCard({ thesis }: { thesis: SignalForgeStrategicThesis }) {
  const meta = trackCopy(thesis.strategic_track);
  const addr = thesis.founder_addressability;
  const blocking = addr?.blocking_unknowns?.[0];
  const candidateId = thesis.member_candidate_ids?.[0];
  const capability = addr?.dimensions?.task_capability?.state;
  const title = thesis.representative_title || thesis.representative_problem || thesis.thesis_id;

  return <article className="rounded-2xl border border-border-secondary bg-bg-primary p-5">
    <div className="flex items-center justify-between gap-3">
      <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${meta.tone}`}>{meta.label}</span>
      <span className="text-[10px] text-text-tertiary">{thesis.classification === "LEAD_USER_WEDGE" ? "先從重度使用者切入" : thesis.classification || "保留觀察"}</span>
    </div>
    <h3 className="mt-3 line-clamp-2 text-[17px] leading-6 font-semibold tracking-[-0.01em] text-text-primary">{title}</h3>
    <p className="mt-2 text-xs leading-5 text-text-secondary">{meta.description}</p>

    <div className="mt-4 grid gap-2 sm:grid-cols-2">
      <PlainMini label="跟你的能力距離" value={distanceCopy(addr?.learning_distance)} />
      <PlainMini label="信任門檻" value={trustCopy(addr?.trust_burden)} />
      <PlainMini label="目前最大缺口" value={blockingUnknownCopy(blocking)} />
      <PlainMini label="你的技術執行能力" value={capability === "SUPPORTED" ? "已有基礎" : capability === "REFUTED" ? "目前不足" : "還沒證明"} />
    </div>

    <div className="mt-4 rounded-xl border border-border-secondary bg-bg-secondary/30 px-3.5 py-3">
      <div className="text-[10px] font-medium text-text-tertiary">下一步</div>
      <div className="mt-1 text-xs font-medium leading-5 text-text-primary">{humanizeActionType(thesis.best_next_action?.action)}</div>
      <div className="mt-1 text-[11px] leading-5 text-text-secondary">{humanizeReason(thesis.best_next_action?.reason)}</div>
    </div>

    <div className="mt-4 flex items-center justify-end gap-3">
      {candidateId ? <Link to={`/candidates/${candidateId}`} className="text-[11px] text-text-secondary hover:underline">看證據</Link> : null}
      <Link to={`/theses/${encodeURIComponent(thesis.thesis_id)}`} className="inline-flex items-center gap-1 text-[11px] font-medium text-info hover:underline">看完整判斷 <ArrowRight size={11} /></Link>
    </div>
  </article>;
}

function PlainMini({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-bg-secondary/45 px-3 py-3">
    <div className="text-[9px] text-text-tertiary">{label}</div>
    <div className="mt-1 text-[11px] font-medium text-text-primary">{value}</div>
  </div>;
}

function ClaimValidationReadyCard({ ready, pending }: { ready: import("../api/client").SignalForgeClaimValidationReady; pending: import("../api/client").SignalForgeValidationExperiment[] }) {
  const register = useRegisterSignalForgeValidationExperiment();
  const open = new Set(pending.filter((x) => String(x.status || "").toUpperCase() === "PENDING" && Number(x.case_id) === Number(ready.case_id)).map((x) => String(x.claim_code || "").toUpperCase()));
  const claims = (ready.prepared_claims || []).filter((code) => ["C10", "C11", "C14"].includes(String(code).toUpperCase()));
  return (
    <div className="rounded-xl border border-border-secondary bg-bg-primary p-3">
      <div className="text-[10px] text-text-tertiary">Case {ready.case_id}</div>
      <div className="mt-1 text-sm font-medium text-text-primary">{ready.title || `Case ${ready.case_id}`}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {claims.map((code) => {
          const event = ready.events?.[code] || code;
          const already = open.has(String(code).toUpperCase());
          return <button key={code} type="button" disabled={already || register.isPending} onClick={() => register.mutate({ case_id: ready.case_id, claim_code: code })} className="rounded-lg border border-border-primary bg-bg-primary px-2.5 py-1.5 text-[11px] font-medium text-text-primary hover:bg-bg-secondary disabled:opacity-50">
            {already ? `${code} 已註冊` : `註冊 ${code} · ${event}`}
          </button>;
        })}
      </div>
    </div>
  );
}

function ClaimValidationExecutionCard({ record }: { record: import("../api/client").SignalForgeValidationExperiment }) {
  const complete = useRecordSignalForgeValidationResult();
  const [result, setResult] = useState("INCONCLUSIVE");
  const [actor, setActor] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("TWD");
  const [note, setNote] = useState("");
  const claim = String(record.claim_code || "").toUpperCase();
  const payment = claim === "C11";
  const binary = result === "PASS" || result === "FAIL";
  const ready = !binary || (actor.trim() && (!payment || (Number(amount || 0) > 0 && currency.trim())));
  return (
    <details className="rounded-xl border border-border-secondary bg-bg-primary p-3">
      <summary className="cursor-pointer list-none">
        <div className="flex items-center justify-between gap-3"><div><div className="text-[10px] text-text-tertiary">{claim} · {record.event}</div><div className="mt-1 text-sm font-medium text-text-primary">{record.title || `Case ${record.case_id}`}</div></div><span className="text-[10px] text-text-tertiary">{record.experiment_id}</span></div>
      </summary>
      <div className="mt-4 grid gap-3 border-t border-border-secondary pt-4 lg:grid-cols-2">
        <label className="text-[11px] text-text-secondary">Result<select value={result} onChange={(e) => setResult(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary"><option>INCONCLUSIVE</option><option>PASS</option><option>FAIL</option></select></label>
        <label className="text-[11px] text-text-secondary">Actor / buyer<input value={actor} onChange={(e) => setActor(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>
        {payment ? <><label className="text-[11px] text-text-secondary">Amount<input value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label><label className="text-[11px] text-text-secondary">Currency<input value={currency} onChange={(e) => setCurrency(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label></> : null}
        <label className="lg:col-span-2 text-[11px] text-text-secondary">Note<textarea value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>
      </div>
      <div className="mt-3 flex justify-end"><button type="button" disabled={complete.isPending || !ready} onClick={() => complete.mutate({ experimentId: record.experiment_id, payload: { result, actor_label: actor.trim(), amount: payment ? Number(amount || 0) : undefined, currency: payment ? currency.trim() : undefined, note } })} className="rounded-lg bg-text-primary px-3 py-2 text-[11px] font-medium text-bg-primary disabled:opacity-50">記錄結果</button></div>
    </details>
  );
}

function MarketActionExecutionCard({ record }: { record: import("../api/client").SignalForgeMarketActionRecord }) {
  const complete = useCompleteSignalForgeMarketAction();
  const [result, setResult] = useState("INCONCLUSIVE");
  const [observedSample, setObservedSample] = useState(String(record.sample_target || ""));
  const [actors, setActors] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [observedBehavior, setObservedBehavior] = useState("");
  const [findings, setFindings] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("TWD");
  const category = String(record.category || record.mode || "").toUpperCase();
  const actionType = String(record.action_type || "").toUpperCase();
  const paymentPass = result === "PASS" && (actionType.includes("PAY") || actionType.includes("PRICE") || actionType.includes("WTP"));
  const actorList = actors.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean);
  const refs = evidenceRefs.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean);
  const sampleN = Number(observedSample || 0);
  const binary = result === "PASS" || result === "FAIL";
  const sampleReady = sampleN >= Number(record.sample_target || 1);
  const evidenceReady = actorList.length > 0 && refs.length > 0;
  const findingReady = category === "FOUNDER_DISCOVERY" ? findings.trim().length >= 8 : observedBehavior.trim().length >= 8;
  const paymentReady = !paymentPass || (Number(amount || 0) > 0 && currency.trim().length > 0 && actorList.length > 0);
  const qualityReady = !binary || (sampleReady && evidenceReady && findingReady && paymentReady);
  return (
    <details className="rounded-xl border border-border-secondary bg-bg-primary p-3">
      <summary className="cursor-pointer list-none">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div><div className="text-[10px] text-text-tertiary">{humanizeActionType(record.action_type)}</div><div className="mt-1 text-sm font-medium text-text-primary">{record.action_id}</div></div>
          <div className="text-[11px] text-text-secondary">目標樣本 {record.sample_target ?? "—"} · {record.status}</div>
        </div>
      </summary>
      <div className="mt-4 grid gap-3 border-t border-border-secondary pt-4 lg:grid-cols-2">
        <label className="text-[11px] text-text-secondary">結果<select value={result} onChange={(e) => setResult(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary"><option value="INCONCLUSIVE">還不能判斷</option><option value="PASS">有支持訊號</option><option value="FAIL">沒有支持訊號</option></select></label>
        <label className="text-[11px] text-text-secondary">實際樣本數<input value={observedSample} onChange={(e) => setObservedSample(e.target.value)} inputMode="numeric" className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>
        <label className="text-[11px] text-text-secondary">接觸到的對象<textarea value={actors} onChange={(e) => setActors(e.target.value)} placeholder="Buyer A, Buyer B" className="mt-1 min-h-20 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>
        <label className="text-[11px] text-text-secondary">證據紀錄<textarea value={evidenceRefs} onChange={(e) => setEvidenceRefs(e.target.value)} placeholder="meeting-note:..., invoice:..." className="mt-1 min-h-20 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>
        {category === "FOUNDER_DISCOVERY" ? <label className="lg:col-span-2 text-[11px] text-text-secondary">你實際發現了什麼<textarea value={findings} onChange={(e) => setFindings(e.target.value)} className="mt-1 min-h-24 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label> : <label className="lg:col-span-2 text-[11px] text-text-secondary">買家實際做了什麼<textarea value={observedBehavior} onChange={(e) => setObservedBehavior(e.target.value)} className="mt-1 min-h-24 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label>}
        {paymentPass ? <><label className="text-[11px] text-text-secondary">實際金額<input value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label><label className="text-[11px] text-text-secondary">幣別<input value={currency} onChange={(e) => setCurrency(e.target.value)} className="mt-1 w-full rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-2 text-xs text-text-primary" /></label></> : null}
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className={`text-[10px] ${qualityReady ? "text-text-tertiary" : "text-txt-warning"}`}>{binary ? (qualityReady ? "資料完整，可以記錄。" : "PASS / FAIL 要有足夠樣本、對象與可追溯證據。") : "還不能判斷也可以記錄，但不會當成市場校準證據。"}</div>
        <button type="button" disabled={complete.isPending || !qualityReady} onClick={() => complete.mutate({ actionId: record.action_id, payload: { result, observations: { observed_sample_size: sampleN, actor_labels: actorList, evidence_refs: refs, observed_behavior: observedBehavior.trim(), decision_relevant_findings: findings.trim(), ...(paymentPass ? { amount: Number(amount || 0), currency: currency.trim(), actor_label: actorList[0] || "" } : {}) } } })} className="rounded-lg border border-border-primary bg-text-primary px-3 py-2 text-[11px] font-medium text-bg-primary disabled:opacity-50">記錄結果</button>
      </div>
    </details>
  );
}

function SystemPill({ icon, label, strong = false }: { icon: ReactNode; label: string; strong?: boolean }) {
  return <div className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[11px] ${strong ? "border-success/20 bg-bg-success/45 text-txt-success" : "border-border-secondary bg-bg-primary text-text-secondary"}`}>{icon}{label}</div>;
}

function OperatingLane({ title, count, items, emphasis = false }: { title: string; count: number; items: SignalForgeOperatingQueueItem[]; emphasis?: boolean }) {
  return <div className={`rounded-2xl border p-3 ${emphasis ? "border-success/20 bg-bg-success/25" : "border-border-secondary bg-bg-primary"}`}>
    <div className="flex items-center justify-between gap-2"><span className="text-[11px] font-medium text-text-secondary">{title}</span><span className="rounded-md bg-bg-secondary px-2 py-0.5 text-[10px] text-text-primary">{count}</span></div>
    <div className="mt-2 space-y-1.5">
      {items.slice(0, 3).map((item, i) => <div key={`${item.case_id || item.candidate_id || i}-${i}`} className="text-[10px] leading-4 text-text-tertiary"><span className="text-text-secondary">{item.title || `Case ${item.case_id || "?"}`}</span><br />{humanizeMachineAction(item.action || item.current_gate)}</div>)}
      {count === 0 ? <div className="text-[10px] text-text-tertiary">目前沒有</div> : null}
      {count > 3 ? <div className="text-[10px] text-text-tertiary">+{count - 3} 個</div> : null}
    </div>
  </div>;
}

function RadarTabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" role="tab" aria-selected={active} onClick={onClick} className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-info/30 ${active ? "bg-text-primary text-bg-primary" : "text-text-secondary hover:bg-bg-secondary hover:text-text-primary"}`}>{children}</button>;
}

function FounderBlock({ eyebrow, icon, children, emphasis = false }: { eyebrow: string; icon: ReactNode; children: ReactNode; emphasis?: boolean }) {
  return <div className={`rounded-xl border p-3 ${emphasis ? "border-success/20 bg-bg-success/30" : "border-border-secondary bg-bg-secondary/30"}`}>
    <div className={`flex items-center gap-1.5 text-[9px] font-medium ${emphasis ? "text-txt-success" : "text-text-tertiary"}`}>{icon}{eyebrow}</div>
    <div className="mt-1.5 text-[11px] leading-5 text-text-primary">{children}</div>
  </div>;
}

function MaturityRail({ claims }: { claims: Record<string, string> }) {
  return <div className="mt-5 overflow-x-auto pb-1"><div className="flex min-w-[620px] items-center">{maturityStages.map((stage, index) => { const state = stageState(claims, stage.code); const visual = stageVisual(state); return <div key={stage.code} className="flex flex-1 items-center"><div className="flex flex-col items-center"><div className={`flex h-5 w-5 items-center justify-center rounded-full border ${visual.ring} ${visual.text}`}>{visual.icon}</div><div className={`mt-1 text-[9px] font-medium ${visual.text}`}>{stage.label}</div></div>{index < maturityStages.length - 1 ? <div className={`mx-1 h-px flex-1 ${state === "SUPPORTED" ? "bg-success/35" : "bg-border-secondary"}`} /> : null}</div>; })}</div></div>;
}
