"""Audit Pain Point clustering without calling any LLM or modifying the database."""

import asyncio
from collections import defaultdict, Counter

from processors.pain_point_processor import PainPointProcessor
from database.connection import async_session, PainPoint
from sqlalchemy import select


KEYWORDS = [
    # Core AI frustrations
    "hallucin", "context window", "context length", "token limit",
    "rate limit", "rate_limit", "throttl",
    "pricing", "cost", "expensive", "billing",
    "latency", "slow", "timeout", "performance",
    "memory", "out of memory", "oom", "ram",

    # Quality & reliability
    "accuracy", "incorrect", "wrong answer", "unreliable",
    "inconsisten", "regression", "downgrad", "quality",

    # Development pain
    "documentation", "docs", "undocument",
    "api", "sdk", "breaking change", "deprecat",
    "deploy", "hosting", "scale", "scaling",
    "debug", "error", "crash", "bug",
    "auth", "login", "permission", "security",

    # AI/ML specific
    "fine-tun", "training", "finetuning",
    "prompt", "prompt engineer", "instruction",
    "embed", "vector", "retrieval", "rag",
    "agent", "workflow", "automat",
    "gpu", "inference", "cuda", "compute",
    "model", "weight", "checkpoint",

    # Tools & ecosystem
    "cursor", "copilot", "chatgpt", "claude",
    "langchain", "openai", "ollama",
    "integration", "plugin", "extension",
    "open source", "license", "censorship", "filter",

    # Career/industry
    "job", "hiring", "layoff", "interview", "salary",
]


def build_clusters(complaints):
    clusters = defaultdict(list)
    memberships = defaultdict(list)

    for complaint in complaints:
        text_lower = complaint["text"].lower()
        assigned = False

        for keyword in KEYWORDS:
            if keyword in text_lower:
                clusters[keyword].append(complaint)
                memberships[complaint["id"]].append(keyword)
                assigned = True

        if not assigned:
            clusters["other"].append(complaint)
            memberships[complaint["id"]].append("other")

    clusters = {k: v for k, v in clusters.items() if len(v) >= 2}
    return clusters, memberships


def short(text, n=180):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


async def main():
    p = PainPointProcessor()
    complaints = await p._find_complaints()

    clusters, memberships = build_clusters(complaints)

    print("=" * 88)
    print("PAIN POINT CLUSTER AUDIT — NO LLM / NO DB WRITES")
    print("=" * 88)
    print(f"Complaint candidates: {len(complaints)}")
    print(f"Valid clusters (>=2 posts): {len(clusters)}")

    membership_counts = Counter(len(memberships[c["id"]]) for c in complaints)
    multi = sum(1 for c in complaints if len(memberships[c["id"]]) > 1)
    max_memberships = max((len(memberships[c["id"]]) for c in complaints), default=0)

    print(f"Posts belonging to >1 keyword bucket: {multi}/{len(complaints)} "
          f"({(multi / len(complaints) * 100 if complaints else 0):.1f}%)")
    print(f"Maximum bucket memberships for one post: {max_memberships}")
    print("Membership-count distribution:",
          ", ".join(f"{k} bucket(s)={v}" for k, v in sorted(membership_counts.items())))

    print("\n" + "=" * 88)
    print("CLUSTERS, LARGEST FIRST")
    print("=" * 88)

    ordered = sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)

    for i, (keyword, posts) in enumerate(ordered, 1):
        ids = {x["id"] for x in posts}
        unique_only = sum(
            1 for post in posts
            if len([m for m in memberships[post["id"]] if m in clusters]) == 1
        )
        overlap_posts = len(posts) - unique_only
        print(
            f"{i:>2}. {keyword:<18} "
            f"size={len(posts):>3}  "
            f"exclusive={unique_only:>3}  "
            f"overlap={overlap_posts:>3} "
            f"({overlap_posts / len(posts) * 100:>5.1f}%)"
        )

    print("\n" + "=" * 88)
    print("TOP PAIRWISE CLUSTER OVERLAPS")
    print("=" * 88)

    pairs = []
    for i, (ka, pa) in enumerate(ordered):
        a = {x["id"] for x in pa}
        for kb, pb in ordered[i + 1:]:
            b = {x["id"] for x in pb}
            inter = len(a & b)
            if inter:
                union = len(a | b)
                pairs.append((inter, inter / union, ka, kb, len(a), len(b)))

    for inter, jaccard, ka, kb, sa, sb in sorted(pairs, reverse=True)[:20]:
        print(
            f"{ka:<18} ↔ {kb:<18} shared={inter:>3}  "
            f"Jaccard={jaccard:.2f}  sizes={sa}/{sb}"
        )

    print("\n" + "=" * 88)
    print("EVIDENCE SAMPLES FROM THE 5 LARGEST CLUSTERS")
    print("=" * 88)

    for keyword, posts in ordered[:5]:
        print(f"\n### CLUSTER: {keyword!r}  ({len(posts)} posts)")
        # Prefer highly-overlapping posts first because they reveal bucket contamination.
        ranked = sorted(
            posts,
            key=lambda x: (len(memberships[x["id"]]), -(x.get("sentiment") or 0)),
            reverse=True,
        )
        for post in ranked[:10]:
            member_list = [m for m in memberships[post["id"]] if m in clusters]
            print(
                f"- id={post['id']} sentiment={post.get('sentiment')} "
                f"buckets={member_list}\n"
                f"  {short(post['text'])}"
            )

    print("\n" + "=" * 88)
    print("CURRENT STORED PAIN POINTS")
    print("=" * 88)

    async with async_session() as session:
        result = await session.execute(
            select(
                PainPoint.title,
                PainPoint.intensity_score,
                PainPoint.post_count,
                PainPoint.has_solution,
            ).order_by(PainPoint.post_count.desc(), PainPoint.intensity_score.desc())
        )
        rows = result.all()

    for title, intensity, post_count, has_solution in rows:
        print(
            f"- posts={post_count:>3} intensity={intensity:>3} "
            f"solution={str(has_solution):<5} | {title}"
        )

    print("\nAUDIT COMPLETE.")
    print("No OpenAI calls were made and no database rows were changed.")


if __name__ == "__main__":
    asyncio.run(main())
