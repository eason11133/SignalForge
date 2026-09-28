# Repository Presentation Audit

This audit records the public-repository cleanup performed for the current SignalForge main branch.

## Scope

The cleanup changes repository presentation only. It does not change SignalForge research logic, evidence semantics, tracking behavior, market-truth boundaries, or runtime algorithms.

Core invariants remain:

- evidence-first research infrastructure
- relevance != validation
- search failed != no market
- repeated behavior != verdict
- counterevidence is preserved
- market_truth_writes = 0
- Founder / ChatGPT owns final analysis and judgment

## Root-script audit

Root Python files audited: **173**

Classification used:

- **Production / runtime / import contract**: kept at root.
- **Canonical current checks**: kept at root so their existing standalone path assumptions remain valid.
- **Historical acceptance / regression / replay / benchmark evidence**: moved unchanged to `tests/history/`.
- **Historical experiment / audit / migration utilities**: moved unchanged to `scripts/history/`.

### Deliberately retained root Python files

- `init_db.py`
- `main.py`
- `run_founder_daily_radar.py`
- `run_radar_cycle.py`
- `run_scrapers.py`
- `run_scrapers_bg.py`
- `run_signalforge_behavior_tracking_v1_regression.py`
- `run_signalforge_brain_v2_acceptance.py`
- `run_signalforge_brain_v2_refresh.py`
- `run_signalforge_dockerless_local_mode_regression.py`
- `run_signalforge_dockerless_readpath_fix_v1_regression.py`
- `run_signalforge_final_portfolio_v1_1_regression.py`
- `run_signalforge_idea_research.py`
- `run_signalforge_research_backlog_route_smoke.py`
- `run_signalforge_runtime_worker.py`
- `run_signalforge_single_item_persistence_regression.py`
- `run_signalforge_tracking_research_persistence_v2_5_3_smoke.py`
- `signalforge_mcp_server.py`
- `spending_tracker.py`

Important dependency findings:

- `api/main.py` imports `run_scrapers_bg.py`.
- `processors/signalforge_runtime.py` resolves `run_signalforge_runtime_worker.py` by repository-root path.
- `processors/signalforge_brain_v2_runtime.py` resolves `run_signalforge_brain_v2_refresh.py` from repository root.
- `processors/signalforge_brain_v2_benchmark.py` imports `fixture_snapshot` from `run_signalforge_brain_v2_acceptance.py`.

Those files were intentionally not moved.

## Historical scripts moved

### tests/history

- `run_signalforge_benchmark_decontamination_u25.py` -> `tests/history/run_signalforge_benchmark_decontamination_u25.py`
- `run_signalforge_brain_v2_benchmark.py` -> `tests/history/run_signalforge_brain_v2_benchmark.py`
- `run_signalforge_brain_v2_integration_acceptance.py` -> `tests/history/run_signalforge_brain_v2_integration_acceptance.py`
- `run_signalforge_chatgpt_integration_part5_acceptance.py` -> `tests/history/run_signalforge_chatgpt_integration_part5_acceptance.py`
- `run_signalforge_floor60_acceptance.py` -> `tests/history/run_signalforge_floor60_acceptance.py`
- `run_signalforge_founder_first_product_ui_acceptance.py` -> `tests/history/run_signalforge_founder_first_product_ui_acceptance.py`
- `run_signalforge_founder_idea_loop_part1_acceptance.py` -> `tests/history/run_signalforge_founder_idea_loop_part1_acceptance.py`
- `run_signalforge_founder_memory_part2_acceptance.py` -> `tests/history/run_signalforge_founder_memory_part2_acceptance.py`
- `run_signalforge_founder_observation_quality_repair_acceptance.py` -> `tests/history/run_signalforge_founder_observation_quality_repair_acceptance.py`
- `run_signalforge_founder_observation_quality_repair_live_acceptance.py` -> `tests/history/run_signalforge_founder_observation_quality_repair_live_acceptance.py`
- `run_signalforge_founder_ux_architecture_phase1_acceptance.py` -> `tests/history/run_signalforge_founder_ux_architecture_phase1_acceptance.py`
- `run_signalforge_founder_ux_phase1_contract_closure_acceptance.py` -> `tests/history/run_signalforge_founder_ux_phase1_contract_closure_acceptance.py`
- `run_signalforge_full_system_live_efficiency_r6_acceptance.py` -> `tests/history/run_signalforge_full_system_live_efficiency_r6_acceptance.py`
- `run_signalforge_full_system_operating_loop_r5_acceptance.py` -> `tests/history/run_signalforge_full_system_operating_loop_r5_acceptance.py`
- `run_signalforge_full_system_postproduction_durability_r9_acceptance.py` -> `tests/history/run_signalforge_full_system_postproduction_durability_r9_acceptance.py`
- `run_signalforge_full_system_rebase_acceptance.py` -> `tests/history/run_signalforge_full_system_rebase_acceptance.py`
- `run_signalforge_full_system_runtime_durability_r7_acceptance.py` -> `tests/history/run_signalforge_full_system_runtime_durability_r7_acceptance.py`
- `run_signalforge_full_system_strategic_routing_r8_acceptance.py` -> `tests/history/run_signalforge_full_system_strategic_routing_r8_acceptance.py`
- `run_signalforge_historical_replay.py` -> `tests/history/run_signalforge_historical_replay.py`
- `run_signalforge_idea_research_benchmark.py` -> `tests/history/run_signalforge_idea_research_benchmark.py`
- `run_signalforge_live_founder_workflow_closure_acceptance.py` -> `tests/history/run_signalforge_live_founder_workflow_closure_acceptance.py`
- `run_signalforge_live_intelligence_semantic_closure_acceptance.py` -> `tests/history/run_signalforge_live_intelligence_semantic_closure_acceptance.py`
- `run_signalforge_live_source_adapter_acceptance.py` -> `tests/history/run_signalforge_live_source_adapter_acceptance.py`
- `run_signalforge_m13_acceptance.py` -> `tests/history/run_signalforge_m13_acceptance.py`
- `run_signalforge_m14_acceptance.py` -> `tests/history/run_signalforge_m14_acceptance.py`
- `run_signalforge_m15_acceptance.py` -> `tests/history/run_signalforge_m15_acceptance.py`
- `run_signalforge_m16_acceptance.py` -> `tests/history/run_signalforge_m16_acceptance.py`
- `run_signalforge_m17_acceptance.py` -> `tests/history/run_signalforge_m17_acceptance.py`
- `run_signalforge_m18_acceptance.py` -> `tests/history/run_signalforge_m18_acceptance.py`
- `run_signalforge_m18_go_live_check.py` -> `tests/history/run_signalforge_m18_go_live_check.py`
- `run_signalforge_market_execution_learning_part6_acceptance.py` -> `tests/history/run_signalforge_market_execution_learning_part6_acceptance.py`
- `run_signalforge_market_execution_learning_part6_durability_acceptance.py` -> `tests/history/run_signalforge_market_execution_learning_part6_durability_acceptance.py`
- `run_signalforge_money_trail_product_acceptance.py` -> `tests/history/run_signalforge_money_trail_product_acceptance.py`
- `run_signalforge_opportunity_decision_part4_acceptance.py` -> `tests/history/run_signalforge_opportunity_decision_part4_acceptance.py`
- `run_signalforge_part4_founder_acceptance_closure.py` -> `tests/history/run_signalforge_part4_founder_acceptance_closure.py`
- `run_signalforge_part5_durability_closure_acceptance.py` -> `tests/history/run_signalforge_part5_durability_closure_acceptance.py`
- `run_signalforge_part6_semantic_closure_acceptance.py` -> `tests/history/run_signalforge_part6_semantic_closure_acceptance.py`
- `run_signalforge_parts1_3_founder_acceptance_closure.py` -> `tests/history/run_signalforge_parts1_3_founder_acceptance_closure.py`
- `run_signalforge_production_focus_r2_acceptance.py` -> `tests/history/run_signalforge_production_focus_r2_acceptance.py`
- `run_signalforge_quality_progression_acceptance.py` -> `tests/history/run_signalforge_quality_progression_acceptance.py`
- `run_signalforge_r8_idea_research_chinese_bridge_fix5_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_chinese_bridge_fix5_acceptance.py`
- `run_signalforge_r8_idea_research_dashboard_cutover_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_dashboard_cutover_acceptance.py`
- `run_signalforge_r8_idea_research_final_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_final_acceptance.py`
- `run_signalforge_r8_idea_research_fix2_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_fix2_acceptance.py`
- `run_signalforge_r8_idea_research_fix3_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_fix3_acceptance.py`
- `run_signalforge_r8_idea_research_fix4_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_fix4_acceptance.py`
- `run_signalforge_r8_idea_research_fix5_e2e_replay.py` -> `tests/history/run_signalforge_r8_idea_research_fix5_e2e_replay.py`
- `run_signalforge_r8_idea_research_multidomain_fix5_replay.py` -> `tests/history/run_signalforge_r8_idea_research_multidomain_fix5_replay.py`
- `run_signalforge_r8_idea_research_recall_fix5_acceptance.py` -> `tests/history/run_signalforge_r8_idea_research_recall_fix5_acceptance.py`
- `run_signalforge_research_backlog_v1_2_batch_contract_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_2_batch_contract_smoke.py`
- `run_signalforge_research_backlog_v1_2_live_import_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_2_live_import_smoke.py`
- `run_signalforge_research_backlog_v1_2_route_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_2_route_smoke.py`
- `run_signalforge_research_backlog_v1_3_continuous_autopilot_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_3_continuous_autopilot_smoke.py`
- `run_signalforge_research_backlog_v1_4_recovery_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_4_recovery_smoke.py`
- `run_signalforge_research_backlog_v1_4_startup_smoke.py` -> `tests/history/run_signalforge_research_backlog_v1_4_startup_smoke.py`
- `run_signalforge_research_backlog_v1_acceptance.py` -> `tests/history/run_signalforge_research_backlog_v1_acceptance.py`
- `run_signalforge_runtime_isolation_r3_acceptance.py` -> `tests/history/run_signalforge_runtime_isolation_r3_acceptance.py`
- `run_signalforge_runtime_telemetry_r4_acceptance.py` -> `tests/history/run_signalforge_runtime_telemetry_r4_acceptance.py`
- `run_signalforge_solo_transition_v5_1_acceptance.py` -> `tests/history/run_signalforge_solo_transition_v5_1_acceptance.py`
- `run_signalforge_source_expansion_wave1_acceptance.py` -> `tests/history/run_signalforge_source_expansion_wave1_acceptance.py`
- `run_signalforge_source_expansion_wave2_acceptance.py` -> `tests/history/run_signalforge_source_expansion_wave2_acceptance.py`
- `run_signalforge_source_expansion_wave3_acceptance.py` -> `tests/history/run_signalforge_source_expansion_wave3_acceptance.py`
- `run_signalforge_source_expansion_wave4_acceptance.py` -> `tests/history/run_signalforge_source_expansion_wave4_acceptance.py`
- `run_signalforge_source_fit_playbook_closure_acceptance.py` -> `tests/history/run_signalforge_source_fit_playbook_closure_acceptance.py`
- `run_signalforge_transition_discovery_v5_2_acceptance.py` -> `tests/history/run_signalforge_transition_discovery_v5_2_acceptance.py`
- `run_signalforge_trust_falsification_part3_acceptance.py` -> `tests/history/run_signalforge_trust_falsification_part3_acceptance.py`
- `run_signalforge_u14_local_acceptance.py` -> `tests/history/run_signalforge_u14_local_acceptance.py`
- `run_signalforge_u15_local_acceptance.py` -> `tests/history/run_signalforge_u15_local_acceptance.py`
- `run_signalforge_u16_local_acceptance.py` -> `tests/history/run_signalforge_u16_local_acceptance.py`
- `run_signalforge_u17_local_acceptance.py` -> `tests/history/run_signalforge_u17_local_acceptance.py`
- `run_signalforge_u18_local_acceptance.py` -> `tests/history/run_signalforge_u18_local_acceptance.py`
- `run_signalforge_u19_local_acceptance.py` -> `tests/history/run_signalforge_u19_local_acceptance.py`
- `run_signalforge_u20_local_acceptance.py` -> `tests/history/run_signalforge_u20_local_acceptance.py`
- `run_signalforge_u21_local_acceptance.py` -> `tests/history/run_signalforge_u21_local_acceptance.py`
- `run_signalforge_u23_local_acceptance.py` -> `tests/history/run_signalforge_u23_local_acceptance.py`
- `run_signalforge_u24_local_acceptance.py` -> `tests/history/run_signalforge_u24_local_acceptance.py`
- `run_signalforge_u25_local_acceptance.py` -> `tests/history/run_signalforge_u25_local_acceptance.py`
- `run_signalforge_u26_1_local_acceptance.py` -> `tests/history/run_signalforge_u26_1_local_acceptance.py`
- `run_signalforge_u26_local_acceptance.py` -> `tests/history/run_signalforge_u26_local_acceptance.py`
- `run_signalforge_u27_local_acceptance.py` -> `tests/history/run_signalforge_u27_local_acceptance.py`
- `run_signalforge_u28_local_acceptance.py` -> `tests/history/run_signalforge_u28_local_acceptance.py`
- `run_signalforge_usable_beta_v1_1_acceptance.py` -> `tests/history/run_signalforge_usable_beta_v1_1_acceptance.py`
- `run_signalforge_usable_beta_v1_acceptance.py` -> `tests/history/run_signalforge_usable_beta_v1_acceptance.py`
- `run_signalforge_usable_beta_v1_live_acceptance.py` -> `tests/history/run_signalforge_usable_beta_v1_live_acceptance.py`

### scripts/history

- `add_ai_spend_dashboard.py` -> `scripts/history/add_ai_spend_dashboard.py`
- `audit_pain_point_clusters.py` -> `scripts/history/audit_pain_point_clusters.py`
- `create_signalforge_structural_checkpoint.py` -> `scripts/history/create_signalforge_structural_checkpoint.py`
- `create_signalforge_validation_experiment.py` -> `scripts/history/create_signalforge_validation_experiment.py`
- `fix_dashboard_truth.py` -> `scripts/history/fix_dashboard_truth.py`
- `rebuild_signalforge_solo_daily.py` -> `scripts/history/rebuild_signalforge_solo_daily.py`
- `record_signalforge_market_result.py` -> `scripts/history/record_signalforge_market_result.py`
- `record_signalforge_structural_checkpoint.py` -> `scripts/history/record_signalforge_structural_checkpoint.py`
- `run_signalforge_adaptive_evidence_u11.py` -> `scripts/history/run_signalforge_adaptive_evidence_u11.py`
- `run_signalforge_boundary_diagnostic_u26_1.py` -> `scripts/history/run_signalforge_boundary_diagnostic_u26_1.py`
- `run_signalforge_boundary_sentinel_u26.py` -> `scripts/history/run_signalforge_boundary_sentinel_u26.py`
- `run_signalforge_continuous_research_u10.py` -> `scripts/history/run_signalforge_continuous_research_u10.py`
- `run_signalforge_criteria_first_symmetric_u27.py` -> `scripts/history/run_signalforge_criteria_first_symmetric_u27.py`
- `run_signalforge_discovery_coverage_u19.py` -> `scripts/history/run_signalforge_discovery_coverage_u19.py`
- `run_signalforge_discovery_family_u20.py` -> `scripts/history/run_signalforge_discovery_family_u20.py`
- `run_signalforge_discovery_foundation_u23.py` -> `scripts/history/run_signalforge_discovery_foundation_u23.py`
- `run_signalforge_evidence_adjudication_u17.py` -> `scripts/history/run_signalforge_evidence_adjudication_u17.py`
- `run_signalforge_evidence_gap_voi_u13.py` -> `scripts/history/run_signalforge_evidence_gap_voi_u13.py`
- `run_signalforge_founder_directed_u15.py` -> `scripts/history/run_signalforge_founder_directed_u15.py`
- `run_signalforge_founder_thesis_control_u14.py` -> `scripts/history/run_signalforge_founder_thesis_control_u14.py`
- `run_signalforge_founder_usable_u5.py` -> `scripts/history/run_signalforge_founder_usable_u5.py`
- `run_signalforge_founder_usable_u6.py` -> `scripts/history/run_signalforge_founder_usable_u6.py`
- `run_signalforge_founder_usable_u7.py` -> `scripts/history/run_signalforge_founder_usable_u7.py`
- `run_signalforge_founder_usable_u8.py` -> `scripts/history/run_signalforge_founder_usable_u8.py`
- `run_signalforge_founder_usable_u9.py` -> `scripts/history/run_signalforge_founder_usable_u9.py`
- `run_signalforge_mature_research_adoption_a1.py` -> `scripts/history/run_signalforge_mature_research_adoption_a1.py`
- `run_signalforge_mature_research_adoption_a2.py` -> `scripts/history/run_signalforge_mature_research_adoption_a2.py`
- `run_signalforge_representation_audit_u24.py` -> `scripts/history/run_signalforge_representation_audit_u24.py`
- `run_signalforge_research_resilience_u16.py` -> `scripts/history/run_signalforge_research_resilience_u16.py`
- `run_signalforge_runtime_assimilation_u12.py` -> `scripts/history/run_signalforge_runtime_assimilation_u12.py`
- `run_signalforge_semantic_basis_u21.py` -> `scripts/history/run_signalforge_semantic_basis_u21.py`
- `run_signalforge_sentinel_review_u28.py` -> `scripts/history/run_signalforge_sentinel_review_u28.py`
- `run_signalforge_thesis_conditioned_evidence_u18.py` -> `scripts/history/run_signalforge_thesis_conditioned_evidence_u18.py`
- `run_signalforge_transition_discovery_v5_2.py` -> `scripts/history/run_signalforge_transition_discovery_v5_2.py`
- `run_signalforge_usability_cut_u1.py` -> `scripts/history/run_signalforge_usability_cut_u1.py`
- `run_signalforge_usability_cut_u2.py` -> `scripts/history/run_signalforge_usability_cut_u2.py`
- `run_signalforge_usability_cut_u3.py` -> `scripts/history/run_signalforge_usability_cut_u3.py`
- `run_signalforge_usability_cut_u4.py` -> `scripts/history/run_signalforge_usability_cut_u4.py`
- `show_signalforge_adaptive_evidence_u11_audit.py` -> `scripts/history/show_signalforge_adaptive_evidence_u11_audit.py`
- `show_signalforge_calibration.py` -> `scripts/history/show_signalforge_calibration.py`
- `show_signalforge_continuous_research_u10_audit.py` -> `scripts/history/show_signalforge_continuous_research_u10_audit.py`
- `show_signalforge_daily_radar.py` -> `scripts/history/show_signalforge_daily_radar.py`
- `show_signalforge_evidence_gap_voi_u13_audit.py` -> `scripts/history/show_signalforge_evidence_gap_voi_u13_audit.py`
- `show_signalforge_founder_usable_u5_audit.py` -> `scripts/history/show_signalforge_founder_usable_u5_audit.py`
- `show_signalforge_founder_usable_u6_audit.py` -> `scripts/history/show_signalforge_founder_usable_u6_audit.py`
- `show_signalforge_founder_usable_u7_audit.py` -> `scripts/history/show_signalforge_founder_usable_u7_audit.py`
- `show_signalforge_founder_usable_u8_audit.py` -> `scripts/history/show_signalforge_founder_usable_u8_audit.py`
- `show_signalforge_founder_usable_u9_audit.py` -> `scripts/history/show_signalforge_founder_usable_u9_audit.py`
- `show_signalforge_full_system_audit.py` -> `scripts/history/show_signalforge_full_system_audit.py`
- `show_signalforge_mature_research_adoption_a2_audit.py` -> `scripts/history/show_signalforge_mature_research_adoption_a2_audit.py`
- `show_signalforge_mature_research_adoption_audit.py` -> `scripts/history/show_signalforge_mature_research_adoption_audit.py`
- `show_signalforge_opportunity_identity_rebase_audit.py` -> `scripts/history/show_signalforge_opportunity_identity_rebase_audit.py`
- `show_signalforge_progression.py` -> `scripts/history/show_signalforge_progression.py`
- `show_signalforge_runtime_assimilation_u12_audit.py` -> `scripts/history/show_signalforge_runtime_assimilation_u12_audit.py`
- `show_signalforge_usability_cut_u1_audit.py` -> `scripts/history/show_signalforge_usability_cut_u1_audit.py`
- `show_signalforge_usability_cut_u2_audit.py` -> `scripts/history/show_signalforge_usability_cut_u2_audit.py`
- `show_signalforge_usability_cut_u3_audit.py` -> `scripts/history/show_signalforge_usability_cut_u3_audit.py`
- `show_signalforge_usability_cut_u4_audit.py` -> `scripts/history/show_signalforge_usability_cut_u4_audit.py`
- `show_signalforge_v10_source_portfolio_audit.py` -> `scripts/history/show_signalforge_v10_source_portfolio_audit.py`
- `show_signalforge_v11_observation_audit.py` -> `scripts/history/show_signalforge_v11_observation_audit.py`
- `show_signalforge_v12_scalable_observation_audit.py` -> `scripts/history/show_signalforge_v12_scalable_observation_audit.py`
- `show_signalforge_v13_balanced_opportunity_audit.py` -> `scripts/history/show_signalforge_v13_balanced_opportunity_audit.py`
- `show_signalforge_v14_full_system_audit.py` -> `scripts/history/show_signalforge_v14_full_system_audit.py`
- `show_signalforge_v15_full_system_audit.py` -> `scripts/history/show_signalforge_v15_full_system_audit.py`
- `show_signalforge_v16_full_system_audit.py` -> `scripts/history/show_signalforge_v16_full_system_audit.py`
- `show_signalforge_v17_full_system_audit.py` -> `scripts/history/show_signalforge_v17_full_system_audit.py`
- `show_signalforge_v18_full_system_audit.py` -> `scripts/history/show_signalforge_v18_full_system_audit.py`
- `show_signalforge_v19_full_system_audit.py` -> `scripts/history/show_signalforge_v19_full_system_audit.py`
- `show_signalforge_v20_full_system_audit.py` -> `scripts/history/show_signalforge_v20_full_system_audit.py`
- `show_signalforge_validation_queue.py` -> `scripts/history/show_signalforge_validation_queue.py`

All moved scripts retain their original Git blobs. No historical evidence was deleted.

Some archived scripts were written against their original root layout and may contain historical path assumptions. They are preserved as engineering evidence, not advertised as the current execution contract.

## Canonical public paths

- `api/`: API and runtime boundaries
- `processors/`: research, relevance, persistence and behavior logic
- `dashboard/`: current Research Workspace
- `scrapers/`: public-source collectors
- `config/`: source/configuration policy
- `docs/`: current architecture and review documentation
- `assets/`: portfolio architecture visuals
- `tests/history/`: historical verification evidence
- `scripts/history/`: historical experiment/audit lineage

## Public-repository safety boundary

Runtime research state is intentionally not part of the public repository. In particular, `.radar_runtime/`, credentials, caches, databases, logs, backups and generated installer archives remain excluded.

See [Limitations](LIMITATIONS.md) for research limitations and [Historical Source Export Manifest](../FULL_SOURCE_MANIFEST.md) for the original public-export provenance.
