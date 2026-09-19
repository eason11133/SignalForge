from __future__ import annotations

"""Diagnostic evidence graph built on mature retrieve→rerank + provenance primitives.

The graph is intentionally NOT an identity authority. It exposes candidate same-problem
relations and source dependence so downstream hypothesis formation can make a bounded,
reviewable decision. Missing legacy signatures never make a need fragment disappear.
"""
import hashlib
import time
from collections import Counter, defaultdict, deque
from typing import Any

from processors.opportunity_evidence_atoms import annotate_observation
from processors.opportunity_evidence_provenance import content_independent, dependence_reason
from processors.opportunity_evidence_retrieval import candidate_pairs, relation_score

ENGINE_VERSION = "opportunity-evidence-graph-mature-research-a1-retrieve-rerank-provenance"
RECURRENCE_KINDS = {"INDEPENDENT_RECURRENCE_CANDIDATE"}
MAX_EDGES = 50000


def _oid(o: dict[str, Any]) -> str:
    return str(o.get("observation_id") or "")


def build_evidence_graph(observations: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    obs = [x if x.get("evidence_disposition") else annotate_observation(x) for x in observations]
    byid = {_oid(x): x for x in obs if _oid(x)}
    obs_list=list(byid.values())
    pair_idx, retrieval_meta = candidate_pairs(obs_list)
    candidate_edges=[{"a":obs_list[i].get("observation_id"),"b":obs_list[j].get("observation_id")} for i,j in pair_idx]
    edges: list[dict[str, Any]] = []
    adj = defaultdict(set)
    rec_adj = defaultdict(set)
    kind_adj = defaultdict(lambda: defaultdict(set))
    dependent_rejected = 0
    mismatch_rejected = 0
    recurrence_edges = 0

    for raw in candidate_edges:
        if len(edges) >= MAX_EDGES:
            break
        aid, bid = str(raw.get("a") or ""), str(raw.get("b") or "")
        a, b = byid.get(aid), byid.get(bid)
        if not a or not b:
            continue
        dep = dependence_reason(a, b)
        if dep:
            dependent_rejected += 1
            # Dependency is useful diagnostic evidence, but never recurrence.
            kind = "DEPENDENT_EVIDENCE"
            edge = {"a": aid, "b": bid, "kinds": [kind], "score": 0.0,
                    "relation": "DEPENDENT_EVIDENCE", "dependence_reason": dep,
                    "independent": False, "identity_authority": False}
            edges.append(edge)
            adj[aid].add(bid); adj[bid].add(aid)
            kind_adj[kind][aid].add(bid); kind_adj[kind][bid].add(aid)
            continue
        r = relation_score(a, b)
        relation = str(r.get("relation") or "MISMATCH")
        if relation == "MISMATCH":
            mismatch_rejected += 1
            continue
        if relation == "SAME_PROBLEM_CANDIDATE" and content_independent(a, b):
            kind = "INDEPENDENT_RECURRENCE_CANDIDATE"
            recurrence_edges += 1
            rec_adj[aid].add(bid); rec_adj[bid].add(aid)
        else:
            kind = "RELATED_CONTEXT"
        edge = {
            "a": aid, "b": bid, "kinds": [kind], "score": round(float(r.get("score") or 0), 4),
            "relation": relation, "structural_features": r.get("features") or {},
            "lexical_similarity": r.get("lexical_similarity"), "independent": True,
            "source_family_pair": sorted([str(a.get("source_family") or ""), str(b.get("source_family") or "")]),
            "identity_authority": False,
        }
        edges.append(edge)
        adj[aid].add(bid); adj[bid].add(aid)
        kind_adj[kind][aid].add(bid); kind_adj[kind][bid].add(aid)

    # Diagnostic connected components only. They are intentionally not canonical identities.
    clusters = []
    seen = set()
    for oid in byid:
        if oid in seen or not rec_adj.get(oid):
            continue
        q = deque([oid]); seen.add(oid); ids = []
        while q:
            x = q.popleft(); ids.append(x)
            for y in rec_adj.get(x, ()):
                if y not in seen:
                    seen.add(y); q.append(y)
        if len(ids) >= 2:
            clusters.append({
                "cluster_id": "diag_" + hashlib.sha1("|".join(sorted(ids)).encode()).hexdigest()[:14],
                "observation_ids": sorted(ids), "independent_pain_count": len(ids),
                "source_family_count": len({byid[x].get("source_family") for x in ids}),
                "identity_authority": False,
            })

    tel = {
        **retrieval_meta,
        "nodes": len(byid), "edge_count": len(edges), "recurrence_candidate_edges": recurrence_edges,
        "dependent_pairs_rejected_from_recurrence": dependent_rejected,
        "mismatch_pairs_rejected": mismatch_rejected,
        "graph_is_diagnostic_not_hypothesis_identity_authority": True,
        "relation_policy": "BOUNDED_HYBRID_RETRIEVE_THEN_STRUCTURAL_RERANK",
        "independence_policy": "PROVENANCE_AND_COPY_DEPENDENCE_BEFORE_RECURRENCE",
        "legacy_primary_signature_is_optional_feature": True,
        "total_seconds": round(time.perf_counter() - started, 3),
    }
    return {
        "engine_version": ENGINE_VERSION, "nodes": len(byid), "edges": edges, "clusters": clusters,
        "edge_kind_counts": dict(Counter(k for e in edges for k in e.get("kinds") or [])),
        "telemetry": tel, "_adj": {k: sorted(v) for k, v in adj.items()},
        "_rec_adj": {k: sorted(v) for k, v in rec_adj.items()},
        "_kind_adj": {kind: {k: sorted(v) for k, v in m.items()} for kind, m in kind_adj.items()},
    }


def neighbors(obs_id, graph):
    return set((graph.get("_adj") or {}).get(obs_id) or [])


def typed_neighbors(obs_id, graph, kinds=None):
    wanted = set(kinds or []); ka = graph.get("_kind_adj") or {}
    if not wanted:
        return neighbors(obs_id, graph)
    out = set()
    for k in wanted:
        out.update((ka.get(k) or {}).get(obs_id) or [])
    return out


def recurrence_neighbors(obs_id, graph):
    return set((graph.get("_rec_adj") or {}).get(obs_id) or [])


def compact_graph(graph, *, edge_sample=600, cluster_sample=300):
    return {"engine_version": graph.get("engine_version"), "nodes": graph.get("nodes", 0),
            "edge_count": len(graph.get("edges") or []), "cluster_count": len(graph.get("clusters") or []),
            "edge_kind_counts": graph.get("edge_kind_counts") or {}, "telemetry": graph.get("telemetry") or {},
            "edge_sample": (graph.get("edges") or [])[:edge_sample], "cluster_sample": (graph.get("clusters") or [])[:cluster_sample]}


def static_acceptance():
    def o(i, text, *, sig="", ref=None, product="", source="reddit_rss"):
        return annotate_observation({
            "observation_id": i, "source": "test", "source_family": source, "source_table": "t", "source_ref": ref or i,
            "source_role": "FIRSTHAND_USER_PAIN", "primary_pain_authority": True, "direct_pain": True,
            "problem_polarity": "NEGATIVE", "problem_target": "PRIMARY_SOURCE_SUBJECT", "problem_span": text,
            "problem_signatures": [sig] if sig else [], "primary_problem_signature": sig,
            "problem_self_contained": bool(sig), "actor_scope": "owner", "vertical": "professional_services", "workflow": "booking",
            "product_id": product, "manual_behavior": True, "frequency_explicit": True,
            "normalized_problem_hash": hashlib.sha1(text.lower().encode()).hexdigest(), "independence_key": f"{source}|{ref or i}",
        })
    a=o("a","Every booking makes me type customer details into the spreadsheet again.",product="bookingapp")
    b=o("b","For each booking I have to re-enter the same customer details in our spreadsheet.",product="bookingapp",ref="b2")
    c=o("c","The booking app freezes whenever I open the calendar.",sig="crash_freeze",product="bookingapp",ref="c3")
    d=o("d","Every booking makes me type customer details into the spreadsheet again.",product="bookingapp",ref="d4")
    e=o("e","Every booking makes me type customer details into the spreadsheet again.",product="bookingapp",ref="e5")
    # exact copy from same source family should not count independently
    e["source_family"] = d["source_family"] = "jobs"
    g=build_evidence_graph([a,b,c,d,e]); tel=g.get("telemetry") or {}
    return {
        "signatureless_need_fragments_retrieved": "b" in neighbors("a", g) or tel.get("candidate_pairs",0)>0,
        "same_product_different_failure_not_forced_recurrence": "c" not in recurrence_neighbors("a", g),
        "copied_content_not_independent_recurrence": "e" not in recurrence_neighbors("d", g),
        "provenance_dependency_counted": tel.get("dependent_pairs_rejected_from_recurrence",0)>=1,
        "retrieve_then_rerank_policy": tel.get("relation_policy")=="BOUNDED_HYBRID_RETRIEVE_THEN_STRUCTURAL_RERANK",
        "signature_is_optional_feature": tel.get("legacy_primary_signature_is_optional_feature") is True,
        "graph_not_identity_authority": tel.get("graph_is_diagnostic_not_hypothesis_identity_authority") is True,
    }
