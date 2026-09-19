from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from config.settings import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ============================================
# TABLE: platforms
# ============================================
class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: users
# ============================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"))
    platform_user_id = Column(String(255), nullable=False)
    username = Column(String(255))
    bio = Column(Text)
    profile_url = Column(Text)
    karma_score = Column(Integer)
    account_created_at = Column(DateTime)
    last_scraped_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("platform_id", "platform_user_id"),
        Index("idx_users_platform", "platform_id"),
        Index("idx_users_username", "username"),
        Index("idx_users_last_scraped", "last_scraped_at"),
    )


# ============================================
# TABLE: posts
# ============================================
class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    platform_id = Column(Integer, ForeignKey("platforms.id"))
    post_type = Column(String(50), nullable=False)
    platform_post_id = Column(String(255))
    parent_post_id = Column(Integer, ForeignKey("posts.id"))
    title = Column(Text)
    body = Column(Text, nullable=False)
    url = Column(Text)
    subreddit = Column(String(255))
    score = Column(Integer, default=0)
    num_comments = Column(Integer, default=0)
    posted_at = Column(DateTime)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("platform_id", "platform_post_id"),
        Index("idx_posts_user", "user_id"),
        Index("idx_posts_platform", "platform_id"),
        Index("idx_posts_type", "post_type"),
        Index("idx_posts_subreddit", "subreddit"),
        Index("idx_posts_posted_at", "posted_at"),
        Index("idx_posts_score", "score"),
    )


# ============================================
# TABLE: personas
# ============================================
class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    core_beliefs = Column(JSONB)
    communication_style = Column(JSONB)
    emotional_triggers = Column(JSONB)
    expertise_domains = Column(JSONB)
    influence_type = Column(String(50))
    influence_score = Column(Float, default=0)
    inferred_location = Column(String(255))
    inferred_role = Column(String(255))
    personality_summary = Column(Text)
    active_topics = Column(JSONB)
    system_prompt = Column(Text)
    validation_score = Column(Float)
    model_used = Column(String(100))
    extracted_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_personas_influence", influence_score.desc()),
        Index("idx_personas_role", "inferred_role"),
        Index("idx_personas_location", "inferred_location"),
    )


# ============================================
# TABLE: cross_platform_identities
# ============================================
class CrossPlatformIdentity(Base):
    __tablename__ = "cross_platform_identities"

    id = Column(Integer, primary_key=True)
    canonical_user_id = Column(Integer, ForeignKey("users.id"))
    linked_user_id = Column(Integer, ForeignKey("users.id"))
    match_confidence = Column(Float)
    match_method = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("canonical_user_id", "linked_user_id"),
    )


# ============================================
# TABLE: community_graph
# ============================================
class CommunityGraph(Base):
    __tablename__ = "community_graph"

    id = Column(Integer, primary_key=True)
    source_user_id = Column(Integer, ForeignKey("users.id"))
    target_user_id = Column(Integer, ForeignKey("users.id"))
    interaction_type = Column(String(50))
    interaction_count = Column(Integer, default=1)
    avg_sentiment = Column(Float)
    first_interaction_at = Column(DateTime)
    last_interaction_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_user_id", "target_user_id", "interaction_type"),
        Index("idx_graph_source", "source_user_id"),
        Index("idx_graph_target", "target_user_id"),
    )


# ============================================
# TABLE: news_events
# ============================================
class NewsEvent(Base):
    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(50), nullable=False)
    source_name = Column(String(255))
    title = Column(Text, nullable=False)
    body = Column(Text)
    url = Column(Text)
    authors = Column(JSONB)
    published_at = Column(DateTime)
    categories = Column(JSONB)
    entities = Column(JSONB)
    sentiment = Column(Float)
    magnitude = Column(String(20))
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_news_source_type", "source_type"),
        Index("idx_news_published", "published_at"),
        Index("idx_news_categories", "categories", postgresql_using="gin"),
        Index("idx_news_entities", "entities", postgresql_using="gin"),
    )


# ============================================
# TABLE: topics
# ============================================
class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True)
    description = Column(Text)
    keywords = Column(JSONB)
    first_seen_at = Column(DateTime)
    last_seen_at = Column(DateTime)
    velocity = Column(Float, default=0)
    total_mentions = Column(Integer, default=0)
    sentiment_distribution = Column(JSONB)
    platforms_active = Column(JSONB)
    opinion_camps = Column(JSONB)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_topics_velocity", velocity.desc()),
        Index("idx_topics_status", "status"),
    )


# ============================================
# TABLE: topic_mentions
# ============================================
class TopicMention(Base):
    __tablename__ = "topic_mentions"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    news_event_id = Column(Integer, ForeignKey("news_events.id"), nullable=True)
    relevance_score = Column(Float)
    sentiment = Column(Float)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_mentions_topic", "topic_id"),
    )


# ============================================
# TABLE: discovered_products
# ============================================
class DiscoveredProduct(Base):
    __tablename__ = "discovered_products"

    id = Column(Integer, primary_key=True)
    canonical_name = Column(String(255), unique=True, nullable=False)
    category = Column(String(100))
    aliases = Column(JSONB, default=list)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime)
    total_mentions = Column(Integer, default=0)
    status = Column(String(20), default="active")
    discovered_by = Column(String(20), default="llm")
    confidence = Column(Float, default=1.0)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dp_name", "canonical_name"),
        Index("idx_dp_category", "category"),
        Index("idx_dp_status", "status"),
    )


# ============================================
# TABLE: product_mentions
# ============================================
class ProductMention(Base):
    __tablename__ = "product_mentions"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("discovered_products.id"))
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    news_event_id = Column(Integer, ForeignKey("news_events.id"), nullable=True)
    context_type = Column(String(50), default="mention")
    sentiment = Column(Float)
    detected_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_pm_product", "product_id"),
        Index("idx_pm_post", "post_id"),
        Index("idx_pm_context", "context_type"),
        Index("idx_pm_detected", "detected_at"),
    )


# ============================================
# TABLE: migrations (product switches)
# ============================================
class Migration(Base):
    __tablename__ = "migrations"

    id = Column(Integer, primary_key=True)
    from_product_id = Column(Integer, ForeignKey("discovered_products.id"))
    to_product_id = Column(Integer, ForeignKey("discovered_products.id"))
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text)
    confidence = Column(Float, default=0.9)
    confirmed_by = Column(String(20), default="regex")
    detected_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_mig_from", "from_product_id"),
        Index("idx_mig_to", "to_product_id"),
    )


# ============================================
# TABLE: pain_points
# ============================================
class PainPoint(Base):
    __tablename__ = "pain_points"

    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    intensity_score = Column(Integer, default=0)
    has_solution = Column(Boolean, default=False)
    mentioned_products = Column(JSONB, default=list)
    platforms = Column(JSONB, default=list)
    sample_quotes = Column(JSONB, default=list)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    post_count = Column(Integer, default=0)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_pp_intensity", intensity_score.desc()),
        Index("idx_pp_status", "status"),
    )


# ============================================
# TABLE: hype_index
# ============================================
class HypeIndex(Base):
    __tablename__ = "hype_index"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    sector_name = Column(String(255), nullable=False)
    builder_sentiment = Column(Float, default=0)
    vc_sentiment = Column(Float, default=0)
    gap = Column(Float, default=0)
    status = Column(String(20), default="aligned")
    builder_post_count = Column(Integer, default=0)
    vc_post_count = Column(Integer, default=0)
    calculated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_hype_sector", "sector_name"),
        Index("idx_hype_gap", gap.desc()),
    )


# ============================================
# TABLE: leader_shifts
# ============================================
class LeaderShift(Base):
    __tablename__ = "leader_shifts"

    id = Column(Integer, primary_key=True)
    persona_id = Column(Integer, ForeignKey("personas.id"))
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    topic_name = Column(String(255))
    old_stance = Column(Text)
    new_stance = Column(Text)
    shift_type = Column(String(20))
    trigger = Column(Text)
    summary = Column(Text)
    old_sentiment = Column(Float)
    new_sentiment = Column(Float)
    detected_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_ls_persona", "persona_id"),
        Index("idx_ls_detected", "detected_at"),
    )


# ============================================
# TABLE: platform_tones
# ============================================
class PlatformTone(Base):
    __tablename__ = "platform_tones"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    platform_name = Column(String(50), nullable=False)
    tone_description = Column(Text)
    post_count = Column(Integer, default=0)
    avg_sentiment = Column(Float)
    analyzed_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("topic_id", "platform_name"),
        Index("idx_pt_topic", "topic_id"),
    )


# ============================================
# TABLE: funding_rounds
# ============================================
class FundingRound(Base):
    __tablename__ = "funding_rounds"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(255), nullable=False)
    amount = Column(String(50))
    stage = Column(String(50))
    sector = Column(String(100))
    location = Column(String(255))
    news_event_id = Column(Integer, ForeignKey("news_events.id"), nullable=True)
    community_sentiment = Column(Float)
    community_post_count = Column(Integer, default=0)
    reaction_summary = Column(Text)
    announced_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_fr_company", "company_name"),
        Index("idx_fr_announced", "announced_at"),
        Index("idx_fr_sector", "sector"),
    )


# ============================================
# TABLE: simulations
# ============================================
class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    scenario = Column(Text, nullable=False)
    scenario_structured = Column(JSONB)
    agent_count = Column(Integer)
    agent_filter = Column(JSONB)
    platform_type = Column(String(50))
    time_steps = Column(Integer)
    model_config = Column(JSONB)
    status = Column(String(20), default="pending")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: simulation_results
# ============================================
class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id = Column(Integer, primary_key=True)
    simulation_id = Column(Integer, ForeignKey("simulations.id"))
    sentiment_trajectory = Column(JSONB)
    opinion_clusters = Column(JSONB)
    influencer_pivots = Column(JSONB)
    viral_content = Column(JSONB)
    risk_score = Column(Float)
    narrative_summary = Column(Text)
    raw_simulation_log = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: scraper_runs
# ============================================
class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id = Column(Integer, primary_key=True)
    scraper_name = Column(String(100), nullable=False)
    status = Column(String(20), default="running")
    records_fetched = Column(Integer, default=0)
    records_new = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    metadata_ = Column("metadata", JSONB)


# ============================================
# TABLE: github_repos
# ============================================
class GithubRepo(Base):
    __tablename__ = "github_repos"

    id = Column(Integer, primary_key=True)
    repo_full_name = Column(String(255), unique=True, nullable=False)
    name = Column(String(255))
    description = Column(Text)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    watchers = Column(Integer, default=0)
    language = Column(String(100))
    topics = Column(JSONB)
    owner_username = Column(String(255))
    open_issues = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    pushed_at = Column(DateTime)
    star_velocity = Column(Float)
    contributor_count = Column(Integer)
    non_founder_contributors = Column(Integer)
    homepage_url = Column(Text)
    license = Column(String(100))
    raw_metadata = Column(JSONB)
    first_scraped_at = Column(DateTime, server_default=func.now())
    last_scraped_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_gh_stars", stars.desc()),
        Index("idx_gh_velocity", "star_velocity"),
        Index("idx_gh_topics", "topics", postgresql_using="gin"),
    )


# ============================================
# TABLE: github_issues
# ============================================
class GithubIssue(Base):
    __tablename__ = "github_issues"

    id = Column(Integer, primary_key=True)
    github_issue_id = Column(BigInteger, unique=True, nullable=False)
    repo_full_name = Column(String(255), nullable=False)
    issue_number = Column(Integer, nullable=False)
    title = Column(Text)
    body = Column(Text)
    state = Column(String(30))
    labels = Column(JSONB)
    author_login = Column(String(255))
    comments_count = Column(Integer, default=0)
    html_url = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    closed_at = Column(DateTime)
    raw_metadata = Column(JSONB)
    first_scraped_at = Column(DateTime, server_default=func.now())
    last_scraped_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("repo_full_name", "issue_number"),
        Index("idx_ghi_repo", "repo_full_name"),
        Index("idx_ghi_updated", "updated_at"),
        Index("idx_ghi_labels", "labels", postgresql_using="gin"),
    )


# ============================================
# TABLE: source_registry
# ============================================
class SourceRegistry(Base):
    __tablename__ = "source_registry"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(60), nullable=False)
    source_key = Column(String(500), nullable=False)
    source_url = Column(Text)
    origin = Column(String(30), nullable=False, default="discovered")
    status = Column(String(30), nullable=False, default="WATCH")
    evidence_role = Column(String(60), nullable=False, default="DIRECT_PROBLEM")
    records_seen = Column(Integer, default=0)
    relevant_hits = Column(Integer, default=0)
    direct_problem_hits = Column(Integer, default=0)
    yield_score = Column(Float, default=0.0)
    last_seen_at = Column(DateTime)
    last_success_at = Column(DateTime)
    last_error = Column(Text)
    next_allowed_at = Column(DateTime)
    source_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("source_type", "source_key"),
        Index("idx_source_registry_status", "status"),
        Index("idx_source_registry_role", "evidence_role"),
        Index("idx_source_registry_yield", "yield_score"),
    )


# ============================================
# TABLE: source_checkpoints
# ============================================
class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"

    id = Column(Integer, primary_key=True)
    checkpoint_key = Column(String(255), unique=True, nullable=False)
    cursor = Column(Integer, default=0)
    last_value = Column(Text)
    checkpoint_metadata = Column("metadata", JSONB, default=dict)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================
# TABLE: external_problem_items
# Generic normalized records from source adapters.
# ============================================
class ExternalProblemItem(Base):
    __tablename__ = "external_problem_items"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(80), nullable=False)
    source_key = Column(String(500), nullable=False)
    external_id = Column(String(500), nullable=False)
    title = Column(Text)
    body = Column(Text)
    url = Column(Text)
    author = Column(String(255))
    published_at = Column(DateTime)
    updated_at = Column(DateTime)
    score = Column(Float)
    is_direct_problem = Column(Boolean, default=False, nullable=False)
    matched_candidate_id = Column(Integer)
    raw_metadata = Column(JSONB)
    first_scraped_at = Column(DateTime, server_default=func.now())
    last_scraped_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_key", "external_id",
            name="uq_external_problem_item",
        ),
        Index("idx_external_problem_source", "source_type", "source_key"),
        Index("idx_external_problem_direct", "is_direct_problem"),
        Index("idx_external_problem_candidate", "matched_candidate_id"),
        Index("idx_external_problem_published", "published_at"),
    )


# ============================================
# TABLE: radar_source_coverage
# Per-case source-search coverage/health.
# ============================================
class RadarSourceCoverage(Base):
    __tablename__ = "radar_source_coverage"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id"), nullable=False)
    source_type = Column(String(120), nullable=False)
    attempt_count = Column(Integer, default=0)
    successful_attempts = Column(Integer, default=0)
    zero_result_attempts = Column(Integer, default=0)
    hits_seen = Column(Integer, default=0)
    direct_problem_hits = Column(Integer, default=0)
    last_status = Column(String(40))
    last_query = Column(Text)
    last_attempt_at = Column(DateTime)
    last_error = Column(Text)
    coverage_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "case_id", "source_type",
            name="uq_radar_source_coverage",
        ),
        Index("idx_radar_source_coverage_case", "case_id"),
        Index("idx_radar_source_coverage_source", "source_type"),
        Index("idx_radar_source_coverage_status", "last_status"),
    )


# ============================================
# TABLE: package_downloads
# ============================================
class PackageDownload(Base):
    __tablename__ = "package_downloads"

    id = Column(Integer, primary_key=True)
    package_name = Column(String(255), nullable=False)
    registry = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    downloads = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("package_name", "registry", "date"),
        Index("idx_pkg_name", "package_name", "registry"),
        Index("idx_pkg_date", "date"),
    )


# ============================================
# TABLE: yc_companies
# ============================================
class YCCompany(Base):
    __tablename__ = "yc_companies"

    id = Column(Integer, primary_key=True)
    slug = Column(String(255), unique=True, nullable=False)
    name = Column(String(255))
    description = Column(Text)
    long_description = Column(Text)
    batch = Column(String(20))
    status = Column(String(50))
    industries = Column(JSONB)
    regions = Column(JSONB)
    team_size = Column(String(50))
    website = Column(Text)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_yc_batch", "batch"),
        Index("idx_yc_industries", "industries", postgresql_using="gin"),
    )


# ============================================
# TABLE: hf_models
# ============================================
class HFModel(Base):
    __tablename__ = "hf_models"

    id = Column(Integer, primary_key=True)
    model_id = Column(String(500), unique=True, nullable=False)
    pipeline_tag = Column(String(100))
    downloads = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    tags = Column(JSONB)
    library_name = Column(String(100))
    last_modified = Column(DateTime)
    downloads_last_week = Column(Integer)
    trending_score = Column(Float)
    raw_metadata = Column(JSONB)
    first_scraped_at = Column(DateTime, server_default=func.now())
    last_scraped_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_hf_downloads", downloads.desc()),
        Index("idx_hf_trending", "trending_score"),
        Index("idx_hf_pipeline", "pipeline_tag"),
    )


# ============================================
# TABLE: ph_launches
# ============================================
class PHLaunch(Base):
    __tablename__ = "ph_launches"

    id = Column(Integer, primary_key=True)
    ph_id = Column(String(100), unique=True)
    name = Column(String(255), nullable=False)
    tagline = Column(Text)
    description = Column(Text)
    votes_count = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    website = Column(Text)
    topics = Column(JSONB)
    makers = Column(JSONB)
    launched_at = Column(DateTime)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_ph_votes", votes_count.desc()),
        Index("idx_ph_launched", "launched_at"),
    )


# ============================================
# TABLE: so_questions
# ============================================
class SOQuestion(Base):
    __tablename__ = "so_questions"

    id = Column(Integer, primary_key=True)
    so_question_id = Column(Integer, unique=True, nullable=False)
    title = Column(Text)
    tags = Column(JSONB)
    view_count = Column(Integer, default=0)
    answer_count = Column(Integer, default=0)
    score = Column(Integer, default=0)
    is_answered = Column(Boolean, default=False)
    link = Column(Text)
    creation_date = Column(DateTime)
    last_activity_date = Column(DateTime)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_so_tags", "tags", postgresql_using="gin"),
        Index("idx_so_created", "creation_date"),
    )


# ============================================
# TABLE: agent_runs
# ============================================
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    agent_name = Column(String(100), nullable=False)
    status = Column(String(20), default="running")
    output = Column(Text)
    output_json = Column(JSONB)
    records_produced = Column(Integer, default=0)
    tokens_used = Column(Integer)
    cost_usd = Column(Float)
    error_message = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)

    __table_args__ = (
        Index("idx_ar_agent", "agent_name"),
        Index("idx_ar_started", started_at.desc()),
    )


# ============================================
# TABLE: research_pipeline
# ============================================
class ResearchPipeline(Base):
    __tablename__ = "research_pipeline"

    id = Column(Integer, primary_key=True)
    paper_title = Column(Text, nullable=False)
    arxiv_id = Column(String(50))
    published_at = Column(DateTime)
    github_repos = Column(JSONB)
    github_first_impl_at = Column(DateTime)
    hf_model_ids = Column(JSONB)
    hf_total_downloads = Column(Integer, default=0)
    hf_first_upload_at = Column(DateTime)
    community_mention_count = Column(Integer, default=0)
    community_first_mention_at = Column(DateTime)
    community_sentiment = Column(Float)
    ph_launches = Column(JSONB)
    ph_first_launch_at = Column(DateTime)
    so_question_count = Column(Integer, default=0)
    current_stage = Column(String(50))
    pipeline_velocity = Column(String(20))
    days_paper_to_code = Column(Integer)
    days_code_to_adoption = Column(Integer)
    days_total_pipeline = Column(Integer)
    updated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: traction_scores
# ============================================
class TractionScore(Base):
    __tablename__ = "traction_scores"

    id = Column(Integer, primary_key=True)
    entity_name = Column(String(255), nullable=False)
    entity_type = Column(String(50))
    ph_votes = Column(Integer, default=0)
    gh_stars = Column(Integer, default=0)
    gh_star_velocity = Column(Float, default=0)
    gh_non_founder_contributors = Column(Integer, default=0)
    pypi_monthly_downloads = Column(Integer, default=0)
    npm_monthly_downloads = Column(Integer, default=0)
    organic_mentions = Column(Integer, default=0)
    self_promo_mentions = Column(Integer, default=0)
    job_listings = Column(Integer, default=0)
    recommendation_rate = Column(Float)
    traction_score = Column(Float)
    traction_label = Column(String(50))
    score_breakdown = Column(JSONB)
    red_flags = Column(JSONB)
    reasoning = Column(Text)
    calculated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_ts_score", traction_score.desc()),
    )


# ============================================
# TABLE: technology_lifecycle
# ============================================
class TechnologyLifecycle(Base):
    __tablename__ = "technology_lifecycle"

    id = Column(Integer, primary_key=True)
    technology_name = Column(String(255), nullable=False)
    current_stage = Column(String(50))
    stage_evidence = Column(JSONB)
    arxiv_paper_count = Column(Integer, default=0)
    github_repo_count = Column(Integer, default=0)
    hf_model_count = Column(Integer, default=0)
    so_question_count = Column(Integer, default=0)
    so_question_type = Column(String(50))
    job_listing_count = Column(Integer, default=0)
    job_listing_type = Column(String(50))
    community_mention_count = Column(Integer, default=0)
    community_sentiment_trajectory = Column(JSONB)
    pypi_download_trend = Column(JSONB)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: market_gaps
# ============================================
class MarketGap(Base):
    __tablename__ = "market_gaps"

    id = Column(Integer, primary_key=True)
    problem_title = Column(Text, nullable=False)
    pain_score = Column(Float)
    complaint_count = Column(Integer, default=0)
    existing_products = Column(Integer, default=0)
    existing_product_names = Column(JSONB)
    total_funding_in_space = Column(Float, default=0)
    funded_startups = Column(JSONB)
    job_postings_related = Column(Integer, default=0)
    yc_batch_presence = Column(Float, default=0)
    gap_signal = Column(String(50))
    opportunity_score = Column(Float)
    reasoning = Column(Text)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: competitive_threats
# ============================================
class CompetitiveThreat(Base):
    __tablename__ = "competitive_threats"

    id = Column(Integer, primary_key=True)
    target_product = Column(String(255), nullable=False)
    competitor = Column(String(255), nullable=False)
    migrations_away = Column(Integer, default=0)
    competitor_gh_velocity = Column(Float, default=0)
    competitor_hiring = Column(Integer, default=0)
    competitor_sentiment = Column(Float, default=0)
    competitor_sentiment_trend = Column(Float)
    opinion_leaders_flipped = Column(Integer, default=0)
    threat_score = Column(Float)
    threat_summary = Column(Text)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: platform_divergence
# ============================================
class PlatformDivergence(Base):
    __tablename__ = "platform_divergence"

    id = Column(Integer, primary_key=True)
    topic_name = Column(String(255), nullable=False)
    reddit_sentiment = Column(Float)
    hn_sentiment = Column(Float)
    youtube_sentiment = Column(Float)
    ph_sentiment = Column(Float)
    max_divergence = Column(Float)
    divergence_direction = Column(String(255))
    prediction = Column(Text)
    status = Column(String(50))
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: narrative_shifts
# ============================================
class NarrativeShift(Base):
    __tablename__ = "narrative_shifts"

    id = Column(Integer, primary_key=True)
    topic_name = Column(String(255), nullable=False)
    topic_id = Column(Integer)
    shift_type = Column(String(100))
    shift_velocity = Column(String(50))
    older_frame = Column(Text)
    recent_frame = Column(Text)
    media_alignment = Column(Text)
    prediction = Column(Text)
    confidence = Column(String(50))
    narrative_timeline = Column(JSONB)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: smart_money
# ============================================
class SmartMoney(Base):
    __tablename__ = "smart_money"

    id = Column(Integer, primary_key=True)
    sector = Column(String(255), nullable=False)
    yc_companies_last_batch = Column(Integer, default=0)
    yc_trend = Column(String(50))
    yc_percentage_of_batch = Column(Float)
    vc_funding_articles = Column(Integer, default=0)
    vc_signal = Column(String(50))
    builder_repos = Column(Integer, default=0)
    builder_stars = Column(Integer, default=0)
    community_posts_30d = Column(Integer, default=0)
    classification = Column(String(50))
    reasoning = Column(Text)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: talent_flow
# ============================================
class TalentFlow(Base):
    __tablename__ = "talent_flow"

    id = Column(Integer, primary_key=True)
    skill = Column(String(255), nullable=False)
    category = Column(String(50))  # skill_gap, emerging, oversupply
    demand_score = Column(Integer, default=0)
    supply_score = Column(Integer, default=0)
    gap = Column(Integer, default=0)
    salary_pressure = Column(String(50))
    trend = Column(String(50))
    job_listings_30d = Column(Integer, default=0)
    so_questions_30d = Column(Integer, default=0)
    reasoning = Column(Text)
    prediction = Column(Text)
    calculated_at = Column(DateTime, server_default=func.now())


# ============================================
# TABLE: job_listings
# ============================================
class JobListing(Base):
    __tablename__ = "job_listings"

    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    company = Column(String(255))
    location = Column(String(255))
    job_type = Column(String(50))
    salary_min = Column(Float)
    salary_max = Column(Float)
    salary_currency = Column(String(10))
    remote = Column(Boolean, default=False)
    seniority = Column(String(50))
    department = Column(String(255))
    tags = Column(JSONB)
    description = Column(Text)
    url = Column(Text, unique=True)
    apply_url = Column(Text)
    published_at = Column(DateTime)
    raw_metadata = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_jl_source", "source"),
        Index("idx_jl_company", "company"),
        Index("idx_jl_remote", "remote"),
        Index("idx_jl_published", "published_at"),
        Index("idx_jl_tags", "tags", postgresql_using="gin"),
    )


# ============================================
# TABLE: job_intelligence
# ============================================
class JobIntelligence(Base):
    __tablename__ = "job_intelligence"

    id = Column(Integer, primary_key=True)
    job_listing_id = Column(Integer, ForeignKey("job_listings.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Role & Seniority
    role_category = Column(String(50))          # backend, frontend, fullstack, devops, data, ml_ai, mobile, security, qa, product, design, management
    seniority_normalized = Column(String(30))   # intern, junior, mid, senior, staff, principal, lead, manager, director, vp, c_level
    experience_years_min = Column(Integer)
    experience_years_max = Column(Integer)

    # Compensation (normalized to USD annual)
    salary_min_usd = Column(Integer)
    salary_max_usd = Column(Integer)

    # Location (normalized)
    remote_policy = Column(String(30))          # fully_remote, hybrid, onsite, remote_friendly
    location_city = Column(String(100))
    location_state = Column(String(100))
    location_country = Column(String(100))

    # Tech Stack
    tech_stack = Column(JSONB)                  # {"languages": [...], "frameworks": [...], "databases": [...], "cloud": [...], "ai_ml": [...], "tools": [...]}

    # Company Intelligence
    market_category = Column(String(50))        # fintech, healthtech, devtools, cybersecurity, edtech, etc.
    business_model = Column(String(30))         # b2b_saas, b2c, marketplace, enterprise, open_source, consulting
    company_stage = Column(String(30))          # seed, series_a, series_b, series_c_plus, growth, public, unknown
    ai_investment_level = Column(String(20))    # core_product, significant, internal_tooling, minimal, none
    funding_mentions = Column(Text)             # e.g. "$50M Series B led by Sequoia"
    domain_industry = Column(String(50))        # healthcare, finance, education, logistics, etc.

    # Hiring Signals
    hiring_urgency = Column(String(20))         # urgent, normal, passive
    team_structure_clues = Column(Text)         # "founding engineer", "report to CTO", "team of 8"

    # Skills & Responsibilities
    key_responsibilities = Column(JSONB)        # ["Design scalable APIs", "Lead ML pipeline", ...]
    must_have_skills = Column(JSONB)            # ["Python", "5+ years backend", ...]
    nice_to_have_skills = Column(JSONB)         # ["Rust", "distributed systems", ...]

    # Culture & Benefits
    benefits = Column(JSONB)                    # ["equity", "unlimited_pto", "visa_sponsorship", ...]
    culture_signals = Column(JSONB)             # ["startup_mentality", "flat_hierarchy", ...]
    work_methodology = Column(String(30))       # agile, scrum, kanban, waterfall, unknown
    compliance_requirements = Column(JSONB)     # ["soc2", "hipaa", "pci", "clearance", ...]

    # Metadata
    extracted_at = Column(DateTime, server_default=func.now())
    raw_llm_response = Column(JSONB)

    __table_args__ = (
        Index("idx_ji_role", "role_category"),
        Index("idx_ji_seniority", "seniority_normalized"),
        Index("idx_ji_market", "market_category"),
        Index("idx_ji_country", "location_country"),
        Index("idx_ji_ai_level", "ai_investment_level"),
        Index("idx_ji_stage", "company_stage"),
        Index("idx_ji_tech", "tech_stack", postgresql_using="gin"),
    )


# ============================================
# TABLE: product_reviews
# ============================================
class ProductReview(Base):
    __tablename__ = "product_reviews"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("discovered_products.id"), unique=True, nullable=False)
    product_name = Column(String(255), nullable=False)
    overall_sentiment = Column(String(20))  # positive/negative/mixed
    satisfaction_score = Column(Integer)  # 0-100
    pros = Column(JSONB, default=list)
    cons = Column(JSONB, default=list)
    common_use_cases = Column(JSONB, default=list)
    feature_requests = Column(JSONB, default=list)
    churn_reasons = Column(JSONB, default=list)
    competitor_comparisons = Column(JSONB, default=list)  # [{competitor, context}]
    post_count = Column(Integer, default=0)
    sample_post_ids = Column(JSONB, default=list)
    source_subreddits = Column(JSONB, default=list)
    calculated_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_pr_product", "product_id"),
        Index("idx_pr_sentiment", "overall_sentiment"),
        Index("idx_pr_score", satisfaction_score.desc()),
    )


# ============================================
# TABLE: gig_posts
# ============================================
class GigPost(Base):
    __tablename__ = "gig_posts"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    is_gig = Column(Boolean, default=True, server_default="true")
    gig_title = Column(String(500))
    project_type = Column(String(50))  # freelance/contract/full_time/co_founder/consulting
    need_description = Column(Text)
    need_category = Column(String(50))  # chatbot/rag/fine_tuning/agent/automation/data_pipeline/other
    skills_required = Column(JSONB, default=list)
    budget_text = Column(String(255))
    budget_min_usd = Column(Float)
    budget_max_usd = Column(Float)
    pay_type = Column(String(30))  # hourly/fixed/monthly/annual/equity
    tech_stack = Column(JSONB, default=list)
    experience_level = Column(String(30))  # junior/mid/senior/any
    remote_policy = Column(String(30))  # remote/onsite/hybrid
    location = Column(String(255))
    start_time = Column(String(100))
    project_duration = Column(String(100))
    industry = Column(String(100))
    company_name = Column(String(255))
    contact_method = Column(String(255))
    equity_offered = Column(Boolean)
    poster_username = Column(String(255))
    source_url = Column(Text)
    source_subreddit = Column(String(255))
    posted_at = Column(DateTime)
    extracted_at = Column(DateTime, server_default=func.now())
    raw_llm_response = Column(JSONB)

    __table_args__ = (
        Index("idx_gp_type", "project_type"),
        Index("idx_gp_category", "need_category"),
        Index("idx_gp_posted", posted_at.desc()),
        Index("idx_gp_tech", "tech_stack", postgresql_using="gin"),
        Index("idx_gp_post_id", "post_id", unique=True),
    )


# ── Custom Market Research ────────────────────────────────────


class ResearchProject(Base):
    __tablename__ = "research_projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    initial_terms = Column(JSONB, default=list)
    expanded_keywords = Column(JSONB, default=list)
    status = Column(String(20), default="draft")  # draft/expanding/scraping/processing/complete/failed
    post_count = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_rp_status", "status"),
        Index("idx_rp_created", created_at.desc()),
    )


class ResearchInsight(Base):
    __tablename__ = "research_insights"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("research_projects.id"), unique=True)
    discussion_summary = Column(Text)
    overall_sentiment = Column(String(20))  # positive/negative/mixed
    sentiment_breakdown = Column(JSONB)  # {positive: %, negative: %, neutral: %}
    products_mentioned = Column(JSONB, default=list)  # [{name, pros, cons, mention_count}]
    feature_requests = Column(JSONB, default=list)  # [{description, frequency, source_count}]
    unmet_needs = Column(JSONB, default=list)  # [{description, intensity, evidence}]
    key_themes = Column(JSONB, default=list)  # [{theme, post_count, sentiment}]
    raw_llm_response = Column(JSONB)
    calculated_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_ri_project", "project_id"),
    )


class ResearchContact(Base):
    __tablename__ = "research_contacts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("research_projects.id"))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(255), nullable=False)
    platform = Column(String(50), default="reddit")
    post_count = Column(Integer, default=0)
    avg_sentiment = Column(Float)
    sentiment_leaning = Column(String(20))  # positive/negative/mixed/neutral
    topics_discussed = Column(JSONB, default=list)
    sample_post_ids = Column(JSONB, default=list)
    profile_url = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "username", name="uq_rc_project_user"),
        Index("idx_rc_project", "project_id"),
        Index("idx_rc_post_count", post_count.desc()),
    )


# ============================================
# TABLE: opportunities
# ============================================
class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    canonical_key = Column(String(80), unique=True, nullable=False)
    title = Column(Text, nullable=False)
    problem_statement = Column(Text)
    who_has_problem = Column(Text)
    why_now = Column(Text)
    status = Column(String(20), default="new")
    opportunity_score = Column(Float, default=0)
    confidence_score = Column(Float, default=0)
    pain_score = Column(Float, default=0)
    demand_score = Column(Float, default=0)
    growth_score = Column(Float, default=0)
    buyer_score = Column(Float, default=0)
    supply_gap_score = Column(Float, default=0)
    cross_source_score = Column(Float, default=0)
    independent_users = Column(Integer, default=0)
    evidence_count = Column(Integer, default=0)
    source_counts = Column(JSONB, default=dict)
    score_breakdown = Column(JSONB, default=dict)
    workarounds = Column(JSONB, default=list)
    existing_solutions = Column(JSONB, default=list)
    buyer_signals = Column(JSONB, default=list)
    cluster_cohesion = Column(Float)
    first_seen_at = Column(DateTime)
    last_seen_at = Column(DateTime)
    calculated_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("idx_opp_score", opportunity_score.desc()),
        Index("idx_opp_confidence", confidence_score.desc()),
        Index("idx_opp_status", "status"),
    )

class OpportunityEvidence(Base):
    __tablename__ = "opportunity_evidence"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(50), nullable=False)
    platform = Column(String(50))
    source_ref = Column(String(255))
    evidence_type = Column(String(50), default="complaint")
    title = Column(Text)
    excerpt = Column(Text)
    url = Column(Text)
    strength = Column(Float, default=0)
    observed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("opportunity_id","source_type","source_ref",name="uq_opp_evidence_source"),
        Index("idx_opp_ev_opportunity","opportunity_id"),
    )

class ProblemCandidate(Base):
    __tablename__ = "problem_candidates"
    id=Column(Integer,primary_key=True)
    canonical_key=Column(String(80),unique=True,nullable=False)
    title=Column(Text,nullable=False)
    problem_statement=Column(Text)
    actor=Column(Text); actor_category=Column(String(50)); task=Column(Text); object=Column(Text)
    failure_mode=Column(Text); consequence=Column(Text); buyer_context=Column(Text); workaround=Column(Text)
    community_platform=Column(String(50)); discussion_key=Column(String(255))
    community_evidence_count=Column(Integer,default=0); community_user_count=Column(Integer,default=0)
    stage=Column(String(30),default="candidate"); founder_status=Column(String(30),default="new")
    market_score=Column(Float,default=0); confidence_score=Column(Float,default=0)
    community_problem_score=Column(Float,default=0); corroboration_score=Column(Float,default=0)
    buyer_demand_score=Column(Float,default=0); supply_gap_score=Column(Float,default=50)
    cross_source_score=Column(Float,default=0)
    source_support=Column(JSONB,default=dict); relation_support=Column(JSONB,default=dict); fingerprint=Column(JSONB,default=dict)
    first_seen_at=Column(DateTime); last_seen_at=Column(DateTime); calculated_at=Column(DateTime,server_default=func.now())
    created_at=Column(DateTime,server_default=func.now()); updated_at=Column(DateTime,server_default=func.now(),onupdate=func.now())
    __table_args__=(Index("idx_problem_candidate_stage","stage"),Index("idx_problem_candidate_score",market_score.desc()),Index("idx_problem_candidate_founder","founder_status"))

class CandidateEvidence(Base):
    __tablename__ = "candidate_evidence"
    id=Column(Integer,primary_key=True)
    candidate_id=Column(Integer,ForeignKey("problem_candidates.id",ondelete="CASCADE"),nullable=False)
    source_type=Column(String(50),nullable=False); source_table=Column(String(100)); source_ref=Column(String(255))
    relation=Column(String(50),nullable=False); title=Column(Text); excerpt=Column(Text); url=Column(Text)
    retrieval_score=Column(Float); verified=Column(Boolean,default=False); verification_confidence=Column(Float)
    evidence_metadata=Column("metadata",JSONB,default=dict); created_at=Column(DateTime,server_default=func.now())
    __table_args__=(Index("idx_candidate_evidence_candidate","candidate_id"),Index("idx_candidate_evidence_source","source_type"),Index("idx_candidate_evidence_relation","relation"))

# ============================================
# RADAR V4.0 — Evidence-Governed Foundation
# ============================================
class RadarCase(Base):
    __tablename__ = "radar_cases"
    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("problem_candidates.id", ondelete="CASCADE"), nullable=False, unique=True)
    case_key = Column(String(120), unique=True, nullable=False)
    legacy_stage = Column(String(30))
    system_verdict = Column(String(30), default="WATCH")
    research_state = Column(String(30), default="ACTIVE")
    current_gate = Column(String(50), default="PROBLEM_REALITY")
    verdict_reason_code = Column(String(100))
    reopened_count = Column(Integer, default=0)
    last_evaluated_at = Column(DateTime)
    next_review_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("idx_radar_case_verdict", "system_verdict"),
        Index("idx_radar_case_gate", "current_gate"),
    )

class RadarClaim(Base):
    __tablename__ = "radar_claims"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id", ondelete="CASCADE"), nullable=False)
    claim_code = Column(String(20), nullable=False)
    claim_type = Column(String(80), nullable=False)
    gate_group = Column(String(80), nullable=False)
    statement = Column(Text, nullable=False)
    state = Column(String(30), default="UNKNOWN")
    is_blocking = Column(Boolean, default=False)
    required_support_groups = Column(Integer, default=2)
    support_groups = Column(Integer, default=0)
    direct_support_groups = Column(Integer, default=0)
    refute_groups = Column(Integer, default=0)
    insufficient_count = Column(Integer, default=0)
    evidence_summary = Column(JSONB, default=dict)
    last_evaluated_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("uq_radar_claim_case_code", "case_id", "claim_code", unique=True),
        Index("idx_radar_claim_state", "state"),
        Index("idx_radar_claim_gate", "gate_group"),
    )

class RadarEvidence(Base):
    __tablename__ = "radar_evidence"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id", ondelete="CASCADE"), nullable=False)
    candidate_evidence_id = Column(Integer, ForeignKey("candidate_evidence.id", ondelete="SET NULL"))
    evidence_key = Column(String(180), unique=True, nullable=False)
    source_type = Column(String(60), nullable=False)
    source_table = Column(String(120))
    source_ref = Column(String(255))
    source_url = Column(Text)
    source_title = Column(Text)
    excerpt = Column(Text)
    source_family_key = Column(String(255), nullable=False)
    directness = Column(String(30), default="RELATED")
    authority_class = Column(String(60), default="UNKNOWN")
    published_at = Column(DateTime)
    observed_at = Column(DateTime, server_default=func.now())
    freshness_class = Column(String(50), default="UNASSESSED")
    freshness_score = Column(Float)
    content_hash = Column(String(80))
    raw_metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("idx_radar_evidence_case", "case_id"),
        Index("idx_radar_evidence_family", "source_family_key"),
        Index("idx_radar_evidence_source", "source_type"),
    )

class RadarClaimEvidence(Base):
    __tablename__ = "radar_claim_evidence"
    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("radar_claims.id", ondelete="CASCADE"), nullable=False)
    evidence_id = Column(Integer, ForeignKey("radar_evidence.id", ondelete="CASCADE"), nullable=False)
    stance = Column(String(30), nullable=False)
    interpretation_method = Column(String(60), nullable=False)
    method_version = Column(String(60))
    interpretation_confidence = Column(Float)
    rationale = Column(Text)
    validated = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("uq_radar_claim_evidence", "claim_id", "evidence_id", unique=True),
        Index("idx_radar_claim_evidence_stance", "stance"),
    )

class RadarAssumption(Base):
    __tablename__ = "radar_assumptions"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id", ondelete="CASCADE"), nullable=False)
    assumption_code = Column(String(40), nullable=False)
    statement = Column(Text, nullable=False)
    state = Column(String(30), default="UNKNOWN")
    impact = Column(String(30), default="MEDIUM")
    dependencies = Column(JSONB, default=list)
    watch_trigger = Column(JSONB, default=dict)
    last_checked_at = Column(DateTime)
    next_check_at = Column(DateTime)
    invalidated_by_evidence_id = Column(Integer, ForeignKey("radar_evidence.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("uq_radar_assumption_case_code", "case_id", "assumption_code", unique=True),
        Index("idx_radar_assumption_state", "state"),
    )

class RadarUnknown(Base):
    __tablename__ = "radar_unknowns"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id", ondelete="CASCADE"), nullable=False)
    claim_id = Column(Integer, ForeignKey("radar_claims.id", ondelete="SET NULL"))
    unknown_code = Column(String(40), nullable=False)
    question = Column(Text, nullable=False)
    uncertainty_type = Column(String(40), default="EPISTEMIC")
    state = Column(String(30), default="OPEN")
    decision_impact = Column(Float)
    reducibility = Column(Float)
    answerability = Column(Float)
    urgency = Column(Float)
    coverage_gap = Column(Float)
    estimated_cost_twd = Column(Float)
    priority_score = Column(Float)
    recommended_method = Column(String(80))
    resolved_by_evidence_id = Column(Integer, ForeignKey("radar_evidence.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index("uq_radar_unknown_case_code", "case_id", "unknown_code", unique=True),
        Index("idx_radar_unknown_state", "state"),
    )

class RadarDecisionEvent(Base):
    __tablename__ = "radar_decision_events"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("radar_cases.id", ondelete="CASCADE"), nullable=False)
    previous_verdict = Column(String(30))
    new_verdict = Column(String(30), nullable=False)
    reason_code = Column(String(100), nullable=False)
    reason_text = Column(Text)
    triggering_claim_code = Column(String(20))
    triggering_evidence_id = Column(Integer, ForeignKey("radar_evidence.id", ondelete="SET NULL"))
    engine_version = Column(String(60), nullable=False)
    decision_snapshot = Column(JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("idx_radar_decision_case", "case_id"),
        Index("idx_radar_decision_verdict", "new_verdict"),
    )

# ============================================
# RADAR V4.1 — Research Controller
# ============================================
class RadarResearchAction(Base):
    __tablename__ = "radar_research_actions"

    id = Column(Integer, primary_key=True)
    case_id = Column(
        Integer,
        ForeignKey("radar_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    unknown_id = Column(
        Integer,
        ForeignKey("radar_unknowns.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_key = Column(String(180), unique=True, nullable=False)
    claim_code = Column(String(20), nullable=False)

    action_type = Column(String(60), nullable=False)
    method = Column(String(100), nullable=False)
    status = Column(String(30), default="PLANNED")

    priority_score = Column(Float, nullable=False)
    decision_impact = Column(Float)
    reducibility = Column(Float)
    answerability = Column(Float)
    urgency = Column(Float)
    coverage_gap = Column(Float)

    estimated_cost_twd = Column(Float, default=0.0)
    estimated_llm_cost_twd = Column(Float, default=0.0)

    ai_allowed = Column(Boolean, default=False)
    ai_task_name = Column(String(100))
    ai_gate_reason = Column(Text)

    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_eligible_at = Column(DateTime)
    last_attempt_at = Column(DateTime)

    plan_metadata = Column(JSONB, default=dict)
    result_metadata = Column(JSONB, default=dict)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_radar_research_case", "case_id"),
        Index("idx_radar_research_status", "status"),
        Index("idx_radar_research_priority", "priority_score"),
    )


class RadarAIBudgetLedger(Base):
    __tablename__ = "radar_ai_budget_ledger"

    id = Column(Integer, primary_key=True)
    case_id = Column(
        Integer,
        ForeignKey("radar_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_key = Column(String(80), nullable=False)
    verdict_state = Column(String(30), nullable=False)

    budget_cap_twd = Column(Float, nullable=False)
    reserved_twd = Column(Float, default=0.0)
    spent_twd = Column(Float, default=0.0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_radar_ai_budget_case_cycle", "case_id", "cycle_key", unique=True),
    )

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
