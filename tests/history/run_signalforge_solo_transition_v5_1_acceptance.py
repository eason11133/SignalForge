from __future__ import annotations

from pathlib import Path

from processors.solo_transition_opportunity import assess_solo_transition


def assess(candidate, claims, company="CAN_DO"):
    return assess_solo_transition(
        candidate,
        claim_states=claims,
        company_reality={"overall": company},
        commercial_reality={},
        attention={"attention_score": 99},
    )


def main() -> int:
    print("=" * 116)
    print("SIGNALFORGE SOLO TRANSITION V5.1 — STATIC + LIVE-MERGE ACCEPTANCE")
    print("=" * 116)
    print("No DB writes. No crawler. No LLM. No fake market validation.\n")

    old_claims = {
        "C03": "SUPPORTED", "C05": "SUPPORTED", "C06": "SUPPORTED",
        "C07": "INSUFFICIENT", "C09": "SUPPORTED", "C11": "INSUFFICIENT", "C12": "UNKNOWN",
    }
    negatives = [
        {
            "name": "CURRENT_TOP_1_BROAD_AI_RELIABILITY",
            "candidate": {
                "title": "AI 模型輸出不可靠",
                "problem_statement": "AI model does not produce reliable outputs",
                "actor": "specific user/group or unclear",
                "task": "use AI for coding assistance",
                "object": "AI model",
                "failure_mode": "unreliable outputs",
                "consequence": "wasted time and frustration with AI performance",
                "buyer_context": "unclear",
                "workaround": "none mentioned",
            },
        },
        {
            "name": "CURRENT_TOP_2_FRONTIER_MIX",
            "candidate": {
                "title": "AI 模型錯誤假設導致輸出偏差",
                "problem_statement": "AI model assumptions lead to incorrect outputs",
                "actor": "specific user/group or unclear",
                "task": "run AI models locally",
                "object": "ROCm SGLang DeepSeek",
                "failure_mode": "incorrect output on MI355X distributed inference",
                "consequence": "wasted time and confusion due to incorrect reporting",
                "buyer_context": "unclear",
                "workaround": "none mentioned",
            },
        },
        {
            "name": "CURRENT_TOP_3_PHENOMENON",
            "candidate": {
                "title": "初階工程師過度依賴工具除錯",
                "problem_statement": "over-reliance on tools for debugging among junior engineers",
                "actor": "junior engineers",
                "task": "debugging code",
                "object": "AI debugging tools",
                "failure_mode": "over-reliance on tools for debugging",
                "consequence": "potential skill gap between junior and experienced engineers",
                "buyer_context": "unclear",
                "workaround": "commit to learning and practicing debugging skills",
            },
        },
    ]

    failed = []
    for item in negatives:
        result = assess(item["candidate"], old_claims)
        ok = result["classification"] == "RESEARCH_THEME" and not result["founder_surface_eligible"]
        print(
            f"NEGATIVE {item['name']}: {'PASS' if ok else 'FAIL'} | "
            f"shape={result['problem_shape']} class={result['classification']} solo={result['solo_fit']}"
        )
        if not ok:
            failed.append(item["name"])

    # Structural positive only. It proves the gate can pass a small, concrete transition-gap structure.
    # It is not evidence that this example is a real market opportunity.
    positive = {
        "title": "Small restaurant staff manually re-enter new-channel orders into POS",
        "problem_statement": "small restaurant operators manually re-enter LINE delivery orders into POS after a new delivery channel becomes common",
        "actor": "small independent restaurant operators",
        "task": "transfer incoming LINE delivery orders into POS",
        "object": "LINE orders and POS",
        "failure_mode": "staff manually re-enter each order and make duplicate-entry mistakes",
        "consequence": "2 hours of staff labor per day and delayed order handling",
        "buyer_context": "independent restaurant owner paying staff",
        "workaround": "copy each order from LINE into POS by hand",
    }
    strong_claims = {
        "C03": "SUPPORTED", "C05": "SUPPORTED", "C06": "SUPPORTED",
        "C07": "SUPPORTED", "C09": "SUPPORTED", "C11": "SUPPORTED", "C12": "SUPPORTED",
    }
    pos = assess(positive, strong_claims)
    pos_ok = pos["classification"] in {"SOLO_INVESTIGATE", "SOLO_VALIDATE"} and pos["founder_surface_eligible"]
    print(
        f"STRUCTURAL_POSITIVE: {'PASS' if pos_ok else 'FAIL'} | "
        f"class={pos['classification']} transition={pos['transition_gap']} econ={pos['economic_necessity']} solo={pos['solo_fit']}"
    )
    if not pos_ok:
        failed.append("STRUCTURAL_POSITIVE")

    markers = {
        "processors/opportunity_decision.py": [
            "gate_existing_decision", "opportunity-decision-v18-solo-transition-gated", "solo_transition",
        ],
        "processors/company_reality.py": [
            "GPU_KERNEL_ENGINEERING", "MODEL_RESEARCH", "generic AI/API code is not proof",
        ],
        "processors/problem_candidate_engine.py": [
            "fingerprint_is_founder_unit", "SAME actor/workflow/failure", "specificity >= 68",
            "candidate-discovery-v5-incremental-solo-transition", "incremental_only", "_incremental_candidates",
        ],
        "processors/problem_discovery_refresh.py": [
            "problem-discovery-refresh-v3-incremental-solo-transition", "incremental_only=True", "enrichment_batch",
        ],
        "processors/opportunity_engine.py": [
            "opportunity_unit_ready", "transition_gap", "never normalize upward to an industry-wide theme",
        ],
        "processors/founder_daily_surface.py": [
            "founder_surface_eligible", "research_themes_parked", "empty_is_valid",
        ],
        "dashboard/src/pages/OpportunityRadar.tsx": [
            "Founder intelligence", "今天的 Solo Founder 商機", "card.solo_transition", "Research themes",
        ],
        "api/routes/signalforge.py": [
            "opportunity_candidate_compact", ".limit(24)",
        ],
    }
    for rel, required in markers.items():
        text = Path(rel).read_text(encoding="utf-8")
        if rel == "api/routes/signalforge.py":
            route_block = text[text.index("def _solution_names"):text.index("def _competitive_names")]
            ok = all(marker in text for marker in required) and '"repo"' not in route_block and '"vendor"' not in route_block
        else:
            ok = all(marker in text for marker in required)
        print(f"CONTRACT {rel}: {'PASS' if ok else 'FAIL'}")
        if not ok:
            failed.append(rel)

    if failed:
        print("\nFAIL:", ", ".join(failed))
        return 1

    print("\nSIGNALFORGE_SOLO_TRANSITION_V5_1_STATIC_PASS")
    print("Live incremental discovery + current Founder UI were preserved during the merge.")
    print("Market outcome remains UNVALIDATED. Next acceptance is the real Founder Top-3/Top-10 after rebuild.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
