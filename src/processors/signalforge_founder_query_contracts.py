from __future__ import annotations

import re
from typing import Any, Mapping

ENGINE_VERSION = "signalforge-r8-idea-research-final-query-contracts-v1"

_LATIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]{1,}")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_WS_RE = re.compile(r"\s+")

_GENERIC = {
    "the","a","an","and","or","not","to","of","for","in","on","with","from","by","is","are","be","been",
    "this","that","these","those","it","they","them","we","our","i","my","you","your","can","could","would",
    "should","must","after","before","more","many","multiple","small","team","teams","user","users","problem",
    "issue","workflow","workflows","process","processes","system","systems","tool","tools","service","services",
    "manual","manually","time","easy","hard","important","difference","differences","need","needs","using","use",
}

# Deterministic bridges are evidence-navigation aids only. They are never market evidence.
_ZH_ALIAS_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("採購","詢價","報價","供應商","供應鏈"), ("procurement","purchasing","sourcing","rfq","quote","supplier","vendor")),
    (("規格","條款","交期","比價","比較"), ("specification","terms","delivery","compare","comparison","normalize")),
    (("發票","對帳","結算"), ("invoice","reconciliation","settlement","accounting")),
    (("預約","候補","取消","爽約"), ("appointment","booking","waitlist","cancellation","no-show")),
    (("理髮","髮廊","美容","美甲","按摩"), ("barbershop","salon","beauty","local-service")),
    (("醫療","診所","病患","臨床","醫院"), ("healthcare","medical","clinic","patient","clinical")),
    (("工程","程式","程式碼","開發","測試","品質"), ("engineering","developer","software","code","testing","qa")),
    (("忘記","遺忘","記不住"), ("forget","memory","persistent-memory")),
    (("規則","設定","指令"), ("rules","instructions","settings","preferences")),
    (("人工","手動"), ("manual","human-work")),
    (("付費","訂閱","價格"), ("paid","subscription","pricing")),
)

_DOMAIN_GROUPS: dict[str, set[str]] = {
    "PROCUREMENT": {"procurement","purchasing","sourcing","rfq","quote","quotation","supplier","vendor","tender","bid"},
    "SOFTWARE_ENGINEERING": {"engineering","developer","software","code","coding","github","repo","repository","qa","testing","pull","commit"},
    "INSURANCE_DOCUMENT_OPERATIONS": {"insurance","insurer","claim","claims","document-extraction","extraction"},
    "GO_TO_MARKET": {"gtm","go-to-market","selling","sales","marketing","customer-acquisition"},
    "HEALTHCARE": {"healthcare","medical","clinic","patient","clinical","hospital"},
    "MARKETING_CONTENT": {"linkedin","content","marketing","social","post","creator"},
    "FINANCE_RECONCILIATION": {"invoice","reconciliation","settlement","accounting","payment","billing"},
    "APPOINTMENT_LOCAL_SERVICE": {"appointment","booking","waitlist","barbershop","salon","beauty","no-show"},
    "AI_AGENT_MEMORY": {"agent","agents","memory","persistent-memory","instructions","rules","context"},
    "NONPROFIT_ASSOCIATION_OPERATIONS": {"nonprofit","nonprofits","non-profit","ngo","charity","association","associations","foundation","volunteer"},
    "EDUCATION_EXAM": {"student","students","exam","exams","education","learning","learner","learners","taiwan","gsat","school"},
    "AGENCY_SERVICES": {"agency","agencies","consultancy","consultancies","consulting","studio","studios","client","clients","discovery","strategy","validation","research"},
    "ECOMMERCE_OPERATOR": {"ecommerce","e-commerce","shopify","merchant","merchants","seller","sellers","store","marketplace"},
}

_WORKFLOW_GROUPS: dict[str, set[str]] = {
    "COMPARE_NORMALIZE": {"compare","comparison","normalize","specification","terms","delivery","quote","rfq","excel","pdf","email"},
    "RECONCILE": {"reconciliation","invoice","settlement","accounting","match"},
    "SCHEDULE": {"appointment","booking","waitlist","cancellation","no-show"},
    "SOFTWARE_QA": {"qa","test","tests","testing","review","reviewing","reviewed","bug","regression","verification","verify","acceptance"},
    "MEMORY_PERSISTENCE": {"memory","persistent-memory","forget","remember","instructions","rules","context"},
    "SECURITY_COMPLIANCE": {"security","compliance","audit","privacy","ciso"},
    "MESSAGING_AUTOMATION": {"messaging","message","messages","line","bot","automation","chatbot","workflow"},
    "LANGUAGE_OUTPUT_TRAINING": {"english","writing","translation","output","trainer","practice","vocabulary","exam"},
    "OPPORTUNITY_VALIDATION": {"opportunity","validation","market","research","discovery","strategy","assessment","workshop","sprint"},
    "PROFESSIONAL_SERVICE_DELIVERY": {"agency","consulting","consultancy","client","engagement","retainer","delivery","research"},
    "MERCHANT_OPERATIONS": {"merchant","seller","shopify","store","orders","inventory","marketplace","ecommerce"},
}

_ACTOR_GROUPS: dict[str, set[str]] = {
    "PROCUREMENT_BUYER": {"procurement","purchasing","sourcing","buyer","supplier","vendor"},
    "ENGINEERING_BUYER": {"engineering","developer","cto","qa","platform","security","software"},
    "HEALTHCARE_BUYER": {"healthcare","medical","clinic","clinical","hospital","patient"},
    "FINANCE_BUYER": {"finance","accounting","controller","invoice","reconciliation"},
    "LOCAL_SERVICE_BUYER": {"barbershop","salon","beauty","appointment","booking"},
    "MARKETING_BUYER": {"marketing","content","linkedin","social","creator"},
    "NONPROFIT_OPERATOR": {"nonprofit","nonprofits","non-profit","ngo","charity","association","foundation","volunteer"},
    "STUDENT_LEARNER": {"student","students","learner","learners","exam","school","gsat"},
    "AGENCY_CONSULTANCY_BUYER": {"agency","agencies","consultancy","consultancies","consulting","studio","studios","client","clients"},
    "ECOMMERCE_OPERATOR": {"ecommerce","e-commerce","merchant","merchants","seller","sellers","shopify","store"},
}


# Problem/job dimensions capture the specific job-to-be-done or failure mode.
# Broad domain adjacency (AI, coding, founder, software, etc.) is intentionally
# excluded from these dimensions so it cannot make a trace relevant by itself.
_PROBLEM_DIMENSION_GROUPS: dict[str, set[str]] = {
    "COMPLETION_VERIFICATION": {
        "verify", "verifies", "verified", "verifying", "verification",
        "validate", "validates", "validated", "validating", "validation",
        # Bare "correct" is intentionally excluded. It is too ambiguous: it can
        # mean "I correct/edit the draft" or "correct permission" and previously
        # promoted adjacent/documentation traces into exact verification evidence.
        "correctness", "acceptance", "evidence", "proof",
    },
    "REQUIREMENT_ADHERENCE": {
        "requirement", "requirements", "spec", "specification", "acceptance-criteria",
        "functionality", "behavior", "behaviour", "ux", "adherence", "adhere", "adheres", "adhered", "satisfy", "meets",
    },
    "TEST_EVIDENCE": {
        "test", "tests", "testing", "qa", "regression", "coverage", "ci", "assertion", "assertions",
    },
    "HUMAN_REVIEW_BURDEN": {
        "review", "reviewing", "reviewed", "human-review", "manual-review", "code-review",
        "inspect", "inspection", "checking", "check",
    },
    "TRUSTED_RESULT": {
        "trust", "trusted", "untrusted", "reliable", "unreliable", "proof", "evidence",
    },
    "COMPARE_NORMALIZE_JOB": {
        "compare", "comparison", "normalize", "normalization", "quote", "quotation", "rfq",
        "specification", "terms", "delivery",
    },
    "RECONCILIATION_JOB": {
        "reconciliation", "reconcile", "invoice", "settlement", "matching", "match",
    },
    "SCHEDULING_CAPACITY_JOB": {
        "appointment", "booking", "waitlist", "cancellation", "no-show", "slot", "capacity",
    },
    "MEMORY_PERSISTENCE_JOB": {
        "memory", "forget", "forgot", "remember", "persistent-memory", "instructions", "rules", "context",
    },
    "PAID_VALUE_JOB": {
        "paid", "pay", "pricing", "subscription", "budget", "cost", "spend", "purchase",
    },
}

_BROAD_CONTEXT_TERMS = {
    "ai", "agent", "agents", "agentic", "coding", "code", "developer", "developers",
    "engineering", "software", "founder", "founders", "tool", "tools", "app", "apps",
    "platform", "service", "services", "work", "working", "team", "teams", "product",
    "products", "workflow", "workflows", "context",
    "but", "cannot", "without", "whether", "everything", "actual", "actually",
    "finish", "finished", "complete", "completed", "completion", "done",
    "correct",
}

_LENS_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("works fine","good enough","already solved","native built in","no need"), ("good","enough","solved","native")),
    (("not worth paying","would not pay","no budget","free enough","low priority","rare problem"), ("budget","value","free","expensive","rare")),
    (("switching cost","migration","trust","security","procurement","discontinued","failed product","no traction"), ("switching","migration","security","procurement","discontinued","traction")),
)


def clean(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def semantic_terms(text: str, *, include_lens_aliases: bool = True) -> list[str]:
    raw = clean(text)
    low = raw.lower()
    out: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        # Transport/source tokens may contain dots/slashes, but semantic concept
        # matching must not fail because sentence punctuation is attached to the
        # token (e.g. ``questionnaires.`` or ``writing.``).
        t = term.lower().strip().strip("._+/")
        if len(t) < 2 or t in _GENERIC or t in seen:
            return
        seen.add(t)
        out.append(t)

    for token in _LATIN_RE.findall(raw):
        add(token)
    for zh_terms, aliases in _ZH_ALIAS_GROUPS:
        if any(z in raw for z in zh_terms):
            for alias in aliases:
                add(alias)
    if include_lens_aliases:
        for triggers, aliases in _LENS_KEYWORDS:
            if any(trigger in low for trigger in triggers):
                for alias in aliases:
                    add(alias)
    return out


def concept_groups(text: str, groups: Mapping[str, set[str]], *, include_lens_aliases: bool = False) -> set[str]:
    # Evidence semantics use only concepts actually present in the text. Query-
    # transport lens aliases are intentionally excluded so e.g. "trusted" does
    # not manufacture procurement/security domain signals.
    terms = set(semantic_terms(text, include_lens_aliases=include_lens_aliases))
    return {name for name, vocab in groups.items() if terms & vocab}




# R8 System Reset WIP: cross-domain hypothesis grammar. These are not benchmark
# answers; they are generic actor/workflow/job concepts used by the same gate for
# developer, education, SMB, agency, ecommerce, creator, nonprofit and B2B SaaS.
_DOMAIN_GROUPS.update({
    "MATH_EDUCATION": {"math","mathematics","algebra","geometry","calculus"},
    "SMB_SERVICE_OPERATIONS": {"small-business","small-businesses","smb","service-business","service-businesses","local-business","local-businesses"},
    "CUSTOMER_SUPPORT_OPERATIONS": {"customer-support","support-team","support-teams","support","inquiry","inquiries","faq","faqs","customer-message","customer-messages","order-status","refund","returns"},
    "CREATOR_CONTENT_OPERATIONS": {"creator","creators","podcast","podcasts","video","videos","short-form","shortform","repurpose","repurposing","clip","clips","content-repurposing"},
    "B2B_SAAS_PROCUREMENT": {"b2b","saas","b2b-saas","enterprise","procurement","security-questionnaire","security-questionnaires","vendor-review","vendor-security"},
})
_WORKFLOW_GROUPS.update({
    "MULTI_AGENT_COORDINATION": {"multi-agent","multiple-agents","parallel-agents","agent-coordination","orchestration","worktree","worktrees","branches","branch","collide","collision","conflict","conflicts","overlapping","sessions","session"},
    "AI_CODE_MAINTENANCE": {"understand","understanding","ownership","maintain","maintenance","debug","debugging","codebase","implementation-detail","implementation-details"},
    "VOCABULARY_LEARNING": {"vocabulary","word","words","memorize","memorized","memorization","meaning","meanings","retention","remember","recognize","recognition","sense","usage"},
    "CUSTOMER_INQUIRY_HANDLING": {"inquiry","inquiries","question","questions","faq","faqs","quote","quotes","booking","bookings","appointment","appointments","message","messages","reply","replies","answer","answers","customer-service","customer-support"},
    "LEAD_RESPONSE": {"lead","leads","inquiry","inquiries","message","messages","reply","replies","respond","response","slow-response","missed-message","missed-messages","lost-lead","lost-leads"},
    "CLIENT_REPORTING": {"client-report","client-reports","reporting","performance-report","performance-reports","dashboard","dashboards","spreadsheet","spreadsheets","aggregate","aggregation","multi-platform","cross-platform"},
    "ECOMMERCE_SUPPORT": {"wismo","order-status","shipping","delivery","return","returns","refund","refunds","logistics","customer-support","support-ticket","support-tickets"},
    "CONTENT_REPURPOSING": {"repurpose","repurposing","clip","clipping","rewrite","rewriting","short-form","shortform","platform-specific","podcast","long-form","longform","content-repurposing"},
    "SECURITY_QUESTIONNAIRE": {"security-questionnaire","security-questionnaires","questionnaire","questionnaires","vendor-security","security-review","security-reviews","procurement-review","compliance-questionnaire","compliance-questionnaires"},
})
_ACTOR_GROUPS.update({
    "SMB_OPERATOR": {"small-business","small-businesses","smb","service-business","service-businesses","local-business","local-businesses","merchant"},
    "CREATOR_OPERATOR": {"creator","creators","youtuber","youtubers","podcaster","podcasters","podcast","podcasts","publisher","publishers"},
    "B2B_SAAS_TEAM": {"b2b","saas","b2b-saas","software-vendor","software-vendors","vendor","vendors","security-team","security-teams","small-team","small-teams"},
})
_PROBLEM_DIMENSION_GROUPS.update({
    "MULTI_AGENT_COLLISION": {"collide","collision","conflict","conflicts","overlap","overlapping","same-file","same-repo","coordination","orchestration","worktree","worktrees"},
    "CODEBASE_UNDERSTANDING_LOSS": {"dont-understand","don't-understand","lose-understanding","lost-understanding","understand","understanding","ownership","own","dont-own","don't-own","debugging","maintainability","implementation-detail","implementation-details","codebase"},
    "LANGUAGE_PRODUCTION_GAP": {"cannot-produce","can't-produce","cant-produce","produce-english","english-output","chinese-to-english","translation","writing","write-english","output-gap","production"},
    "VOCABULARY_RETENTION_GAP": {"forget","forgot","forgetting","retention","memorize","memorized","memorization","cannot-remember","can't-remember","cant-remember","recognize","recognition","meaning","meanings","usage","use-words"},
    "REPETITIVE_INQUIRY_TOIL": {"repetitive","repeatedly","same-question","same-questions","faq","faqs","inquiry","inquiries","answer-manually","manual-replies","manual-reply","repeated-questions"},
    "LEAD_RESPONSE_LOSS": {"miss","missed","lose","loses","lost","slow","slowly","delay","delayed","missed-lead","missed-leads","lost-lead","lost-leads","slow-response","respond-slowly","miss-message","missed-message","missed-messages","lose-leads","lost-customer","lost-customers"},
    "CLIENT_REPORTING_TOIL": {"manual-reporting","reporting","recurring-report","recurring-reports","aggregate","aggregation","multi-platform","cross-platform","spreadsheet","spreadsheets"},
    "ECOMMERCE_SUPPORT_TOIL": {"wismo","order-status","shipping","delivery","returns","refunds","logistics","repetitive-support","support-time","support-workload"},
    "CONTENT_REPURPOSING_TOIL": {"repurpose","repurposing","manual-repurposing","clipping","rewriting","short-form","platform-specific","multiple-platforms","multi-platform"},
    "SECURITY_QUESTIONNAIRE_TOIL": {"security-questionnaire","security-questionnaires","questionnaire","questionnaires","vendor-security","security-review","security-reviews","procurement","reuse-evidence","reusing-evidence","compliance"},
})


# Cross-market operational grammar. These concepts are generic and are not tied
# to benchmark URLs or one product. They allow the same relevance gate to reason
# about industrial operations, procurement, claims, asset condition and cost
# recovery without falling back to developer-only semantics.
_DOMAIN_GROUPS.update({
    "MANUFACTURING_OPERATIONS": {"manufacturing","factory","factories","plant","plants","industrial","machine","machines","machinery","pcba","cnc","production","mro","pneumatic"},
    "INDUSTRIAL_ENERGY_OPERATIONS": {"energy","electricity","power","tariff","tariffs","compressed-air","compressed","hvac","solar","facility","facilities"},
    "CONSTRUCTION_PROJECT_CONTROLS": {"construction","contractor","contractors","subcontractor","subcontractors","change-order","change-orders","boq","project-controls"},
    "LOGISTICS_FREIGHT_OPERATIONS": {"freight","cargo","carrier","carriers","logistics","shipment","shipments","shipping"},
    "INDUSTRIAL_PROCUREMENT_MARKET": {"procurement","sourcing","raw-material","raw-materials","spare-part","spare-parts","supplier","suppliers","bidding","competitive-bidding"},
    "ASSET_CONDITION_VALUE": {"asset","assets","equipment","battery","batteries","used-equipment","used-machine","resale","residual-value","condition"},
    "INDUSTRIAL_PROCESS_CONTROL": {"wastewater","dosing","thermal-drift","drift","compensation","process-control","process-optimization"},
    "ECOMMERCE_FINANCE_OPERATIONS": {"ecommerce","e-commerce","marketplace","payout","payouts","settlement","reconciliation"},
})
_WORKFLOW_GROUPS.update({
    "ASSET_INSPECTION_DIAGNOSTICS": {"inspection","inspect","diagnostic","diagnostics","detect","detection","leak","leaks","health","condition","first-article","underperformance"},
    "DOWNTIME_MAINTENANCE_INTELLIGENCE": {"downtime","maintenance","mro","failure","failures","machine-log","machine-logs","log-analysis","root-cause","fault","faults","logs"},
    "PROCUREMENT_SOURCING": {"procurement","purchasing","purchase","purchases","sourcing","source","supplier","suppliers","vendor","vendors","group-purchasing","bulk-buying","spare-parts","raw-material"},
    "CLAIM_EVIDENCE_RECOVERY": {"claim","claims","warranty","change-order","change-orders","evidence","recovery","recover","dispute","disputes","filing"},
    "COST_AUDIT_RECOVERY": {"audit","auditing","tariff","capacity","contract-capacity","payout","payouts","reconciliation","overcharge","underpayment","correction","cost"},
    "PROCESS_OPTIMIZATION": {"optimization","optimisation","optimized","optimize","optimise","dosing","thermal-drift","compensation","efficiency","control"},
    "MARKET_PRICE_DISCOVERY": {"bidding","bids","bid","auction","competitive-bidding","price-discovery","pricing","scrap","byproduct","quote","quotes"},
    "RESIDUAL_VALUE_ASSESSMENT": {"residual-value","residual","resale","condition","health","passport","valuation","value-assessment","used-equipment","pricing"},
})
_ACTOR_GROUPS.update({
    "INDUSTRIAL_OPERATOR": {"factory","factories","plant","plants","manufacturer","manufacturers","manufacturing","industrial","maintenance-team","operations-team","production-manager","production-managers"},
    "FACILITY_OPERATOR": {"facility","facilities","building","buildings","hvac","energy-manager","facility-manager","commercial-building","commercial-buildings"},
    "PROCUREMENT_OPERATOR": {"procurement","purchasing","sourcing","buyer","buyers","supplier","suppliers","manufacturer","manufacturers"},
    "CONSTRUCTION_OPERATOR": {"construction","contractor","contractors","subcontractor","subcontractors","project-manager","project-managers"},
    "LOGISTICS_OPERATOR": {"freight","cargo","carrier","carriers","shipper","shippers","logistics"},
    "ASSET_OWNER_OPERATOR": {"asset-owner","asset-owners","equipment-owner","equipment-owners","fleet","used-ev","used-equipment"},
})




_GENERALIZED_PROBLEM_REGEXES: dict[str, tuple[str, ...]] = {
    "MULTI_AGENT_COLLISION": (
        r"\b(?:agents?|sessions?)\b.{0,80}\b(?:collid\w*|conflict\w*|step on|same file|same repo|worktree\w*)\b",
        r"\b(?:parallel|multiple|two|several)\b.{0,60}\bagents?\b.{0,80}\b(?:conflict\w*|collision\w*|overlap\w*|worktree\w*)\b",
    ),
    "CODEBASE_UNDERSTANDING_LOSS": (
        r"\b(?:don't|do not|cannot|can't|hard to|struggle to)\b.{0,80}\b(?:understand|maintain|debug)\b.{0,80}\b(?:code|codebase|project)\b",
        r"\b(?:understand|own|ownership)\b.{0,60}\b(?:code|codebase|implementation)\b",
    ),
    "LANGUAGE_PRODUCTION_GAP": (
        r"\b(?:cannot|can't|cant|struggle|difficulty|hard)\b.{0,80}\b(?:write|writing|translate|translation|produce)\b.{0,80}\b(?:english|sentence|paragraph)\b",
        r"\b(?:english|chinese-to-english|translation)\b.{0,80}\b(?:cannot|can't|cant|struggle|difficulty|hard)\b.{0,80}\b(?:write|translate|produce)\b",
    ),
    "VOCABULARY_RETENTION_GAP": (
        r"\b(?:memorize|memorized|memorization|study|studied|vocabulary)\b.{0,120}\b(?:forget|forgot|forgetting|can't remember|cannot remember|don't remember|do not remember|don't recognize|cannot recognize|fail(?:s|ed)? to recognize|fail(?:s|ed)? to retain|fail(?:s|ed)? to recall|cannot use|can't use|fail(?:s|ed)? to use|poor retention)\b",
        r"\b(?:forget|forgot|forgetting|can't remember|cannot remember|don't recognize|cannot recognize|poor retention|fail to recognize|fail to retain)\b.{0,80}\b(?:word|words|vocabulary|meaning|meanings)\b",
    ),
    "REPETITIVE_INQUIRY_TOIL": (
        r"\b(?:same|repetitive|repeated|repeatedly)\b.{0,80}\b(?:question|questions|inquiry|inquiries|faq|faqs|booking|bookings)\b",
        r"\b(?:repetitive|repeated)\b.{0,60}\b(?:reply|replies|response|responses)\b",
        r"\b(?:answer|reply|respond)\b.{0,40}\b(?:manually|manual)\b.{0,80}\b(?:question|questions|inquiry|inquiries|message|messages)\b",
        r"\b(?:manually|manual)\b.{0,80}\b(?:answer|reply|respond)\b.{0,80}\b(?:question|questions|inquiry|inquiries|message|messages)\b",
    ),
    "LEAD_RESPONSE_LOSS": (
        r"\b(?:miss|missed|missing)\b.{0,60}\b(?:message|messages|inquiry|inquiries|lead|leads)\b",
        r"\b(?:slow|late|hours? later|delay|delayed)\b.{0,60}\b(?:reply|respond|response)\b.{0,100}\b(?:lead|customer|sale|buy)\b",
        r"\b(?:lead|leads|customer|customers)\b.{0,80}\b(?:gone|lost|leave|buy elsewhere|churn)\b",
    ),
    "CLIENT_REPORTING_TOIL": (
        r"\b(?:manual|manually)\b.{0,80}\b(?:report|reports|reporting|spreadsheet|spreadsheets)\b",
        r"\b(?:export|aggregate|combine)\b.{0,120}\b(?:meta|google ads|analytics|platforms?|spreadsheets?)\b.{0,100}\b(?:report|reporting)\b",
    ),
    "ECOMMERCE_SUPPORT_TOIL": (
        r"\b(?:where is my order|wismo|order status|shipping|delivery|return|returns|refund|refunds)\b.{0,120}\b(?:support|question|questions|ticket|tickets|answer|reply)\b",
        r"\b(?:support|customer service)\b.{0,120}\b(?:order status|shipping|returns?|refunds?|logistics)\b",
    ),
    "CONTENT_REPURPOSING_TOIL": (
        r"\b(?:manual|manually|spend time|hours)\b.{0,100}\b(?:repurpose|clip|clipping|rewrite|rewriting|adapt)\b",
        r"\b(?:long-form|long form|podcast|episode|video)\b.{0,100}\b(?:into|to)\b.{0,80}\b(?:shorts|reels|tiktok|short-form|short form)\b",
    ),
    "SECURITY_QUESTIONNAIRE_TOIL": (
        r"\b(?:security|compliance|vendor)\b.{0,60}\bquestionnaires?\b",
        r"\bquestionnaires?\b.{0,100}\b(?:procurement|security|compliance|soc2|soc 2)\b",
    ),
    "INSPECTION_DIAGNOSTICS_JOB": (
        r"\b(?:inspect|inspection|detect|detection|diagnostic|health|condition)\b.{0,100}\b(?:machine|equipment|pcba|battery|leak|asset|solar)\b",
        r"\b(?:machine|equipment|pcba|battery|asset|solar)\b.{0,100}\b(?:inspect|inspection|detect|detection|diagnostic|health|condition)\b",
    ),
    "DOWNTIME_MAINTENANCE_JOB": (
        r"\b(?:downtime|machine failure|maintenance)\b.{0,120}\b(?:log|logs|root cause|analysis|diagnos\w*)\b",
        r"\b(?:log|logs|telemetry)\b.{0,120}\b(?:downtime|failure|maintenance)\b",
    ),
    "PROCUREMENT_SOURCING_JOB": (
        r"\b(?:procurement|purchasing|sourcing|buyer)\b.{0,120}\b(?:supplier|vendor|raw material|spare[- ]?parts?|group purchasing)\b",
        r"\b(?:supplier|vendor|raw material|spare[- ]?parts?)\b.{0,140}\b(?:identify|source|sourcing|procure|procurement|purchase)\b",
        r"\b(?:parts?|components?)\b.{0,120}\b(?:difficult|hard)\b.{0,100}\b(?:identify|source|sourcing)\b",
    ),
    "CLAIM_RECOVERY_EVIDENCE_JOB": (
        r"\b(?:claim|claims|warranty|change order|change-order)\b.{0,140}\b(?:evidence|proof|recover|recovery|dispute|documentation)\b",
        r"\b(?:evidence|proof)\b.{0,140}\b(?:claim|warranty|change order|change-order|cargo|freight)\b",
    ),
    "COST_AUDIT_RECOVERY_JOB": (
        r"\b(?:audit|reconcile|reconciliation|check)\b.{0,120}\b(?:tariff|capacity|payout|settlement|overcharge|underpayment|invoice|billing|energy cost|electricity cost|hvac cost)\b",
        r"\b(?:tariff|capacity|payout|settlement|overcharge|underpayment|invoice|billing|energy cost|electricity cost|hvac cost)\b.{0,120}\b(?:audit|reconcile|recover|recovery|correction|avoidable)\b",
        r"\b(?:hvac|energy|electricity)\b.{0,100}\b(?:audit|efficiency)\b.{0,100}\b(?:cost|bill|billing|saving|savings|avoidable)\b",
    ),
    "PROCESS_OPTIMIZATION_JOB": (
        r"\b(?:optimi[sz]e|optimization|efficiency|compensation|control)\b.{0,120}\b(?:dosing|wastewater|thermal drift|hvac|process|cnc)\b",
        r"\b(?:dosing|wastewater|thermal drift|hvac|process|cnc)\b.{0,120}\b(?:optimi[sz]e|optimization|efficiency|compensation|control)\b",
    ),
    "MARKET_PRICE_DISCOVERY_JOB": (
        r"\b(?:scrap|byproduct|by-product)\b.{0,120}\b(?:bidding|auction|price discovery|buyers?|competitive)\b",
        r"\b(?:bidding|auction|price discovery)\b.{0,120}\b(?:scrap|byproduct|by-product)\b",
    ),
    "RESIDUAL_VALUE_ASSESSMENT_JOB": (
        r"\b(?:used|resale|residual value|valuation)\b.{0,120}\b(?:equipment|machine|battery|asset|condition|health)\b",
        r"\b(?:condition|health|passport)\b.{0,120}\b(?:resale|residual value|valuation|used equipment|used machine)\b",
    ),
}

# Operational workflows contain many polysemous single words (maintenance, audit,
# quote, condition, health, pricing). They are therefore relation-gated: the
# workflow is present only when the text expresses the corresponding bounded job
# relationship, not merely because one token appears. This is the same fail-closed
# principle used for generalized exact-job dimensions.
_RELATION_GATED_OPERATIONAL_WORKFLOWS: dict[str, str] = {
    "ASSET_INSPECTION_DIAGNOSTICS": "INSPECTION_DIAGNOSTICS_JOB",
    "DOWNTIME_MAINTENANCE_INTELLIGENCE": "DOWNTIME_MAINTENANCE_JOB",
    "PROCUREMENT_SOURCING": "PROCUREMENT_SOURCING_JOB",
    "CLAIM_EVIDENCE_RECOVERY": "CLAIM_RECOVERY_EVIDENCE_JOB",
    "COST_AUDIT_RECOVERY": "COST_AUDIT_RECOVERY_JOB",
    "PROCESS_OPTIMIZATION": "PROCESS_OPTIMIZATION_JOB",
    "MARKET_PRICE_DISCOVERY": "MARKET_PRICE_DISCOVERY_JOB",
    "RESIDUAL_VALUE_ASSESSMENT": "RESIDUAL_VALUE_ASSESSMENT_JOB",
}

_PROBLEM_DIMENSION_WORKFLOW_REQUIREMENTS: dict[str, set[str]] = {
    "COMPARE_NORMALIZE_JOB": {"COMPARE_NORMALIZE"},
    "RECONCILIATION_JOB": {"RECONCILE"},
    "SCHEDULING_CAPACITY_JOB": {"SCHEDULE"},
    "MEMORY_PERSISTENCE_JOB": {"MEMORY_PERSISTENCE"},
    "TEST_EVIDENCE": {"SOFTWARE_QA"},
    "MULTI_AGENT_COLLISION": {"MULTI_AGENT_COORDINATION"},
    "CODEBASE_UNDERSTANDING_LOSS": {"AI_CODE_MAINTENANCE"},
    "LANGUAGE_PRODUCTION_GAP": {"LANGUAGE_OUTPUT_TRAINING"},
    "VOCABULARY_RETENTION_GAP": {"VOCABULARY_LEARNING"},
    "REPETITIVE_INQUIRY_TOIL": {"CUSTOMER_INQUIRY_HANDLING"},
    "LEAD_RESPONSE_LOSS": {"LEAD_RESPONSE"},
    "CLIENT_REPORTING_TOIL": {"CLIENT_REPORTING"},
    "ECOMMERCE_SUPPORT_TOIL": {"ECOMMERCE_SUPPORT"},
    "CONTENT_REPURPOSING_TOIL": {"CONTENT_REPURPOSING"},
    "SECURITY_QUESTIONNAIRE_TOIL": {"SECURITY_QUESTIONNAIRE"},
    "INSPECTION_DIAGNOSTICS_JOB": {"ASSET_INSPECTION_DIAGNOSTICS"},
    "DOWNTIME_MAINTENANCE_JOB": {"DOWNTIME_MAINTENANCE_INTELLIGENCE"},
    "PROCUREMENT_SOURCING_JOB": {"PROCUREMENT_SOURCING"},
    "CLAIM_RECOVERY_EVIDENCE_JOB": {"CLAIM_EVIDENCE_RECOVERY"},
    "COST_AUDIT_RECOVERY_JOB": {"COST_AUDIT_RECOVERY"},
    "PROCESS_OPTIMIZATION_JOB": {"PROCESS_OPTIMIZATION"},
    "MARKET_PRICE_DISCOVERY_JOB": {"MARKET_PRICE_DISCOVERY"},
    "RESIDUAL_VALUE_ASSESSMENT_JOB": {"RESIDUAL_VALUE_ASSESSMENT"},
}

# Narrow Founder human-review closure: role/object identity is kept separate
# from broad domain/problem dimensions. In particular, the token ``agent``
# never implies an AI coding agent.
_AI_CODING_AGENT_PATTERNS = (
    r"\bai\s+coding\s+agents?\b", r"\bcoding\s+agents?\b", r"\bcode\s+agents?\b",
    r"\bclaude\s+code\b", r"\bcodex(?:\s+cli)?\b", r"\baider\b",
    r"\bgithub\s+copilot\b", r"\bdeveloper\s+agents?\b", r"\bsoftware\s+engineering\s+agents?\b",
)
_BUILD_AGENT_PATTERNS = (
    r"\bbuild\s+agents?\b", r"\bci\s+agents?\b", r"\bdeployment\s+agents?\b",
    r"\bjenkins\s+agents?\b", r"\bazure(?:\s+devops)?\s+agents?\b", r"\bmsbuild\b",
    r"\bbuild\s+runners?\b", r"\bci\s+runners?\b",
)
_CHAT_AGENT_PATTERNS = (r"\bchat\s+agents?\b", r"\bchatbots?\b", r"\bconversational\s+agents?\b")
_DOCUMENTATION_PATTERNS = (
    r"\bdocumentation\b", r"\bdocument\b", r"\bdocs\b", r"\bmarkdown\b", r"\breadme\b",
    r"\breferences?\b", r"\burls?\b", r"\blicense\b", r"\bversion\s+metadata\b",
    r"\bapi\s+documentation\b", r"\bsecurity\s+documentation\b", r"\bsections?\b", r"\bwiki\b",
    # Public market traces are multilingual. These cues only establish the
    # DOCUMENTATION object; they never make a trace relevant by themselves.
    r"문서", r"라이선스", r"인용", r"참고문헌", r"文件", r"文档", r"文書", r"ドキュメント",
)
_DEPLOYMENT_PERMISSION_PATTERNS = (
    r"\bdeployment\b", r"\bdeploy\b", r"\bdeploying\b", r"\bpermissions?\b",
    r"\baccess\s+rights?\b", r"\bservice\s+account\b",
)
_BUILD_INFRA_PATTERNS = (
    r"\bmsbuild\b", r"\bbuild\s+agents?\b", r"\bbuild\s+pipeline\b", r"\bci\s+pipeline\b",
    r"\bci/cd\b", r"\bjenkins\b", r"\bbuild\s+runners?\b", r"\bci\s+runners?\b",
)
_IMPLEMENTATION_PATTERNS = (
    r"\bimplement(?:s|ed|ing|ation)?\b", r"\bmodify(?:ing|ied|ies)?\s+(?:the\s+)?code\b",
    r"\bedit(?:ing|ed|s)?\s+(?:the\s+)?code\b", r"\bwrite(?:s|ing|ten)?\s+code\b",
    r"\bgenerat(?:e|es|ed|ing)\s+(?:the\s+)?(?:code|classes?)\b", r"\bship(?:s|ped|ping)?\s+code\b",
    r"\bsoftware\s+implementation\b", r"\bimplementation\s+work\b",
)
_CODE_CHANGE_PATTERNS = (
    r"\bcode\s+changes?\b", r"\bcoding\s+changes?\b", r"\bfunctionality\s+changes?\b", r"\bchange(?:s|d|ing)?\s+(?:the\s+)?code\b", r"\bpatch(?:es|ed|ing)?\b",
    r"\bdiffs?\b", r"\bpull\s+requests?\b", r"\bcommits?\b", r"\bfiles?\s+changed\b",
)
_REFACTOR_PATTERNS = (r"\brefactor(?:s|ed|ing)?\b", r"\brefactoring\b")
_FEATURE_PATTERNS = (r"\bfeature\s+implementation\b", r"\bimplement(?:s|ed|ing)?\s+(?:a\s+|the\s+)?feature\b", r"\badd(?:s|ed|ing)?\s+(?:a\s+|the\s+)?feature\b", r"\bfeature\s+code\b")
_BUG_FIX_PATTERNS = (r"\bbug\s+fix(?:es)?\b", r"\bfix(?:es|ed|ing)?\s+(?:a\s+|the\s+)?bug\b")
_GENERAL_QA_PATTERNS = (r"\bquality\s+review\b", r"\bquality\s+check\b", r"\bqa\s+review\b")
_DIRECT_IMPLEMENTATION_PATTERNS = (
    # Strong implementation relationships. These are deliberately narrower than
    # generic repository vocabulary such as "pull request", "CI" or "code
    # example", which frequently occurs inside documentation reviews.
    *_IMPLEMENTATION_PATTERNS,
    *_REFACTOR_PATTERNS,
    *_FEATURE_PATTERNS,
    *_BUG_FIX_PATTERNS,
    r"\bcode\s+changes?\b",
    r"\bfunctionality\s+changes?\b",
    r"\bchange(?:s|d|ing)?\s+(?:the\s+)?code\b",
    r"\bpatch(?:es|ed|ing)?\s+(?:the\s+)?(?:code|implementation|feature|bug)\b",
    r"\bdiffs?\s+(?:show|shows|showed|contain|contains|contained)\b",
)

_DOCUMENTATION_DOMINANCE_PATTERNS = (
    r"\bmarkdown\b", r"\breadme\b", r"\bdocs?\b", r"\bdocumentation\b",
    r"\breferences?\b", r"\bcitations?\b", r"\blicense\b",
    r"\bversion\s+(?:metadata|information|policy)\b", r"\bapi\s+(?:documentation|docs?|specification)\b",
    r"\bsecurity\s+(?:documentation|section|guide)\b", r"\btest\s+(?:documentation|section|coverage\s+description)\b",
    r"\bci\s+(?:documentation|section|workflow\s+description)\b", r"\bsections?\b", r"\bwiki\b",
    r"문서", r"라이선스", r"인용", r"참고문헌", r"文件", r"文档", r"文書", r"ドキュメント",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    low = clean(text).lower()
    return any(re.search(p, low, re.IGNORECASE) for p in patterns)


def workflow_identity_profile(text: str) -> dict[str, Any]:
    raw = clean(text)
    low = raw.lower()
    explicit_implementation_evidence = _matches_any(raw, _DIRECT_IMPLEMENTATION_PATTERNS)
    documentation_cue_count = sum(1 for p in _DOCUMENTATION_DOMINANCE_PATTERNS if re.search(p, low, re.IGNORECASE))
    objects: set[str] = set()
    if _matches_any(raw, _DOCUMENTATION_PATTERNS): objects.add("DOCUMENTATION")
    if _matches_any(raw, _DEPLOYMENT_PERMISSION_PATTERNS): objects.add("DEPLOYMENT_PERMISSION")
    if _matches_any(raw, _BUILD_INFRA_PATTERNS): objects.add("BUILD_INFRASTRUCTURE")
    if _matches_any(raw, _REFACTOR_PATTERNS): objects.add("REFACTOR")
    if _matches_any(raw, _FEATURE_PATTERNS): objects.add("FEATURE")
    if _matches_any(raw, _BUG_FIX_PATTERNS): objects.add("BUG_FIX")
    if _matches_any(raw, _CODE_CHANGE_PATTERNS): objects.add("CODE_CHANGE")
    if _matches_any(raw, _IMPLEMENTATION_PATTERNS): objects.add("SOFTWARE_IMPLEMENTATION")
    if _matches_any(raw, _GENERAL_QA_PATTERNS): objects.add("GENERAL_QA")

    roles: set[str] = set()
    if _matches_any(raw, _BUILD_AGENT_PATTERNS): roles.add("BUILD_AGENT")
    if _matches_any(raw, _CHAT_AGENT_PATTERNS): roles.add("CHAT_AGENT")
    explicit_ai_coding = _matches_any(raw, _AI_CODING_AGENT_PATTERNS)
    ai_marker = bool(re.search(r"\b(?:ai|llm|model)\b", low))
    implementation_object = bool(objects & {"SOFTWARE_IMPLEMENTATION","CODE_CHANGE","REFACTOR","FEATURE","BUG_FIX"})
    # R6 live-path closure: a real multilingual GitHub documentation review
    # escaped R5 because the prose was Korean and only one English documentation
    # cue survived the lexical bridge. Requiring two cues let incidental
    # repository vocabulary such as "Pull Request" win as CODE_CHANGE.
    # Fail closed: once a documentation object is present and there is no direct
    # implementation relationship, documentation is dominant. A genuine mixed
    # implementation+docs trace remains eligible because explicit implementation
    # evidence overrides this rule.
    documentation_dominant = bool(
        "DOCUMENTATION" in objects
        and documentation_cue_count >= 1
        and not explicit_implementation_evidence
    )
    # Do not manufacture an AI coding agent from "AI quality review" plus
    # repository/doc vocabulary such as pull request, CI, tests or code example.
    if explicit_ai_coding or (ai_marker and implementation_object and not documentation_dominant):
        roles.add("AI_CODING_AGENT")
    if "DOCUMENTATION" in objects and ("agent" in low or ai_marker or "review" in low):
        roles.add("DOCUMENTATION_AGENT_REVIEW")
    if re.search(r"\bagents?\b", low) and not roles:
        if any(x in low for x in ("software", "developer", "code", "coding")):
            roles.add("GENERAL_SOFTWARE_AGENT")
        else:
            roles.add("UNKNOWN_AGENT")

    # A hypothesis such as "AI coding agents finish work" identifies software
    # implementation even when it does not literally say "implement". This
    # inference is allowed only after explicit AI-coding-agent identity exists.
    if "AI_CODING_AGENT" in roles and re.search(r"\b(?:work|task|tasks|coding|code)\b", low) and not documentation_dominant:
        objects.add("SOFTWARE_IMPLEMENTATION")

    # Documentation dominance is semantic precedence, not deletion of raw text.
    # If implementation-looking tokens were only incidental mentions inside a doc
    # review, they cannot establish implementation identity.
    if documentation_dominant:
        objects.discard("SOFTWARE_IMPLEMENTATION")
        if not explicit_implementation_evidence:
            objects.discard("CODE_CHANGE")

    relationships: set[str] = set()
    if (
        "AI_CODING_AGENT" in roles
        and objects & {"SOFTWARE_IMPLEMENTATION","CODE_CHANGE","REFACTOR","FEATURE","BUG_FIX"}
        and not documentation_dominant
    ):
        relationships.add("AI_CODING_IMPLEMENTATION")
    if "BUILD_AGENT" in roles or objects & {"BUILD_INFRASTRUCTURE","DEPLOYMENT_PERMISSION"}:
        relationships.add("BUILD_OR_DEPLOYMENT_INFRASTRUCTURE")
    if "DOCUMENTATION" in objects:
        relationships.add("DOCUMENTATION_WORK")

    dominant_object = "DOCUMENTATION" if documentation_dominant else (
        "SOFTWARE_IMPLEMENTATION" if objects & {"SOFTWARE_IMPLEMENTATION","CODE_CHANGE","REFACTOR","FEATURE","BUG_FIX"} else None
    )
    return {
        "agent_roles": sorted(roles),
        "target_objects": sorted(objects),
        "workflow_relationships": sorted(relationships),
        "dominant_object": dominant_object,
        "documentation_dominant": documentation_dominant,
        "explicit_implementation_evidence": explicit_implementation_evidence,
    }

def semantic_profile(text: str) -> dict[str, Any]:
    terms = semantic_terms(text, include_lens_aliases=False)
    workflows = set(concept_groups(text, _WORKFLOW_GROUPS))
    low_text = clean(text).lower()
    # Operational workflow names contain highly polysemous tokens. Remove the
    # raw token-derived hits and re-add only when the bounded job relationship
    # itself is expressed. This prevents e.g. software "maintenance" from becoming
    # machine-downtime intelligence, or a customer "quote" from becoming an
    # industrial price-discovery workflow.
    for workflow_name, problem_dimension in _RELATION_GATED_OPERATIONAL_WORKFLOWS.items():
        workflows.discard(workflow_name)
        if any(re.search(pattern, low_text, re.IGNORECASE) for pattern in _GENERALIZED_PROBLEM_REGEXES[problem_dimension]):
            workflows.add(workflow_name)

    raw_problem_dimensions = set(concept_groups(text, _PROBLEM_DIMENSION_GROUPS))
    # Generalized exact jobs are phrase/relationship based, never single-token
    # triggers. Remove their lexical hits and re-add only when a bounded relation
    # pattern is actually present.
    raw_problem_dimensions -= set(_GENERALIZED_PROBLEM_REGEXES)
    for dimension, patterns in _GENERALIZED_PROBLEM_REGEXES.items():
        if any(re.search(pattern, low_text, re.IGNORECASE) for pattern in patterns):
            raw_problem_dimensions.add(dimension)
    # Prefer the more specific operational job when a generic repetitive-query
    # pattern is nested inside a specialized workflow.
    if "ECOMMERCE_SUPPORT_TOIL" in raw_problem_dimensions:
        raw_problem_dimensions.discard("REPETITIVE_INQUIRY_TOIL")
    if "SECURITY_QUESTIONNAIRE_TOIL" in raw_problem_dimensions:
        raw_problem_dimensions.discard("REPETITIVE_INQUIRY_TOIL")
        raw_problem_dimensions.discard("PROCUREMENT_SOURCING_JOB")

    domains = set(concept_groups(text, _DOMAIN_GROUPS))
    actors = set(concept_groups(text, _ACTOR_GROUPS))
    # Multi-token buyer identities should not depend on hyphenated tokenization.
    # This keeps "small business" / "small store" aligned without making the
    # generic word "business" a universal SMB signal.
    if re.search(r"\bsmall\s+(?:business(?:es)?|store|shop|merchant|salon|clinic|service business)\b", low_text):
        domains.add("SMB_SERVICE_OPERATIONS")
        actors.add("SMB_OPERATOR")
    operational_domains = {
        "MANUFACTURING_OPERATIONS", "INDUSTRIAL_ENERGY_OPERATIONS",
        "CONSTRUCTION_PROJECT_CONTROLS", "LOGISTICS_FREIGHT_OPERATIONS",
        "INDUSTRIAL_PROCUREMENT_MARKET", "ASSET_CONDITION_VALUE",
        "INDUSTRIAL_PROCESS_CONTROL", "ECOMMERCE_FINANCE_OPERATIONS",
    }
    if domains & operational_domains:
        # Polysemous words such as QA, output, instructions, audit and inventory
        # previously manufactured developer/education/security workflows inside
        # industrial hypotheses. Keep those concepts only when their native
        # context is explicitly present.
        if not re.search(r"\b(?:software|code|coding|developer|github|repository|repo)\b", low_text):
            domains.discard("SOFTWARE_ENGINEERING")
            actors.discard("ENGINEERING_BUYER")
            workflows.discard("SOFTWARE_QA")
            workflows.discard("AI_CODE_MAINTENANCE")
        if not re.search(r"\b(?:student|learner|school|exam|english|translation|vocabulary)\b", low_text):
            domains.discard("EDUCATION_EXAM")
            workflows.discard("LANGUAGE_OUTPUT_TRAINING")
        if not re.search(r"\b(?:ai|agent|agents|memory|remember|forget|persistent memory)\b", low_text):
            domains.discard("AI_AGENT_MEMORY")
            workflows.discard("MEMORY_PERSISTENCE")
        if not re.search(r"\b(?:security|compliance|privacy|soc2|soc 2|ciso)\b", low_text):
            workflows.discard("SECURITY_COMPLIANCE")
        if not re.search(r"\b(?:merchant|seller|shopify|ecommerce|e-commerce|marketplace)\b", low_text):
            workflows.discard("MERCHANT_OPERATIONS")
        if not re.search(r"\b(?:message|messages|messaging|chat|chatbot|reply|replies|inquiry|inquiries)\b|\bline\s+(?:app|oa|official|messaging|account)\b", low_text):
            workflows.discard("MESSAGING_AUTOMATION")

    problem_dimensions: list[str] = []
    for dimension in sorted(raw_problem_dimensions):
        required_workflows = _PROBLEM_DIMENSION_WORKFLOW_REQUIREMENTS.get(dimension)
        if required_workflows and not (workflows & required_workflows):
            continue
        problem_dimensions.append(dimension)
    specific_problem_terms = [t for t in terms if t not in _BROAD_CONTEXT_TERMS]
    identity = workflow_identity_profile(text)
    return {
        "terms": terms,
        "domains": sorted(domains),
        "workflows": sorted(workflows),
        "actors": sorted(actors),
        "problem_dimensions": problem_dimensions,
        "specific_problem_terms": specific_problem_terms,
        **identity,
        "has_han": bool(_HAN_RE.search(text or "")),
    }


def hypothesis_contract(text: str) -> dict[str, Any]:
    """Build the reusable Founder relevance contract for any domain.

    The contract is descriptive only. It separates actor/workflow/object/job identity
    from retrieval terms so search overlap can never become Market Truth by itself.
    """
    raw = clean(text)
    profile = semantic_profile(raw)
    return {
        "raw": raw,
        "actors": list(profile.get("actors") or []),
        "workflows": list(profile.get("workflows") or []),
        "objects": list(profile.get("target_objects") or []),
        "problem_jobs": list(profile.get("problem_dimensions") or []),
        "domains": list(profile.get("domains") or []),
        "specific_terms": list(profile.get("specific_problem_terms") or []),
        "market_truth_writes": 0,
    }


def _bounded_join(terms: list[str], *, max_terms: int, max_chars: int, max_bytes: int | None = None) -> str:
    chosen: list[str] = []
    for term in terms:
        candidate = " ".join([*chosen, term])
        if len(candidate) > max_chars:
            continue
        if max_bytes is not None and len(candidate.encode("utf-8")) > max_bytes:
            continue
        chosen.append(term)
        if len(chosen) >= max_terms:
            break
    return " ".join(chosen)


def compile_source_query(raw_query: str, source: str) -> dict[str, Any]:
    """Compile a natural-language Founder query into a source-safe query.

    Important: this is transport/query syntax adaptation, not evidence inference.
    It deliberately removes GitHub boolean-reserved tokens and keeps requests far
    below documented query-size limits.
    """
    raw = clean(raw_query)
    profile = semantic_profile(raw)
    # Transport query compilation may add falsification-lens aliases; they are
    # deliberately not part of profile["terms"] / evidence semantics.
    terms = semantic_terms(raw, include_lens_aliases=True)

    # Put decision-critical lens aliases early so long natural-language ideas do
    # not truncate the falsification intent.
    lens = [x for x in terms if x in {"good","enough","solved","native","budget","value","free","expensive","rare","switching","migration","security","procurement","discontinued","traction"}]
    core = [x for x in terms if x not in lens]
    low_value_transport = {"pdf","email","excel","cost","too","trust","failed","product","no","traction","manual","human-work"}
    distinctive = [x for x in core if x not in low_value_transport]

    src = source.upper()
    if src.startswith("GITHUB"):
        ordered = distinctive[:5] + lens + [x for x in core if x not in distinctive]
        ordered = [x for x in ordered if x.lower() not in {"and","or","not"}]
        final = _bounded_join(ordered, max_terms=12, max_chars=180)
        limit = "GITHUB_SEARCH_LT_256_CHARACTERS_AND_NO_BOOLEAN_OPERATOR_OVERFLOW"
    elif src.startswith("HACKER") or src == "HN":
        # HN/Algolia requires all query words by default. Use a compact blend of
        # problem identity + falsification lens instead of the full sentence.
        ordered = distinctive[:3] + lens[:3] + distinctive[3:]
        final = _bounded_join(ordered, max_terms=6, max_chars=160, max_bytes=240)
        limit = "ALGOLIA_QUERY_LT_512_BYTES"
    else:
        ordered = distinctive[:5] + lens + [x for x in core if x not in distinctive]
        final = _bounded_join(ordered, max_terms=12, max_chars=220, max_bytes=420)
        limit = "BOUNDED_SOURCE_QUERY"

    if not final:
        # Last-resort ASCII tokenization; fail visibly upstream if still empty.
        fallback = [x.lower() for x in _LATIN_RE.findall(raw) if x.lower() not in _GENERIC]
        final = _bounded_join(fallback, max_terms=8, max_chars=160)
    return {
        "raw_query": raw,
        "final_query": final,
        "source": src,
        "contract": limit,
        "profile": profile,
    }


SOURCE_PROFILE_REGISTRY: dict[str, dict[str, Any]] = {
    "DEVELOPER_TOOLING": {
        "observation_source_families": ["HACKER_NEWS", "STACK_OVERFLOW", "GITHUB_ISSUES", "GITHUB_REPOSITORIES", "GITHUB_DISCUSSIONS", "DEVELOPER_COMMUNITIES"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "DEVELOPER_DISCUSSION": ["HACKER_NEWS", "STACK_OVERFLOW", "GITHUB_ISSUES", "GITHUB_DISCUSSIONS", "DEVELOPER_COMMUNITIES"],
        },
        "recommended_source_families": ["HACKER_NEWS", "STACK_OVERFLOW", "GITHUB_ISSUES", "GITHUB_REPOSITORIES", "GITHUB_DISCUSSIONS"],
        "query_grammar": [],
    },
    "AGENCY_SERVICES": {
        "observation_source_families": [
            "AGENCY_SERVICE_PAGES", "AGENCY_REVIEWS", "FOUNDER_COMMUNITIES",
            "CONSULTING_JOB_POSTS", "PRODUCT_DISCOVERY_STRATEGY_PAGES", "RESEARCH_TOOL_REVIEWS",
        ],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "BUYER_VOICE": ["FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "AGENCY_REVIEWS"],
            "COMMERCIAL_WORKFLOW": ["AGENCY_SERVICE_PAGES", "CONSULTING_JOB_POSTS", "PRODUCT_DISCOVERY_STRATEGY_PAGES", "RESEARCH_TOOL_REVIEWS"],
        },
        "recommended_source_families": [
            "AGENCY_SERVICE_PAGES", "AGENCY_REVIEWS", "FOUNDER_COMMUNITIES",
            "CONSULTING_JOB_POSTS", "PRODUCT_DISCOVERY_STRATEGY_PAGES", "RESEARCH_TOOL_REVIEWS",
        ],
        "query_grammar": [
            'agency client performance reporting', 'multi platform client reporting dashboard',
            '"product discovery" agency', '"market validation" agency', '"product strategy" consultancy',
            '"customer research" agency', '"opportunity assessment" consultancy', '"validation sprint" studio',
            '"discovery workshop" product studio', '"market research" "AI agency"', '"client discovery" consultancy',
        ],
        "money_grammar": [
            "pricing", "retainer", "discovery sprint", "strategy engagement", "research package",
            "consulting hours", "product discovery fee", "validation workshop",
        ],
        "paid_dissatisfaction_grammar": [
            "manual research", "ChatGPT", "Perplexity", "Reddit", "Google", "research takes too long",
            "hard to trust", "need to verify", "client asked for evidence", "still manual",
        ],
    },
    "NONPROFIT_OPERATIONS": {
        "observation_source_families": [
            "NONPROFIT_COMMUNITIES", "ASSOCIATION_SOFTWARE_REVIEWS", "NONPROFIT_TECH_COMMUNITIES",
            "MESSAGING_PLATFORM_APP_REVIEWS", "NONPROFIT_OPERATIONS_FORUMS",
        ],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OPERATOR_VOICE": ["NONPROFIT_COMMUNITIES", "NONPROFIT_OPERATIONS_FORUMS", "NONPROFIT_TECH_COMMUNITIES"],
            "SOLUTION_WORKFLOW": ["ASSOCIATION_SOFTWARE_REVIEWS", "MESSAGING_PLATFORM_APP_REVIEWS", "NONPROFIT_SERVICE_PAGES"],
        },
        "recommended_source_families": [
            "NONPROFIT_COMMUNITIES", "ASSOCIATION_SOFTWARE_REVIEWS", "NONPROFIT_TECH_COMMUNITIES",
            "MESSAGING_PLATFORM_APP_REVIEWS", "NONPROFIT_OPERATIONS_FORUMS",
        ],
        "query_grammar": [
            '"nonprofit" messaging workflow', '"association" member messaging', '"LINE" nonprofit automation',
            '"charity" messaging operations', '"nonprofit" volunteer communication',
        ],
    },
    "EDUCATION_EXAM": {
        "observation_source_families": [
            "STUDENT_COMMUNITIES", "EXAM_PREP_COMMUNITIES", "TUTORING_FORUMS",
            "EDTECH_REVIEWS", "SCHOOL_LEARNING_COMMUNITIES",
        ],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "LEARNER_VOICE": ["STUDENT_COMMUNITIES", "EXAM_PREP_COMMUNITIES", "SCHOOL_LEARNING_COMMUNITIES"],
            "SOLUTION_CONTEXT": ["EDTECH_REVIEWS", "TUTORING_FORUMS"],
        },
        "recommended_source_families": [
            "STUDENT_COMMUNITIES", "EXAM_PREP_COMMUNITIES", "TUTORING_FORUMS",
            "EDTECH_REVIEWS", "SCHOOL_LEARNING_COMMUNITIES",
        ],
        "query_grammar": [
            '"Taiwan" English exam students', '"GSAT" English writing', '"學測" 英文 作文',
            '"English translation" Taiwan students', '"exam students" English output practice',
        ],
    },
    "ECOMMERCE_OPERATOR": {
        "observation_source_families": ["SHOPIFY_ECOSYSTEM", "SELLER_FORUMS", "MERCHANT_COMMUNITIES", "ECOMMERCE_APP_REVIEWS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OPERATOR_VOICE": ["SELLER_FORUMS", "MERCHANT_COMMUNITIES"],
            "SOLUTION_ECOSYSTEM": ["SHOPIFY_ECOSYSTEM", "ECOMMERCE_APP_REVIEWS"],
        },
        "recommended_source_families": ["SHOPIFY_ECOSYSTEM", "SELLER_FORUMS", "MERCHANT_COMMUNITIES", "ECOMMERCE_APP_REVIEWS"],
        "query_grammar": ["merchant workflow", "seller pain", "Shopify app review", "store operator workaround"],
    },
}


SOURCE_PROFILE_REGISTRY.update({
    "INDUSTRIAL_OPERATIONS": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","INDUSTRY_FEEDS","COMPANY_SERVICE_PAGES","VIDEO_DISCUSSIONS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OPERATOR_OR_ENGINEER_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","VIDEO_DISCUSSIONS"],
            "WORKFLOW_OR_MARKET_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","INDUSTRY_FEEDS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","INDUSTRY_FEEDS","COMPANY_SERVICE_PAGES"],
        "query_grammar": [
            "compressed air leak detection maintenance",
            "pcba first article inspection quality",
            "machine downtime logs root cause",
            "cnc thermal drift compensation",
            "wastewater dosing optimization",
            "industrial operator maintenance inspection",
        ],
    },
    "INDUSTRIAL_PROCUREMENT": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES","PUBLIC_MARKET_CONVERSATIONS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "BUYER_OR_OPERATOR_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","PUBLIC_MARKET_CONVERSATIONS"],
            "SUPPLIER_MARKET_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        "query_grammar": ["industrial procurement sourcing","supplier spare parts sourcing","raw material purchasing workflow"],
    },
    "CONSTRUCTION_CLAIMS": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "PROJECT_OPERATOR_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS"],
            "CLAIM_WORKFLOW_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS"],
        "query_grammar": ["construction change order claim evidence","contractor claim documentation","construction payment dispute evidence"],
    },
    "LOGISTICS_CLAIMS": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES","PUBLIC_MARKET_CONVERSATIONS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "SHIPPER_OR_OPERATOR_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","PUBLIC_MARKET_CONVERSATIONS"],
            "CLAIM_WORKFLOW_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS"],
        "query_grammar": ["freight cargo claim evidence","shipping damage claim recovery","carrier claim documentation"],
    },
    "ASSET_CONDITION_MARKET": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES","PUBLIC_MARKET_CONVERSATIONS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OWNER_OR_BUYER_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","PUBLIC_MARKET_CONVERSATIONS"],
            "VALUATION_MARKET_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS"],
        "query_grammar": ["used equipment condition valuation","asset health residual value","used machine condition resale"],
    },
    "CLAIM_RECOVERY_OPERATIONS": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES","PUBLIC_MARKET_CONVERSATIONS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OWNER_OR_OPERATOR_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","PUBLIC_MARKET_CONVERSATIONS"],
            "CLAIM_OR_WARRANTY_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        "query_grammar": ["warranty claim evidence recovery","asset defect claim inspection","commercial claim recovery workflow"],
    },
    "COST_AUDIT_RECOVERY": {
        "observation_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {
            "OPERATOR_OR_FINANCE_VOICE": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS"],
            "BILLING_OR_TARIFF_CONTEXT": ["GENERAL_WEB","INDUSTRY_NEWS","COMPANY_SERVICE_PAGES"],
        },
        "recommended_source_families": ["PROFESSIONAL_COMMUNITIES","DOMAIN_FORUMS","GENERAL_WEB","INDUSTRY_NEWS"],
        "query_grammar": [
            "energy tariff contract capacity audit",
            "hvac energy efficiency cost audit",
            "marketplace payout reconciliation audit",
            "billing overcharge recovery audit",
        ],
    },
})

SOURCE_PROFILE_REGISTRY.update({
    "SMB_SERVICE_OPERATIONS": {
        "observation_source_families": ["MERCHANT_COMMUNITIES","LOCAL_BUSINESS_REVIEWS","SERVICE_REVIEWS","FOUNDER_COMMUNITIES","MESSAGING_PLATFORM_APP_REVIEWS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {"OPERATOR_VOICE":["MERCHANT_COMMUNITIES","FOUNDER_COMMUNITIES","LOCAL_BUSINESS_REVIEWS"],"WORKFLOW_CONTEXT":["SERVICE_REVIEWS","MESSAGING_PLATFORM_APP_REVIEWS"]},
        "recommended_source_families": ["MERCHANT_COMMUNITIES","LOCAL_BUSINESS_REVIEWS","SERVICE_REVIEWS","FOUNDER_COMMUNITIES","MESSAGING_PLATFORM_APP_REVIEWS"],
        "query_grammar": ["small business customer inquiries","service business booking questions","merchant message response"],
    },
    "CREATOR_CONTENT": {
        "observation_source_families": ["CREATOR_COMMUNITIES","VIDEO_DISCUSSIONS","FOUNDER_COMMUNITIES","PRODUCT_REVIEWS_VIDEO","GENERAL_WEB"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {"CREATOR_VOICE":["CREATOR_COMMUNITIES","VIDEO_DISCUSSIONS"],"WORKFLOW_CONTEXT":["PRODUCT_REVIEWS_VIDEO","GENERAL_WEB"]},
        "recommended_source_families": ["CREATOR_COMMUNITIES","VIDEO_DISCUSSIONS","PRODUCT_REVIEWS_VIDEO","GENERAL_WEB"],
        "query_grammar": ["creator content repurposing","podcast short form repurpose","video clipping workflow"],
    },
    "B2B_SAAS_SECURITY": {
        "observation_source_families": ["FOUNDER_COMMUNITIES","DEVELOPER_COMMUNITIES","PROFESSIONAL_COMMUNITIES","COMPANY_SERVICE_PAGES","RESEARCH_TOOL_REVIEWS"],
        "min_observation_family_matches": 2,
        "required_observation_dimensions": {"OPERATOR_VOICE":["FOUNDER_COMMUNITIES","DEVELOPER_COMMUNITIES","PROFESSIONAL_COMMUNITIES"],"PROCUREMENT_CONTEXT":["COMPANY_SERVICE_PAGES","RESEARCH_TOOL_REVIEWS"]},
        "recommended_source_families": ["FOUNDER_COMMUNITIES","PROFESSIONAL_COMMUNITIES","COMPANY_SERVICE_PAGES","RESEARCH_TOOL_REVIEWS"],
        "query_grammar": ["security questionnaire SaaS","vendor security review questionnaire","enterprise procurement security"],
    },
})

_DEFAULT_FAST_SOURCE_FAMILIES = ("HACKER_NEWS", "STACK_OVERFLOW", "GITHUB_ISSUES", "GITHUB_REPOSITORIES")

_AGENCY_TERMS = {
    "agency", "agencies", "consultancy", "consultancies", "consulting", "product studio", "product studios",
    "market validation", "opportunity validation", "customer research", "client discovery", "product discovery",
    "product strategy", "discovery workshop", "validation sprint", "strategy engagement", "market research",
}
_ECOMMERCE_TERMS = {"ecommerce", "e-commerce", "shopify", "merchant", "seller", "store operator", "marketplace seller"}
_NONPROFIT_TERMS = {
    "nonprofit", "nonprofits", "non-profit", "non profit", "ngo", "charity", "association", "associations",
    "foundation", "volunteer organization", "member organization",
}
_EDUCATION_EXAM_TERMS = {
    "exam student", "exam students", "taiwan exam", "taiwan students", "gsat", "學測",
    "english output trainer", "english exam", "exam prep", "student writing", "student translation",
}


_INDUSTRIAL_OPERATION_TERMS = {"manufacturing","factory","factories","industrial","machine downtime","pcba","cnc","compressed air","compressed-air","hvac","wastewater","thermal drift","solar inspection","solar warranty","solar asset"}
_INDUSTRIAL_PROCUREMENT_TERMS = {"raw material","raw-material","raw materials","group purchasing","spare part","spare parts","spare-part","spare-parts","competitive bidding","industrial sourcing"}
_CONSTRUCTION_CLAIM_TERMS = {"construction claim","change order","change-order","contractor claim","construction evidence"}
_LOGISTICS_CLAIM_TERMS = {"freight claim","cargo claim","carrier claim","shipping claim","logistics claim"}
_ASSET_CONDITION_TERMS = {"used equipment","used industrial equipment","residual value","residual-value","used ev battery","battery health","condition passport","equipment condition"}
_INDUSTRIAL_COST_AUDIT_TERMS = {"industrial tariff","contract capacity","contract-capacity","payout audit","payout reconciliation","energy audit","hvac efficiency audit"}
_SMB_SERVICE_TERMS = {
    "small business","small businesses","smb","service business","service businesses","local business","local businesses",
    "customer inquiry","customer inquiries","restaurant","restaurants","restaurant owner","restaurant owners",
    "salon","salons","barbershop","barbershops","beauty studio","beauty studios","clinic","clinics",
    "food delivery","delivery platform","delivery platforms",
}
_CREATOR_TERMS = {"creator","creators","content repurposing","repurpose","repurposing","short-form","podcast","long-form","platform-specific"}
_B2B_SAAS_SECURITY_TERMS = {"b2b saas","b2b-saas","security questionnaire","security questionnaires","vendor security","enterprise security","procurement questionnaire","compliance questionnaire"}

def canonical_source_family(source: str) -> str:
    src = clean(source).upper()
    if src in {"HN", "HACKER_NEWS", "HACKER_NEWS_ALGOLIA"}:
        return "HACKER_NEWS"
    if src in {"STACK_OVERFLOW", "STACK_OVERFLOW_API", "STACKEXCHANGE", "STACK_EXCHANGE"}:
        return "STACK_OVERFLOW"
    if src == "GITHUB_SEARCH":
        return "GITHUB_SEARCH"
    aliases = {
        "BRAVE_WEB": "BRAVE_WEB",
        "GDELT_DOC": "GDELT_NEWS",
        "YOUTUBE_DATA_API": "YOUTUBE",
        "THREADS_API": "THREADS",
        "GREENHOUSE_PUBLIC_JOBS": "GREENHOUSE_JOBS",
        "LEVER_PUBLIC_JOBS": "LEVER_JOBS",
        "RSS_ATOM": "PUBLIC_FEEDS",
        "BLUESKY_PUBLIC_SEARCH": "BLUESKY",
        "X_RECENT_SEARCH": "X",
        "DISCOURSE_PUBLIC": "DISCOURSE",
        "MASTODON_SEARCH": "MASTODON",
        "LEMMY_PUBLIC": "LEMMY",
        "STACK_EXCHANGE_NETWORK": "STACK_EXCHANGE_NETWORK",
        "ASHBY_PUBLIC_JOBS": "ASHBY_JOBS",
        "GOOGLE_PLACES_REVIEWS": "GOOGLE_PLACES",
        "YELP_REVIEWS": "YELP",
    }
    return aliases.get(src, src)

def classify_source_profile(text: str) -> dict[str, str]:
    raw = clean(text)
    low = raw.lower()
    profile = semantic_profile(raw)
    domains = set(profile["domains"])
    # Buyer/problem observation domain takes precedence over implementation words
    # such as bot, automation, software, or workflow.
    if any(term in low for term in _NONPROFIT_TERMS):
        return {
            "problem_domain": "NONPROFIT_ASSOCIATION_OPERATIONS",
            "buyer_type": "NONPROFIT_ASSOCIATION_OPERATOR",
            "workflow_type": "MESSAGING_WORKFLOW_AUTOMATION" if any(x in low for x in ("line", "messag", "bot", "automation", "workflow")) else "NONPROFIT_OPERATIONS",
            "source_profile": "NONPROFIT_OPERATIONS",
        }
    if any(term in low for term in _EDUCATION_EXAM_TERMS) or ("student" in low and any(x in low for x in ("exam", "english", "writing", "translation"))):
        return {
            "problem_domain": "EDUCATION_EXAM",
            "buyer_type": "STUDENT_LEARNER",
            "workflow_type": "LANGUAGE_OUTPUT_TRAINING" if any(x in low for x in ("english", "writing", "translation", "output", "trainer")) else "EXAM_PREPARATION",
            "source_profile": "EDUCATION_EXAM",
        }
    if any(term in low for term in _AGENCY_TERMS):
        return {
            "problem_domain": "AGENCY_SERVICES",
            "buyer_type": "AI_AGENCY_PRODUCT_STUDIO" if ("ai agency" in low or "product studio" in low) else "AGENCY_CONSULTANCY",
            "workflow_type": "OPPORTUNITY_VALIDATION" if any(x in low for x in ("validation", "opportunity", "research", "discovery", "strategy")) else "PROFESSIONAL_SERVICE_WORKFLOW",
            "source_profile": "AGENCY_SERVICES",
        }
    if ("warranty" in low and any(x in low for x in ("solar", "asset", "equipment", "machine", "defect"))):
        return {
            "problem_domain": "INDUSTRIAL_ENERGY_OPERATIONS" if "solar" in low else "ASSET_CONDITION_VALUE",
            "buyer_type": "ASSET_OWNER_OPERATOR",
            "workflow_type": "CLAIM_EVIDENCE_RECOVERY",
            "source_profile": "CLAIM_RECOVERY_OPERATIONS",
        }
    if any(term in low for term in _CONSTRUCTION_CLAIM_TERMS):
        return {
            "problem_domain": "CONSTRUCTION_PROJECT_CONTROLS",
            "buyer_type": "CONSTRUCTION_OPERATOR",
            "workflow_type": "CLAIM_EVIDENCE_RECOVERY",
            "source_profile": "CONSTRUCTION_CLAIMS",
        }
    if any(term in low for term in _LOGISTICS_CLAIM_TERMS):
        return {
            "problem_domain": "LOGISTICS_FREIGHT_OPERATIONS",
            "buyer_type": "LOGISTICS_OPERATOR",
            "workflow_type": "CLAIM_EVIDENCE_RECOVERY",
            "source_profile": "LOGISTICS_CLAIMS",
        }
    if any(term in low for term in _ASSET_CONDITION_TERMS):
        return {
            "problem_domain": "ASSET_CONDITION_VALUE",
            "buyer_type": "ASSET_OWNER_OPERATOR",
            "workflow_type": "RESIDUAL_VALUE_ASSESSMENT",
            "source_profile": "ASSET_CONDITION_MARKET",
        }
    if any(x in low for x in ("scrap", "byproduct", "by-product")) and any(x in low for x in ("bid", "bidding", "price", "recycler", "sell", "buyer")):
        return {
            "problem_domain": "INDUSTRIAL_PROCUREMENT_MARKET",
            "buyer_type": "INDUSTRIAL_OPERATOR",
            "workflow_type": "MARKET_PRICE_DISCOVERY",
            "source_profile": "INDUSTRIAL_PROCUREMENT",
        }
    if any(term in low for term in _INDUSTRIAL_PROCUREMENT_TERMS):
        return {
            "problem_domain": "INDUSTRIAL_PROCUREMENT_MARKET",
            "buyer_type": "PROCUREMENT_OPERATOR",
            "workflow_type": "PROCUREMENT_SOURCING",
            "source_profile": "INDUSTRIAL_PROCUREMENT",
        }
    if any(term in low for term in _INDUSTRIAL_COST_AUDIT_TERMS):
        return {
            "problem_domain": "INDUSTRIAL_ENERGY_OPERATIONS" if any(x in low for x in ("tariff","capacity","energy","hvac")) else "ECOMMERCE_FINANCE_OPERATIONS",
            "buyer_type": "FACILITY_OPERATOR" if any(x in low for x in ("tariff","capacity","energy","hvac")) else "ECOMMERCE_OPERATOR",
            "workflow_type": "COST_AUDIT_RECOVERY",
            "source_profile": "COST_AUDIT_RECOVERY",
        }
    if any(term in low for term in _INDUSTRIAL_OPERATION_TERMS):
        return {
            "problem_domain": "MANUFACTURING_OPERATIONS",
            "buyer_type": "INDUSTRIAL_OPERATOR",
            "workflow_type": "INDUSTRIAL_OPERATIONS",
            "source_profile": "INDUSTRIAL_OPERATIONS",
        }
    if any(term in low for term in _B2B_SAAS_SECURITY_TERMS):
        return {
            "problem_domain": "B2B_SAAS_PROCUREMENT",
            "buyer_type": "B2B_SAAS_TEAM",
            "workflow_type": "SECURITY_QUESTIONNAIRE",
            "source_profile": "B2B_SAAS_SECURITY",
        }
    if any(term in low for term in _CREATOR_TERMS):
        return {
            "problem_domain": "CREATOR_CONTENT_OPERATIONS",
            "buyer_type": "CREATOR_OPERATOR",
            "workflow_type": "CONTENT_REPURPOSING",
            "source_profile": "CREATOR_CONTENT",
        }
    if any(term in low for term in _SMB_SERVICE_TERMS):
        return {
            "problem_domain": "SMB_SERVICE_OPERATIONS",
            "buyer_type": "SMB_OPERATOR",
            "workflow_type": (
                "ORDER_OPERATIONS"
                if any(x in low for x in ("order", "orders", "food delivery", "delivery platform", "delivery platforms"))
                else "CUSTOMER_INQUIRY_HANDLING"
            ),
            "source_profile": "SMB_SERVICE_OPERATIONS",
        }
    if any(term in low for term in _ECOMMERCE_TERMS):
        return {
            "problem_domain": "ECOMMERCE_OPERATOR",
            "buyer_type": "ECOMMERCE_OPERATOR",
            "workflow_type": "MERCHANT_OPERATIONS",
            "source_profile": "ECOMMERCE_OPERATOR",
        }
    if domains & {"SOFTWARE_ENGINEERING", "AI_AGENT_MEMORY"}:
        return {
            "problem_domain": sorted(domains & {"SOFTWARE_ENGINEERING", "AI_AGENT_MEMORY"})[0],
            "buyer_type": "DEVELOPER_OR_ENGINEERING_TEAM",
            "workflow_type": "DEVELOPER_TOOLING",
            "source_profile": "DEVELOPER_TOOLING",
        }
    domain = sorted(domains)[0] if domains else "UNCLASSIFIED"
    return {
        "problem_domain": domain,
        "buyer_type": "UNKNOWN",
        "workflow_type": "UNKNOWN",
        "source_profile": "DOMAIN_SPECIFIC_OTHER" if domain != "UNCLASSIFIED" else "UNCLASSIFIED",
    }

def _grammar_match_score(raw: str, grammar: str) -> tuple[int, int]:
    """Score a retrieval grammar by hypothesis-specific lexical overlap.

    Generic profile boilerplate is deliberately not enough. The second query is
    emitted only when at least one meaningful grammar token occurs in the Founder
    hypothesis. This prevents subtype drift such as an e-commerce payout audit
    receiving an industrial-tariff query merely because both share the word audit.
    """
    raw_terms = set(semantic_terms(raw, include_lens_aliases=False))
    grammar_terms = set(semantic_terms(grammar, include_lens_aliases=False))
    weak = {
        "audit", "workflow", "operator", "industrial", "problem", "service",
        "business", "customer", "client", "content", "market", "evidence",
        "recovery", "support", "review", "agency", "agencies", "student", "students",
        "nonprofit", "creator", "merchant", "saas", "industrial",
    }
    strong_overlap = (raw_terms & grammar_terms) - weak
    all_overlap = raw_terms & grammar_terms
    return len(strong_overlap), len(all_overlap)


def source_profile_queries(text: str) -> list[str]:
    """Return up to two compact executed queries tied to the Founder hypothesis.

    The first query is hypothesis-derived. A second profile grammar is allowed only
    when it has real lexical support in the hypothesis; registry ordering cannot
    select an unrelated subtype. Retrieval grammar never becomes evidence.
    """
    raw = clean(text)
    cls = classify_source_profile(raw)
    profile = cls["source_profile"]
    terms = [t for t in semantic_terms(raw) if t not in _BROAD_CONTEXT_TERMS]
    reg = SOURCE_PROFILE_REGISTRY.get(profile, {})
    grammar = [clean(x).replace('"', "") for x in (reg.get("query_grammar") or []) if clean(x)]
    anchors: dict[str, list[str]] = {
        "DEVELOPER_TOOLING": ["developer", "workflow"],
        "EDUCATION_EXAM": ["student", "english", "exam"],
        "SMB_SERVICE_OPERATIONS": ["small business", "customer inquiry"],
        "AGENCY_SERVICES": ["agency", "client workflow"],
        "ECOMMERCE_OPERATOR": ["ecommerce", "merchant support"],
        "CREATOR_CONTENT": ["creator", "content workflow"],
        "NONPROFIT_OPERATIONS": ["nonprofit", "messaging workflow"],
        "B2B_SAAS_SECURITY": ["b2b saas", "security procurement"],
        "INDUSTRIAL_OPERATIONS": ["industrial", "operator workflow"],
        "INDUSTRIAL_PROCUREMENT": ["industrial", "procurement sourcing"],
        "CONSTRUCTION_CLAIMS": ["construction", "claim evidence"],
        "LOGISTICS_CLAIMS": ["freight", "claim evidence"],
        "ASSET_CONDITION_MARKET": ["asset", "condition value"],
        "CLAIM_RECOVERY_OPERATIONS": ["claim", "evidence recovery"],
        "COST_AUDIT_RECOVERY": ["audit", "recovery workflow"],
    }
    core = list(dict.fromkeys(terms))[:7]
    base_parts = [*core, *anchors.get(profile, [])]
    base = " ".join(dict.fromkeys(base_parts))
    queries: list[str] = []
    if base:
        q = _bounded_join(base.split(), max_terms=10, max_chars=180, max_bytes=300)
        if q:
            queries.append(q)

    if grammar and core:
        scored = sorted(
            ((_grammar_match_score(raw, g), -idx, g) for idx, g in enumerate(grammar)),
            reverse=True,
        )
        best_score, _, best_grammar = scored[0]
        # Require a strong subtype anchor, or at least two total overlapping terms.
        # A lone generic word such as "audit" cannot emit a second query.
        if best_score[0] >= 1 or best_score[1] >= 2:
            second = " ".join(dict.fromkeys([*core[:4], *best_grammar.split()]))
            second = _bounded_join(second.split(), max_terms=10, max_chars=180, max_bytes=300)
            if second and second not in queries:
                queries.append(second)
    return queries[:2]


def source_fit_for_problem_class(text: str, *, configured_source_families: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    cls = classify_source_profile(text)
    source_profile = cls["source_profile"]
    reg = SOURCE_PROFILE_REGISTRY.get(source_profile, {})
    configured_input = _DEFAULT_FAST_SOURCE_FAMILIES if configured_source_families is None else configured_source_families
    configured = [canonical_source_family(x) for x in configured_input]
    configured = list(dict.fromkeys(x for x in configured if x))
    required = list(reg.get("observation_source_families") or [])
    matched = [x for x in configured if x in set(required)]
    min_matches = int(reg.get("min_observation_family_matches") or (1 if required else 0))
    dimension_contract = reg.get("required_observation_dimensions") if isinstance(reg.get("required_observation_dimensions"), Mapping) else {}
    dimension_matches: dict[str, list[str]] = {}
    for dimension, families in dimension_contract.items():
        allowed = {str(x).upper() for x in (families or [])}
        dimension_matches[str(dimension)] = [x for x in configured if x in allowed]
    dimensions_complete = all(bool(v) for v in dimension_matches.values()) if dimension_matches else True
    if not required:
        fit_state = "UNKNOWN"
        legacy_fit = "SOURCE_FIT_UNKNOWN"
        reason = "No adequate observation-source family contract is defined for this buyer/problem class."
    elif len(matched) >= min_matches and dimensions_complete:
        fit_state = "SUFFICIENT"
        legacy_fit = "SUFFICIENT_FOR_BOUNDED_OBSERVATION_PROBE"
        reason = "The actually configured source families cover each required buyer/problem observation dimension for a bounded first-pass probe."
    else:
        fit_state = "INSUFFICIENT"
        legacy_fit = "INSUFFICIENT_FOR_PROBLEM_CLASS"
        missing_dims = [k for k,v in dimension_matches.items() if not v]
        reason = "The actually configured source families do not cover the buyer/problem observation domain well enough to interpret zero traces as market absence."
        if missing_dims:
            reason += " Missing observation dimensions: " + ", ".join(missing_dims) + "."
    return {
        **cls,
        "fit": legacy_fit,
        "source_fit_state": fit_state,
        "source_fit_reason": reason,
        "reason": reason,
        "problem_domains": semantic_profile(text)["domains"],
        "configured_source_profile": "ACTUAL_CONFIGURED_SOURCE_FAMILIES",
        "configured_source_families": configured,
        "adequate_observation_source_families": required,
        "matched_observation_source_families": matched,
        "minimum_observation_family_matches": min_matches,
        "required_observation_dimensions": {str(k): list(v or []) for k,v in dimension_contract.items()},
        "matched_observation_dimensions": dimension_matches,
        "observation_dimensions_complete": dimensions_complete,
        "recommended_source_families": list(reg.get("recommended_source_families") or (["DOMAIN_SPECIFIC_BUYER_WORKFLOW_SOURCES"] if source_profile not in {"DEVELOPER_TOOLING"} else [])),
        "profile_query_grammar": list(reg.get("query_grammar") or []),
        "money_query_grammar": list(reg.get("money_grammar") or []),
        "paid_dissatisfaction_query_grammar": list(reg.get("paid_dissatisfaction_grammar") or []),
        "market_truth_writes": 0,
        "truth_boundary": "SOURCE_FIT_DEPENDS_ON_ACTUAL_CONFIGURED_SOURCE_FAMILY_COVERAGE_OF_BUYER_PROBLEM_OBSERVATION_DOMAIN;_ROUTING_METADATA_CANNOT_WRITE_C01_C14_OR_CREATE_MARKET_TRUTH",
    }

