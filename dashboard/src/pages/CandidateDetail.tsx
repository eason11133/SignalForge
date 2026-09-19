import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  Boxes,
  Check,
  ChevronDown,
  Circle,
  Copy,
  Download,
  Eye,
  FileText,
  Printer,
  Radar,
  Search,
  ShieldCheck,
  Target,
  MessageCircle,
  X,
} from "lucide-react";
import {
  useProblemCandidate,
  useSignalForgeDaily,
  useSignalForgeOpportunityDetail,
  useSignalForgeResearchMore,
  useSignalForgeResearchState,
  useTriggerSignalForge,
  useUpdateProblemCandidateStatus,
} from "../api/hooks";

const titleZh: Record<string, string> = {
  "AI model does not produce reliable outputs": "AI 模型輸出不可靠",
  "AI model assumptions lead to incorrect outputs": "AI 模型錯誤假設導致輸出偏差",
  "Over-reliance on tools for debugging among junior engineers": "初階工程師過度依賴工具除錯",
  "Windows VRAM consumption limits model performance": "Windows VRAM 使用限制模型效能",
  "Broken onboarding process for API access": "API 存取 onboarding 流程失效",
  "AI model output is unreliable under load": "AI 模型在高負載下輸出不可靠",
  "Complexity and deployment issues with Salesforce integration": "Salesforce 整合與部署複雜",
  "Inability to generate effective regression tests for certain bugs": "特定 Bug 難以產生有效回歸測試",
  "Insufficient data for accurate modeling of streaming services": "串流服務建模缺乏足夠資料",
  "Poor communication channels hinder effective collaboration": "溝通管道不良降低協作效率",
};

type ClaimState = "SUPPORTED" | "REFUTED" | "INSUFFICIENT" | "UNKNOWN" | string;
type RealityPacket = {
  status?: string;
  next_boundary?: string;
  source_need?: string;
  wedge?: unknown;
  competitors?: unknown;
  friction?: unknown;
  technology_regime?: unknown;
};

type DiscussionPack = {
  title: string;
  originalTitle?: string | null;
  problem: string;
  actor?: string | null;
  task?: string | null;
  consequence?: string | null;
  buyerContext?: string | null;
  workaround?: string | null;
  verdict: string;
  decisionReason: string;
  biggestUnknown: string;
  currentSolutions: string[];
  competitiveContext: string[];
  confirmedGapReasons: string[];
  gapUnknowns: string[];
  gapContext: string[];
  buyers: string[];
  existingHypothesis?: string | null;
  companyFit: string;
  companyGaps: string[];
  claims: Record<string, string>;
  evidence: Array<{ source: string; title: string; excerpt: string; url?: string | null }>;
};

function normalizedState(value?: string | null): ClaimState {
  return String(value || "UNKNOWN").toUpperCase();
}

function stateLabel(state: ClaimState) {
  if (state === "SUPPORTED") return "已確認";
  if (state === "REFUTED") return "不成立";
  if (state === "INSUFFICIENT") return "證據不足";
  return "尚未知";
}

function stateVisual(state: ClaimState) {
  if (state === "SUPPORTED") return { text: "text-txt-success", border: "border-success/30", bg: "bg-bg-success/40", icon: <Check size={11} /> };
  if (state === "REFUTED") return { text: "text-danger", border: "border-danger/30", bg: "bg-bg-danger/40", icon: <X size={11} /> };
  if (state === "INSUFFICIENT") return { text: "text-txt-warning", border: "border-warning/25", bg: "bg-bg-warning/35", icon: <Circle size={8} fill="currentColor" /> };
  return { text: "text-text-tertiary", border: "border-border-primary", bg: "bg-bg-secondary/40", icon: <Circle size={8} /> };
}

function sourceLabel(source?: string | null) {
  const value = String(source || "evidence").toLowerCase();
  if (value.includes("hackernews")) return "Hacker News";
  if (value.includes("reddit")) return "Reddit";
  if (value.includes("stackoverflow") || value.includes("stackexchange")) return "Stack Exchange";
  if (value.includes("github")) return "GitHub";
  if (value.includes("job")) return "Jobs";
  if (value.includes("news")) return "News";
  if (value.includes("community")) return "Community";
  if (value.includes("product")) return "Product";
  return source || "Evidence";
}

function uniqueStrings(values: unknown[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (value: unknown) => {
    if (value == null) return;
    if (typeof value === "string" || typeof value === "number") {
      const text = String(value).trim();
      if (text && !seen.has(text.toLowerCase())) {
        seen.add(text.toLowerCase());
        out.push(text);
      }
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(add);
      return;
    }
    if (typeof value === "object") {
      const row = value as Record<string, unknown>;
      for (const key of ["name", "company", "product", "solution", "competitor", "repo", "title", "label"]) {
        if (row[key] != null) {
          add(row[key]);
          return;
        }
      }
    }
  };
  values.forEach(add);
  return out.slice(0, 12);
}

function textValue(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string" || typeof value === "number") {
    const text = String(value).trim();
    return text || null;
  }
  if (Array.isArray(value)) {
    const parts = uniqueStrings(value);
    return parts.length ? parts.join("、") : null;
  }
  if (typeof value === "object") {
    const row = value as Record<string, unknown>;
    for (const key of ["hypothesis", "wedge", "summary", "description", "text", "action", "reason"]) {
      const text = textValue(row[key]);
      if (text) return text;
    }
  }
  return null;
}

function verdictLabel(verdict?: string | null) {
  const value = String(verdict || "WATCH").toUpperCase();
  if (value === "VALIDATE") return "值得真人驗證";
  if (value === "INVESTIGATE") return "值得深入研究";
  if (value === "BUILD") return "已進入 Build 邊界";
  if (value === "IGNORE" || value === "PARK") return "暫不投入";
  return "機器持續研究";
}

function companyFitLabel(state: ClaimState) {
  if (state === "SUPPORTED") return "目前能力看起來能做，但仍要用真實交付驗證。";
  if (state === "REFUTED") return "目前有明確能力／執行障礙，不適合直接做。";
  if (state === "INSUFFICIENT") return "有部分能力訊號，但還不足以說這題適合我們解。";
  return "尚未完成 Company Reality 判斷。";
}

const claimName: Record<string, string> = {
  C01: "問題存在", C02: "重複發生", C03: "痛點重大", C04: "市場連結",
  C05: "Buyer reality", C06: "現有方案", C07: "未解缺口", C08: "差異化",
  C09: "我能不能做", C10: "客戶取得", C11: "付費意願", C12: "時機",
  C13: "競爭", C14: "切換摩擦",
};

function claimHuman(code: string) {
  return `${code} · ${claimName[code] || "Claim"}`;
}

function researchGapLabel(value?: unknown) {
  const gap = String(value || "");
  const labels: Record<string, string> = {
    INDEPENDENT_NEED_RECURRENCE: "獨立需求 / 重複發生證據",
    CURRENT_SOLUTION_SUPPLY: "現有解法 / 供給",
    PEER_ADOPTION_OR_DIFFUSION: "同類採用 / 擴散",
    PAYMENT_BEHAVIOR: "實際付費行為",
  };
  return labels[gap] || gap || "尚未選出下一個研究 Gap";
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildDiscussionPrompt(pack: DiscussionPack) {
  const evidence = pack.evidence.length
    ? pack.evidence.map((item, index) => `${index + 1}. [${item.source}] ${item.title}\n   ${item.excerpt}${item.url ? `\n   ${item.url}` : ""}`).join("\n")
    : "目前沒有可直接展示的 evidence row。";
  const solutions = pack.currentSolutions.length ? pack.currentSolutions.join("、") : "尚未取得足夠具名解法";
  const competition = pack.competitiveContext.length ? pack.competitiveContext.join("、") : "尚未取得足夠具名競爭／替代脈絡";
  const confirmedGap = pack.confirmedGapReasons.length ? pack.confirmedGapReasons.map((item) => `- ${item}`).join("\n") : "- 目前沒有已確認的未解缺口理由";
  const unknowns = pack.gapUnknowns.length ? pack.gapUnknowns.map((item) => `- ${item}`).join("\n") : "- 目前沒有額外 published unknown";
  const gapContext = pack.gapContext.length ? pack.gapContext.map((item) => `- ${item}`).join("\n") : "- 無";
  const companyGaps = pack.companyGaps.length ? pack.companyGaps.map((item) => `- ${item}`).join("\n") : "- 目前沒有更具體的 capability gap plan";
  const claimText = Object.entries(pack.claims).map(([code, state]) => `${code}=${state}`).join(" | ") || "無";

  return `# SignalForge Founder Discussion Handoff

這是一份由 SignalForge 篩選並整理好的商機上下文。SignalForge 的工作到「發現、篩選、整理證據與未知」為止；接下來請你作為我的 Founder thinking partner 跟我討論。

## 對話規則
- 把下面內容視為已讀上下文，不要一上來重新做一份完整市場研究。
- 事實、SignalForge 判斷、你的推論、產品假設要清楚分開。
- 不要因為 SignalForge 把它排進來，就預設這是一個好商機。
- 不要自動替我產生 7 天產品 wedge 或 30 天 MVP；只有我問到產品、驗證、價格或執行時再一起推。
- 如果我要求最新狀況，或某個關鍵事實可能已過期，再另外查證。
- 我可以只問「你怎麼看？」、「最大的漏洞？」、「值不值得驗證？」或任何角度，你直接承接這份上下文回答。

## Opportunity
標題：${pack.title}${pack.originalTitle ? `\n原文：${pack.originalTitle}` : ""}
問題：${pack.problem}
誰遇到：${pack.actor || "未知"}
正在做什麼：${pack.task || "未知"}
造成什麼：${pack.consequence || "未知"}
Buyer context：${pack.buyerContext || "未知"}
目前 workaround：${pack.workaround || "未知"}

## SignalForge published judgment
Verdict：${pack.verdict}
Decision reason：${pack.decisionReason}
最大未知：${pack.biggestUnknown}
Claim states：${claimText}

## 市場現在怎麼解
具名解法：${solutions}
競爭／替代脈絡：${competition}

## 未解缺口：已確認 vs 未知
已確認的 persistence / failure evidence：
${confirmedGap}

仍未知：
${unknowns}

其他相關 context：
${gapContext}

## Buyer
${pack.buyers.length ? pack.buyers.join("、") : "尚無具名 Buyer"}

## Company reality
${pack.companyFit}
能力缺口：
${companyGaps}

## 已存在的產品假設（若有）
${pack.existingHypothesis || "目前沒有 evidence-backed product hypothesis。這不是缺資料時要自動補出的欄位。"}

## 可追溯證據
${evidence}

---
如果這份訊息後面沒有附我的具體問題，請只簡短回覆：「已接手這筆商機，你可以直接問我任何角度。」不要主動展開一整份分析。`;
}

function buildMarkdownPack(pack: DiscussionPack, prompt: string) {
  const solutions = pack.currentSolutions.length ? pack.currentSolutions.map((item) => `- ${item}`).join("\n") : "- 尚無足夠具名解法";
  const competition = pack.competitiveContext.length ? pack.competitiveContext.map((item) => `- ${item}`).join("\n") : "- 尚無足夠具名競爭／替代脈絡";
  const confirmedGap = pack.confirmedGapReasons.length ? pack.confirmedGapReasons.map((item) => `- ${item}`).join("\n") : "- 目前沒有已確認的未解缺口理由";
  const gapUnknowns = pack.gapUnknowns.length ? pack.gapUnknowns.map((item) => `- ${item}`).join("\n") : "- 目前沒有額外 published unknown";
  const gapContext = pack.gapContext.length ? pack.gapContext.map((item) => `- ${item}`).join("\n") : "- 無";
  const buyers = pack.buyers.length ? pack.buyers.map((item) => `- ${item}`).join("\n") : "- 尚無具名 Buyer";
  const companyGaps = pack.companyGaps.length ? pack.companyGaps.map((item) => `- ${item}`).join("\n") : "- 目前沒有更具體的 capability gap plan";
  const evidence = pack.evidence.length ? pack.evidence.map((item) => `- [${item.source}] ${item.title}\n  - ${item.excerpt}${item.url ? `\n  - ${item.url}` : ""}`).join("\n") : "- 無可展示 evidence";
  const claims = Object.entries(pack.claims).map(([code, state]) => `- ${code}: ${state}`).join("\n") || "- 無";

  return `# SignalForge Founder Discussion Handoff

## ${pack.title}

${pack.originalTitle ? `原文：${pack.originalTitle}\n\n` : ""}**Verdict:** ${pack.verdict}

**目前判斷：** ${pack.decisionReason}

**問題：** ${pack.problem}

**最大未知：** ${pack.biggestUnknown}

## 誰遇到 / Buyer
${buyers}

- Actor：${pack.actor || "未知"}
- Task：${pack.task || "未知"}
- Consequence：${pack.consequence || "未知"}
- Buyer context：${pack.buyerContext || "未知"}

## 市場現在怎麼解
${solutions}

### 競爭 / 替代脈絡
${competition}

**目前 workaround：** ${pack.workaround || "未知"}

## 未解缺口

### 已確認的 persistence / failure evidence
${confirmedGap}

### 仍未知
${gapUnknowns}

### 其他相關 context
${gapContext}

## Company reality
${pack.companyFit}

### 能力缺口
${companyGaps}

## 已存在的產品假設（若有）
${pack.existingHypothesis || "目前沒有 evidence-backed product hypothesis。"}

## Claim states
${claims}

## 可追溯證據
${evidence}

---

## 貼到 ChatGPT 的 handoff

${prompt}
`;
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the textarea fallback for browsers that block Clipboard API.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  return copied;
}

function printPack(pack: DiscussionPack) {
  const popup = window.open("", "_blank", "width=960,height=900");
  if (!popup) return;
  const list = (items: string[], fallback: string) => items.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>${escapeHtml(fallback)}</p>`;
  const evidence = pack.evidence.length
    ? `<ol>${pack.evidence.map((item) => `<li><strong>${escapeHtml(item.source)}</strong> — ${escapeHtml(item.title)}<br/><span>${escapeHtml(item.excerpt)}</span>${item.url ? `<br/><small>${escapeHtml(item.url)}</small>` : ""}</li>`).join("")}</ol>`
    : "<p>無可展示 evidence。</p>";
  popup.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(pack.title)} - SignalForge</title><style>body{font-family:Arial,'Noto Sans TC',sans-serif;color:#161616;max-width:820px;margin:40px auto;line-height:1.65;padding:0 24px}h1{font-size:28px}h2{font-size:17px;margin-top:28px;border-top:1px solid #ddd;padding-top:18px}h3{font-size:14px;margin-top:18px}p,li{font-size:13px}.muted{color:#777}.box{border:1px solid #ddd;border-radius:12px;padding:14px 16px;background:#fafafa}small{color:#777;word-break:break-all}@media print{body{margin:0;max-width:none}.no-print{display:none}}</style></head><body><div class="muted">SignalForge · Founder Discussion Handoff</div><h1>${escapeHtml(pack.title)}</h1>${pack.originalTitle ? `<p class="muted">原文：${escapeHtml(pack.originalTitle)}</p>` : ""}<div class="box"><strong>${escapeHtml(pack.verdict)}</strong><p>${escapeHtml(pack.decisionReason)}</p></div><h2>問題</h2><p>${escapeHtml(pack.problem)}</p><h2>市場現在怎麼解</h2>${list(pack.currentSolutions, "尚無足夠具名解法")}<h3>競爭 / 替代脈絡</h3>${list(pack.competitiveContext, "尚無足夠具名競爭／替代脈絡")}<p><strong>Workaround：</strong>${escapeHtml(pack.workaround || "未知")}</p><h2>未解缺口</h2><h3>已確認的 persistence / failure evidence</h3>${list(pack.confirmedGapReasons, "目前沒有已確認的未解缺口理由")}<h3>仍未知</h3>${list(pack.gapUnknowns, "目前沒有額外 published unknown")}<h3>其他相關 context</h3>${list(pack.gapContext, "無")}<h2>Company reality</h2><p>${escapeHtml(pack.companyFit)}</p>${list(pack.companyGaps, "目前沒有更具體的 capability gap plan")}<h2>已存在的產品假設（若有）</h2><p>${escapeHtml(pack.existingHypothesis || "目前沒有 evidence-backed product hypothesis。")}</p><h2>Buyer</h2>${list(pack.buyers, "尚無具名 Buyer")}<h2>最大未知</h2><p>${escapeHtml(pack.biggestUnknown)}</p><h2>證據</h2>${evidence}<script>setTimeout(()=>window.print(),250)<\/script></body></html>`);
  popup.document.close();
}

export default function CandidateDetail() {
  const params = useParams();
  const id = Number(params.id || 0);
  const candidateQuery = useProblemCandidate(id);
  const dailyQuery = useSignalForgeDaily();
  const forgeDetailQuery = useSignalForgeOpportunityDetail(id);
  const researchStateQuery = useSignalForgeResearchState(id);
  const researchMore = useSignalForgeResearchMore(id);
  const refreshSignalForge = useTriggerSignalForge();
  const update = useUpdateProblemCandidateStatus();
  const [copied, setCopied] = useState(false);

  const candidate = candidateQuery.data;
  const card = useMemo(
    () => dailyQuery.data?.cards?.find((item: any) => item.candidate_id === id),
    [dailyQuery.data?.cards, id]
  );

  if (!id || candidateQuery.isLoading) {
    return (
      <div className="mx-auto max-w-[1260px] space-y-4">
        <div className="h-7 w-36 animate-pulse rounded-lg bg-bg-secondary" />
        <div className="h-64 animate-pulse rounded-2xl border border-border-secondary bg-bg-primary" />
        <div className="h-52 animate-pulse rounded-2xl border border-border-secondary bg-bg-primary" />
      </div>
    );
  }

  if (candidateQuery.error || !candidate) {
    return (
      <div className="mx-auto max-w-[1260px] rounded-2xl border border-danger/25 bg-bg-danger px-5 py-4 text-sm text-danger">
        這個商機目前無法讀取。SignalForge 不會用舊資料假裝正常。
      </div>
    );
  }

  const claims = { ...(forgeDetailQuery.data?.claim_states || {}), ...(card?.claims || {}) };
  const reality = (card?.reality || {}) as Record<string, RealityPacket>;
  const c06 = normalizedState(claims.C06);
  const c07 = normalizedState(claims.C07);
  const c09 = normalizedState(claims.C09);
  const c08 = normalizedState(claims.C08);
  const buyers = card?.buyer_organizations || [];
  const displayTitle = titleZh[candidate.title] || candidate.title;
  const originalTitle = displayTitle !== candidate.title ? candidate.title : null;
  const forgeDetail = forgeDetailQuery.data;
  const soloAssessment = card?.solo_transition || forgeDetail?.solo_assessment || {};
  // Founder truth surfaces must not promote raw CandidateEvidence metadata into
  // confirmed solution/competition claims. Use adjudicated ledger / published
  // reality only; unverified candidate evidence stays outside the handoff.
  const currentSolutions = uniqueStrings([
    forgeDetail?.current_solutions,
  ]);
  const competitiveContext = uniqueStrings([
    forgeDetail?.competitive_context,
    reality.C08?.competitors,
    reality.C13?.competitors,
  ]);
  const existingHypothesis = textValue(reality.C08?.wedge);
  const switchingFriction = textValue(reality.C14?.friction);
  const technologyRegime = textValue(reality.C12?.technology_regime);
  const rawGapEvidence = (forgeDetail?.gap_evidence || []).slice(0, 12);
  const exactGapEvidence = rawGapEvidence.filter((item: any) => item.validated).slice(0, 5);
  const confirmedGapSupport = exactGapEvidence.filter((item: any) => String(item.stance || "").toUpperCase() === "SUPPORT");
  const confirmedGapReasons = c07 === "SUPPORTED" ? uniqueStrings([
    "已有直接證據顯示：使用現有方案後，核心問題仍持續存在。",
    ...(forgeDetail?.failure_reasons || []),
    ...confirmedGapSupport.slice(0, 4).map((item: any) => item.excerpt || item.source_title || ""),
  ]) : [];
  const gapUnknowns = uniqueStrings([
    c07 === "REFUTED" ? "目前證據反而不支持『現有方案仍無法解掉核心問題』；不要把它當成 persistence 已成立。" : null,
    c07 === "INSUFFICIENT" || c07 === "UNKNOWN" ? "未解 Gap 尚未被證明；現在還不能把『市場上有方案』解讀成『市場仍有缺口』。" : null,
    c07 !== "SUPPORTED" && rawGapEvidence.length ? `目前有 ${rawGapEvidence.length} 筆 C07 evidence row，但狀態尚未 SUPPORTED，因此只當成待判斷資料。` : null,
    card?.biggest_unknown,
  ]);
  const gapContext = uniqueStrings([
    switchingFriction ? `切換／摩擦訊號：${switchingFriction}` : null,
    technologyRegime ? `技術環境：${technologyRegime}` : null,
  ]);
  const companyGaps = (card?.company_gap_plan || []).map((item: any) => {
    const capability = item.capability || "能力缺口";
    const action = item.action || item.boundary || item.status || "待補";
    return `${capability}：${action}`;
  });
  const discussionEvidence = (forgeDetail?.published_evidence || [])
    .filter((item: any) => item.validated)
    .map((item: any) => ({
      source: sourceLabel(item.source_type),
      title: `[${item.claim_code || "CLAIM"} · ${String(item.stance || "EVIDENCE").toUpperCase()}] ${item.source_title || item.excerpt || "Validated ledger evidence"}`,
      excerpt: item.excerpt || item.rationale || item.source_title || "",
      url: item.source_url,
    }))
    .filter((item, index, rows) => rows.findIndex((row) => `${row.source}|${row.title}|${row.url || ""}` === `${item.source}|${item.title}|${item.url || ""}`) === index)
    .slice(0, 12);
  const truthRows = Object.entries(claims).map(([code, value]) => ({ code, state: normalizedState(value) }));
  const knownTruth = truthRows.filter((row) => row.state === "SUPPORTED");
  const contradictedTruth = truthRows.filter((row) => row.state === "REFUTED");
  const unknownTruth = truthRows.filter((row) => !["SUPPORTED", "REFUTED"].includes(String(row.state)));
  const researchState = researchStateQuery.data;
  const bestNextResearch = (researchState?.best_next_research || {}) as Record<string, unknown>;
  const recentResearch = (researchState?.recent_requests || []).slice(0, 3);
  const pack: DiscussionPack = {
    title: displayTitle,
    originalTitle,
    problem: candidate.problem_statement || "目前問題描述仍待更多證據收斂。",
    actor: candidate.actor,
    task: candidate.task,
    consequence: candidate.consequence,
    buyerContext: candidate.buyer_context,
    workaround: candidate.workaround,
    verdict: verdictLabel(card?.verdict || candidate.stage),
    decisionReason: card?.decision_reason || "SignalForge 仍在補證據。",
    biggestUnknown: card?.biggest_unknown || "目前沒有更具體的 published unknown。",
    currentSolutions,
    competitiveContext,
    confirmedGapReasons,
    gapUnknowns,
    gapContext,
    buyers,
    existingHypothesis,
    companyFit: companyFitLabel(c09),
    companyGaps,
    claims,
    evidence: discussionEvidence,
  };
  const discussionPrompt = buildDiscussionPrompt(pack);
  const markdownPack = buildMarkdownPack(pack, discussionPrompt);

  const copyHandoff = async () => {
    const ok = await copyText(discussionPrompt);
    setCopied(ok);
    if (ok) window.setTimeout(() => setCopied(false), 2200);
    return ok;
  };

  const discussWithChatGPT = async () => {
    const chatWindow = window.open("https://chatgpt.com/", "_blank");
    if (chatWindow) chatWindow.opener = null;
    await copyHandoff();
    chatWindow?.focus();
  };

  const runResearchMore = () => researchMore.mutate();
  const refreshPublished = () => refreshSignalForge.mutate();

  return (
    <div className="mx-auto max-w-[1260px] pb-14">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 rounded-lg py-1 text-[11px] font-medium text-text-tertiary hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30"
      >
        <ArrowLeft size={13} /> 回今日商機
      </Link>

      <section className="mt-4 overflow-hidden rounded-2xl border border-border-secondary bg-bg-primary">
        <div className="px-5 py-5 md:px-7 md:py-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0 max-w-4xl">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-info/20 bg-bg-info px-2.5 py-1 text-[11px] font-medium text-txt-info">
                  <Radar size={11} /> {soloAssessment.classification === "RESEARCH_THEME" ? "Research Theme · 不是目前 Solo 商機" : verdictLabel(card?.verdict || candidate.stage)}
                </span>
                {card ? <span className="text-[11px] text-text-tertiary">優先度 {Math.round(card.attention_score)}</span> : null}
              </div>
              <h1 className="mt-3 text-[29px] font-semibold leading-[1.18] tracking-[-0.025em] text-text-primary">{displayTitle}</h1>
              {originalTitle ? <div className="mt-1.5 text-[11px] text-text-tertiary">原文：{originalTitle}</div> : null}
              <p className="mt-4 max-w-3xl text-[13px] leading-6 text-text-secondary">{candidate.problem_statement || "目前問題描述仍待更多證據收斂。"}</p>
            </div>

            <div className="flex shrink-0 flex-wrap gap-2 xl:w-[420px] xl:justify-end">
              <button type="button" disabled={researchMore.isPending} onClick={runResearchMore} className="inline-flex items-center gap-1.5 rounded-xl border border-info/20 bg-bg-info px-3 py-2.5 text-[11px] font-medium text-txt-info hover:opacity-90 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">
                <Search size={13} /> {researchMore.isPending ? "研究中…" : "研究下一個未知"}
              </button>
              <button type="button" disabled={refreshSignalForge.isPending} onClick={refreshPublished} className="inline-flex items-center gap-1.5 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-secondary hover:bg-bg-secondary disabled:opacity-50">
                <Radar size={13} /> {refreshSignalForge.isPending ? "啟動中…" : "重新掃描 / 更新 Published"}
              </button>
              <button type="button" onClick={discussWithChatGPT} className="inline-flex items-center gap-1.5 rounded-xl bg-text-primary px-3 py-2.5 text-[11px] font-medium text-white hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">
                <MessageCircle size={13} /> {copied ? "Handoff 已複製" : "與 ChatGPT 討論"}
              </button>
              <button type="button" onClick={() => printPack(pack)} className="inline-flex items-center gap-1.5 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-primary hover:bg-bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">
                <Printer size={13} /> 存成 PDF
              </button>
              <button type="button" disabled={update.isPending} onClick={() => update.mutate({ id: candidate.id, status: "watch" })} className="inline-flex items-center gap-1.5 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-secondary hover:bg-bg-secondary disabled:opacity-50">
                <Eye size={13} /> 追蹤
              </button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <SummaryStat label="Problem shape" value={soloAssessment.problem_shape || "UNKNOWN"} />
            <SummaryStat label="Transition gap" value={soloAssessment.transition_gap || "UNKNOWN"} />
            <SummaryStat label="Economic necessity" value={soloAssessment.economic_necessity || "UNKNOWN"} />
            <SummaryStat label="Solo fit" value={soloAssessment.solo_fit || "UNKNOWN"} />
          </div>
        </div>
      </section>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <main className="space-y-4">
          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<Target size={16} />} eyebrow="SOLO FOUNDER GATE" title="這到底是不是我一個人抓得到的商機" />
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              <InfoBox label="分類" value={soloAssessment.classification || "UNKNOWN"} />
              <InfoBox label="下一個必要 Gate" value={soloAssessment.next_gate || "UNKNOWN"} />
            </div>
            {(soloAssessment.disqualifiers || []).length ? (
              <div className="mt-4">
                <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">目前不能算商機的原因</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(soloAssessment.disqualifiers || []).map((item: string) => <span key={item} className="rounded-lg border border-warning/20 bg-bg-warning/25 px-2.5 py-1.5 text-[10px] text-txt-warning">{item}</span>)}
                </div>
              </div>
            ) : null}
            <div className="mt-4 text-[10px] leading-5 text-text-tertiary">SignalForge 不在這裡硬生產品。只有具體 workflow、transition/adoption gap、經濟必要性與 solo capture path 都有證據，才有資格進 Founder priority。</div>
          </section>

          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<Boxes size={16} />} eyebrow="SOLUTION LANDSCAPE" title="市場現在怎麼解" />
            <div className="mt-4 flex items-center gap-2">
              <StateBadge state={c06} />
              <span className="text-[11px] text-text-tertiary">SignalForge 對「現有方案／替代做法確實存在」的判斷</span>
            </div>
            <div className="mt-4">
              <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">具名現有解法</div>
              {currentSolutions.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {currentSolutions.map((solution) => <span key={solution} className="rounded-lg border border-border-secondary bg-bg-secondary/45 px-2.5 py-1.5 text-[11px] text-text-secondary">{solution}</span>)}
                </div>
              ) : (
                <div className="mt-2 rounded-xl bg-bg-secondary/40 px-4 py-3 text-[12px] leading-5 text-text-secondary">
                  {c06 === "SUPPORTED" ? "已確認市場上存在現有方案，但目前 Ledger 還沒有足夠具名 solution identity 可安全展示。" : "尚未取得足夠證據建立具名 Solution Landscape。"}
                </div>
              )}
            </div>
            <div className="mt-4 border-t border-border-secondary pt-4">
              <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">競爭 / 替代脈絡</div>
              <div className="mt-1 text-[10px] leading-4 text-text-tertiary">這些是競爭或替代訊號，不自動等同「已證明能解核心問題」的現有解法。</div>
              {competitiveContext.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {competitiveContext.map((item) => <span key={item} className="rounded-lg border border-border-secondary bg-bg-primary px-2.5 py-1.5 text-[11px] text-text-secondary">{item}</span>)}
                </div>
              ) : <div className="mt-2 text-[11px] text-text-tertiary">目前沒有足夠具名競爭／替代脈絡。</div>}
            </div>
            <div className="mt-4">
              <InfoBox label="現在的 workaround" value={candidate.workaround || "尚未辨識到穩定 workaround"} />
            </div>
          </section>

          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<Search size={16} />} eyebrow="UNRESOLVED GAP" title="為什麼到現在還沒被解掉" />
            <div className="mt-4 flex items-center gap-2"><StateBadge state={c07} /><span className="text-[11px] text-text-tertiary">未解缺口不是預設成立；已證明理由和未知必須分開。</span></div>

            <div className="mt-4">
              <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">已確認的 persistence / failure evidence</div>
              {confirmedGapReasons.length ? (
                <div className="mt-2 space-y-2.5">
                  {confirmedGapReasons.map((reason, index) => (
                    <div key={`${reason}-${index}`} className="flex gap-2.5 rounded-xl border border-success/15 bg-bg-success/20 px-3.5 py-3 text-[12px] leading-5 text-text-secondary">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-success/25 bg-bg-primary text-[9px] text-txt-success"><Check size={10} /></span>
                      <span>{reason}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-2 rounded-xl bg-bg-secondary/35 px-4 py-3 text-[11px] leading-5 text-text-secondary">目前沒有可以安全寫成「為什麼沒解掉」的已確認理由。</div>
              )}
            </div>

            <div className="mt-4 border-t border-border-secondary pt-4">
              <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">仍未知 / 證據不足</div>
              <div className="mt-2 space-y-2">
                {gapUnknowns.length ? gapUnknowns.map((item, index) => (
                  <div key={`${item}-${index}`} className="rounded-xl bg-bg-secondary/35 px-3.5 py-3 text-[11px] leading-5 text-text-secondary">{item}</div>
                )) : <div className="text-[11px] text-text-tertiary">目前沒有額外 published unknown。</div>}
              </div>
            </div>

            {gapContext.length ? (
              <div className="mt-4 border-t border-border-secondary pt-4">
                <div className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">其他相關 context</div>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {gapContext.map((item) => <div key={item} className="rounded-xl border border-border-secondary bg-bg-secondary/20 px-3.5 py-3 text-[11px] leading-5 text-text-secondary">{item}</div>)}
                </div>
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<ShieldCheck size={16} />} eyebrow="TRUTH SNAPSHOT" title="現在到底知道什麼、不知道什麼、哪裡被反證" />
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <TruthColumn title="KNOWN · 已確認" tone="success" rows={knownTruth} empty="目前沒有 SUPPORTED claim。" />
              <TruthColumn title="UNKNOWN · 還不能下結論" tone="warning" rows={unknownTruth} empty="目前沒有未解 claim。" />
              <TruthColumn title="CONTRADICTED · 被反證" tone="danger" rows={contradictedTruth} empty="目前沒有 REFUTED claim。" />
            </div>
            <div className="mt-3 text-[9px] leading-4 text-text-tertiary">INSUFFICIENT / UNKNOWN 不會被 UI 自動補成弱支持；Search failure 也不是反證。</div>
          </section>

          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<Target size={16} />} eyebrow="COMPANY CAPABILITY" title="如果問題成立，我目前有沒有必要能力" />
            <div className="mt-4 flex flex-wrap items-center gap-2"><StateBadge state={c09} /><span className="text-[12px] font-medium text-text-primary">{companyFitLabel(c09)}</span></div>
            {companyGaps.length ? (
              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {companyGaps.map((gap: string) => <div key={gap} className="rounded-xl border border-border-secondary bg-bg-secondary/30 px-3.5 py-3 text-[11px] leading-5 text-text-secondary">{gap}</div>)}
              </div>
            ) : (
              <div className="mt-4 rounded-xl bg-bg-secondary/35 px-4 py-3 text-[11px] text-text-secondary">目前沒有更具體的 capability gap plan；不要把「能做 demo」當成「能做到客戶滿意」。</div>
            )}
          </section>

          <section className="rounded-2xl border border-info/15 bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<Search size={16} />} eyebrow="RESEARCH MORE · SHADOW" title="下一個最值得補的證據" />
            <div className="mt-4 rounded-xl border border-info/15 bg-bg-info/20 px-4 py-3">
              <div className="text-[10px] font-medium text-txt-info">{researchGapLabel(bestNextResearch.gap)}</div>
              <div className="mt-1 text-[11px] leading-5 text-text-secondary">
                {bestNextResearch.action ? `下一步：${String(bestNextResearch.action)}` : researchState?.status === "NOT_REGISTERED" ? "這筆商機尚未建立 Founder-directed shadow research state；第一次點擊會建立並只跑 1 個 bounded request。" : "目前沒有正 marginal-value 的研究步驟。"}
              </div>
              {bestNextResearch.marginal_voi != null ? <div className="mt-1 text-[9px] text-text-tertiary">Marginal VOI：{String(bestNextResearch.marginal_voi)}（只做研究排序，不是市場真實機率）</div> : null}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" disabled={researchMore.isPending} onClick={runResearchMore} className="inline-flex items-center gap-1.5 rounded-xl bg-text-primary px-3 py-2.5 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50">
                <Search size={13} /> {researchMore.isPending ? "正在跑 bounded research…" : "補研究 1 次"}
              </button>
              <button type="button" onClick={() => researchStateQuery.refetch()} disabled={researchStateQuery.isFetching} className="inline-flex items-center gap-1.5 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-secondary hover:bg-bg-secondary disabled:opacity-50">
                <Radar size={13} /> 重新讀取 Shadow State
              </button>
            </div>
            {recentResearch.length ? (
              <div className="mt-4 space-y-2">
                {recentResearch.map((row: any, index: number) => (
                  <div key={row.request_id || index} className="rounded-xl border border-border-secondary bg-bg-secondary/25 px-3.5 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] font-medium text-text-primary"><span>{researchGapLabel(row.gap)}</span><span className="text-text-tertiary">{row.adapter || "adapter unknown"}</span></div>
                    <div className="mt-1 text-[10px] leading-5 text-text-secondary">{row.query || "No query recorded"}</div>
                    <div className="mt-1 text-[9px] text-text-tertiary">retrieved {row.candidate_count ?? 0} · confirmed independent {row.confirmed_count ?? 0}{row.error ? ` · error: ${row.error}` : ""}</div>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="mt-3 text-[9px] leading-4 text-text-tertiary">這裡是 SHADOW research。Retrieved candidate 不會直接改 C01–C14、WTP、Opportunity verdict 或 Build recommendation；Published truth 只會透過正式 adjudication / publish pipeline 更新。</div>
          </section>

          <section className="rounded-2xl border border-info/15 bg-bg-primary px-5 py-5 md:px-6">
            <SectionTitle icon={<MessageCircle size={16} />} eyebrow="FOUNDER DISCUSSION" title="到這裡 SignalForge 的工作先停" />
            <p className="mt-4 max-w-3xl text-[12px] leading-6 text-text-secondary">
              SignalForge 只把通過 Solo Founder Gate 的題目當 Founder priority。若這頁是 Research Theme，它只保留作研究脈絡，不要求你硬想產品；真正的產品切口、價格與驗證仍留到你和 ChatGPT 的對話裡一起推。
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {["你怎麼看？", "最大的漏洞在哪？", "值得花時間驗證嗎？", "如果要測，最小怎麼測？", "跟我現在的方向相比呢？"].map((starter) => (
                <span key={starter} className="rounded-full border border-info/15 bg-bg-info/20 px-2.5 py-1.5 text-[10px] text-txt-info">{starter}</span>
              ))}
            </div>
            {existingHypothesis ? (
              <details className="mt-4 rounded-xl border border-border-secondary bg-bg-secondary/20 px-4 py-3">
                <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">SignalForge 目前已有一個 product hypothesis（只當討論上下文）</summary>
                <div className="mt-2 text-[11px] leading-5 text-text-secondary">{existingHypothesis}</div>
              </details>
            ) : null}
          </section>

          <details className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-4 md:px-6">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg text-[11px] font-medium text-text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">
              <span className="inline-flex items-center gap-2"><ShieldCheck size={14} /> 商業現實與 Claim 狀態</span><ChevronDown size={14} className="text-text-tertiary" />
            </summary>
            <div className="mt-4 border-t border-border-secondary pt-4">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ["C08", "差異化"], ["C10", "客戶取得"], ["C11", "付費意願"], ["C12", "時機"],
                  ["C13", "競爭"], ["C14", "切換"], ["C09", "執行能力"], ["C07", "未解缺口"],
                ].map(([code, label]) => <ClaimTile key={code} label={label} code={code} state={normalizedState(claims[code])} />)}
              </div>
            </div>
          </details>

          <details className="rounded-2xl border border-border-secondary bg-bg-primary px-5 py-4 md:px-6">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg text-[11px] font-medium text-text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">
              <span className="inline-flex items-center gap-2"><FileText size={14} /> 可追溯證據</span><ChevronDown size={14} className="text-text-tertiary" />
            </summary>
            <div className="mt-4 divide-y divide-border-secondary border-t border-border-secondary">
              {discussionEvidence.length ? discussionEvidence.map((item, index) => (
                <article key={`${item.source}-${index}`} className="py-3.5">
                  <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-text-tertiary">{item.source}</div>
                  <div className="mt-1 text-[12px] font-medium leading-5 text-text-primary">{item.title}</div>
                  {item.excerpt && item.excerpt !== item.title ? <div className="mt-1 text-[11px] leading-5 text-text-secondary">{item.excerpt}</div> : null}
                  {item.url ? <a href={item.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[10px] font-medium text-txt-info hover:underline">開啟來源 <ArrowUpRight size={10} /></a> : null}
                </article>
              )) : <div className="py-5 text-[11px] text-text-tertiary">目前沒有已驗證、可安全帶入 Founder handoff 的 Evidence row。</div>}
            </div>
          </details>
        </main>

        <aside className="space-y-4 xl:sticky xl:top-20 xl:self-start">
          <section className="rounded-2xl border border-border-secondary bg-bg-primary px-4 py-4">
            <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-tertiary">FOUNDER VIEW</div>
            <div className="mt-3 space-y-3">
              <SideRow label="現有方案" state={c06} />
              <SideRow label="未解缺口" state={c07} />
              <SideRow label="差異化" state={c08} />
              <SideRow label="我能不能做" state={c09} />
            </div>
            <div className="mt-4 border-t border-border-secondary pt-4">
              <div className="text-[10px] text-text-tertiary">具名 Buyer</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {buyers.length ? buyers.slice(0, 8).map((buyer: string) => <span key={buyer} className="max-w-full truncate rounded-lg bg-bg-secondary px-2 py-1 text-[10px] text-text-secondary" title={buyer}>{buyer}</span>) : <span className="text-[11px] text-text-tertiary">尚未確認</span>}
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-info/15 bg-bg-info/20 px-4 py-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-text-primary"><MessageCircle size={15} /> 跟 ChatGPT 討論這個商機</div>
            <p className="mt-2 text-[11px] leading-5 text-text-secondary">把 SignalForge 已整理的 published truth、解法、Gap、Company Fit、Unknowns 與已驗證 Ledger Evidence 交接出去；unvalidated candidate evidence 不會混進 handoff，也不再讓 Radar 為「討論」額外燒 token。</p>
            <div className="mt-4 space-y-2">
              <button type="button" onClick={discussWithChatGPT} className="flex w-full items-center justify-center gap-2 rounded-xl bg-text-primary px-3 py-2.5 text-[11px] font-medium text-white hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30"><MessageCircle size={13} /> {copied ? "Handoff 已複製，切到 ChatGPT 貼上" : "複製並開啟 ChatGPT"}</button>
              <button type="button" onClick={copyHandoff} className="flex w-full items-center justify-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-primary hover:bg-bg-secondary"><Copy size={13} /> 只複製 Handoff</button>
              <button type="button" onClick={() => downloadText(`signalforge-opportunity-${candidate.id}.md`, markdownPack)} className="flex w-full items-center justify-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-primary hover:bg-bg-secondary"><Download size={13} /> 下載 Discussion Handoff .md</button>
              <button type="button" onClick={() => printPack(pack)} className="flex w-full items-center justify-center gap-2 rounded-xl border border-border-primary bg-bg-primary px-3 py-2.5 text-[11px] font-medium text-text-primary hover:bg-bg-secondary"><Printer size={13} /> 列印 / 存 PDF</button>
            </div>
            <div className="mt-3 text-[9px] leading-4 text-text-tertiary">SignalForge 不會在這裡替你決定產品、MVP 或價格。Handoff 只帶 published truth 與 validated ledger evidence，讓 ChatGPT 從可追溯的已知事實開始跟你談。</div>
          </section>

          <button type="button" disabled={update.isPending} onClick={() => update.mutate({ id: candidate.id, status: "dismissed" })} className="flex w-full items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-[11px] text-text-tertiary hover:bg-bg-danger hover:text-danger disabled:opacity-50">
            <X size={13} /> 暫時略過這個商機
          </button>
        </aside>
      </div>
    </div>
  );
}

function SectionTitle({ icon, eyebrow, title }: { icon: ReactNode; eyebrow: string; title: string }) {
  return (
    <div>
      <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.12em] text-text-tertiary">{icon}{eyebrow}</div>
      <h2 className="mt-1.5 text-[16px] font-semibold tracking-[-0.01em] text-text-primary">{title}</h2>
    </div>
  );
}

function TruthColumn({ title, tone, rows, empty }: { title: string; tone: "success" | "warning" | "danger"; rows: Array<{ code: string; state: ClaimState }>; empty: string }) {
  const toneClass = tone === "success" ? "border-success/20 bg-bg-success/25" : tone === "danger" ? "border-danger/20 bg-bg-danger/20" : "border-warning/20 bg-bg-warning/20";
  return (
    <div className={`rounded-xl border px-3.5 py-3 ${toneClass}`}>
      <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-text-tertiary">{title}</div>
      <div className="mt-2 space-y-1.5">
        {rows.length ? rows.slice(0, 8).map((row) => (
          <div key={row.code} className="flex items-center justify-between gap-2 text-[10px]"><span className="text-text-secondary">{claimHuman(row.code)}</span><StateBadge state={row.state} /></div>
        )) : <div className="text-[10px] text-text-tertiary">{empty}</div>}
      </div>
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-border-secondary bg-bg-secondary/30 px-4 py-3"><div className="text-[9px] font-medium uppercase tracking-[0.1em] text-text-tertiary">{label}</div><div className="mt-1.5 line-clamp-2 text-[11px] leading-5 text-text-secondary">{value}</div></div>;
}

function InfoBox({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-border-secondary bg-bg-secondary/25 px-3.5 py-3"><div className="text-[9px] font-medium uppercase tracking-[0.08em] text-text-tertiary">{label}</div><div className="mt-1.5 text-[11px] leading-5 text-text-secondary">{value}</div></div>;
}

function StateBadge({ state }: { state: ClaimState }) {
  const visual = stateVisual(state);
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[9px] font-medium ${visual.border} ${visual.bg} ${visual.text}`}>{visual.icon}{stateLabel(state)}</span>;
}

function ClaimTile({ label, code, state }: { label: string; code: string; state: ClaimState }) {
  return <div className="rounded-xl border border-border-secondary bg-bg-secondary/25 px-3 py-3"><div className="flex items-center justify-between gap-2"><span className="text-[11px] font-medium text-text-primary">{label}</span><span className="text-[9px] text-text-tertiary">{code}</span></div><div className="mt-2"><StateBadge state={state} /></div></div>;
}

function SideRow({ label, state }: { label: string; state: ClaimState }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-[11px] text-text-secondary">{label}</span><StateBadge state={state} /></div>;
}
