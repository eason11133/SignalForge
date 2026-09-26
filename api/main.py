"""FastAPI application for the Community Mind Mirror Intelligence Dashboard."""

import asyncio
import os
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, func, text

from api.deps import get_db
from api.pipeline import run_pipeline, get_state as get_pipeline_state, is_running, set_broadcast
from processors.signalforge_runtime import launch_signalforge_cycle_nonblocking
from api.routes import dashboard, topics, personas, news, search, websocket, intelligence, signals, agents, source_data, job_intelligence, product_reviews, gig_board, research, opportunities, candidates, signalforge, signalforge_brain_v2
from database.connection import (
    async_session, engine, Base, User, Post, Persona, Topic, TopicMention,
    CommunityGraph, NewsEvent, ScraperRun,
    DiscoveredProduct, ProductMention, Migration, PainPoint,
    HypeIndex, LeaderShift, PlatformTone, FundingRound, AgentRun,
    ResearchPipeline, TractionScore, TechnologyLifecycle,
    MarketGap, CompetitiveThreat, PlatformDivergence,
    GithubRepo, HFModel, PackageDownload, YCCompany, SOQuestion, PHLaunch,
    ProductReview, GigPost, ResearchProject,
)

logger = structlog.get_logger()

from config.settings import SIGNALFORGE_LOCAL_MODE, SIGNALFORGE_STORAGE_MODE


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables and start 24-hour scraper scheduler."""
    app.state.database_ready = False
    app.state.database_error = None
    app.state.database_last_checked_at = None
    # ── Storage init ─────────────────────────────────────────────────────────
    # Current SignalForge Research Backlog / materials / history / behavior state are
    # file-backed under .radar_runtime.  Docker/PostgreSQL is now optional legacy
    # infrastructure instead of a startup requirement.
    app.state.storage_mode = SIGNALFORGE_STORAGE_MODE
    app.state.signalforge_core_ready = True
    if SIGNALFORGE_LOCAL_MODE:
        app.state.database_ready = False
        app.state.database_error = None
        app.state.database_last_checked_at = time.time()
        logger.info(
            "signalforge_local_storage_ready",
            storage_mode=SIGNALFORGE_STORAGE_MODE,
            database_required=False,
            research_store=".radar_runtime",
        )
    else:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                result = await conn.execute(text("SELECT COUNT(*) FROM platforms"))
                count = result.scalar()
                if count == 0:
                    await conn.execute(text("""
                        INSERT INTO platforms (name) VALUES
                        ('reddit'), ('hackernews'), ('github'), ('arxiv'),
                        ('producthunt'), ('stackoverflow'), ('youtube'),
                        ('news'), ('twitter'), ('linkedin')
                        ON CONFLICT (name) DO NOTHING
                    """))
            app.state.database_ready = True
            app.state.database_error = None
            app.state.database_last_checked_at = time.time()
            logger.info("database_initialized")
        except Exception as e:
            app.state.database_ready = False
            app.state.database_error = f"{type(e).__name__}: {e}"
            app.state.database_last_checked_at = time.time()
            logger.error("database_init_failed", error=str(e))

    # ── Wire broadcast so pipeline can push WebSocket events ─────────────────
    from api.routes.websocket import broadcast
    set_broadcast(broadcast)

    # ── Scheduler ────────────────────────────────────────────────────────────
    # The legacy DB-backed scraper/signalforge scheduler is disabled in local mode.
    # ResearchBacklog keeps its own file-backed supervisor and single-item runs, so
    # current SignalForge research remains usable without PostgreSQL/Redis.
    scheduler: AsyncIOScheduler | None = None
    if not SIGNALFORGE_LOCAL_MODE:
        interval_hours = int(os.getenv("PIPELINE_INTERVAL_HOURS", "24"))
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_pipeline,
            trigger=IntervalTrigger(hours=interval_hours),
            id="pipeline",
            name="Scraper pipeline",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        signalforge_interval = max(1, int(os.getenv("SIGNALFORGE_CHECK_INTERVAL_HOURS", "1") or 1))
        scheduler.add_job(
            launch_signalforge_cycle_nonblocking,
            trigger=IntervalTrigger(hours=signalforge_interval),
            kwargs={"force": False, "reason": "scheduler_or_wake"},
            id="signalforge",
            name="SignalForge stale-aware research",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=86400,
            max_instances=1,
        )
        scheduler.start()

        async def _delayed_signalforge_startup() -> None:
            delay_seconds = max(15, int(os.getenv("SIGNALFORGE_STARTUP_CATCHUP_DELAY_SECONDS", "60") or 60))
            await asyncio.sleep(delay_seconds)
            if not bool(getattr(app.state, "database_ready", False)):
                logger.warning("signalforge_startup_catchup_skipped", reason="DATABASE_NOT_READY")
                return
            launch_signalforge_cycle_nonblocking(force=False, reason="startup_catchup")

        asyncio.create_task(_delayed_signalforge_startup())
        logger.info(
            "scheduler_started",
            interval_hours=interval_hours,
            signalforge_check_hours=signalforge_interval,
        )
    else:
        logger.info(
            "legacy_scheduler_skipped",
            reason="SIGNALFORGE_LOCAL_MODE",
            research_backlog_supervisor="AVAILABLE_ON_DEMAND",
        )

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


app = FastAPI(
    title="Community Mind Mirror",
    lifespan=lifespan,
    description="Intelligence Dashboard API for AI/tech community analysis",
    version="1.0.0",
)


# SIGNALFORGE_FOUNDER_USABILITY_EVIDENCE_PRECISION_CLOSURE_V1
from api.signalforge_founder_precision_closure import install_signalforge_founder_precision
install_signalforge_founder_precision(app)
# END_SIGNALFORGE_FOUNDER_USABILITY_EVIDENCE_PRECISION_CLOSURE_V1


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# SignalForge DB-backed Founder routes fail visibly when Production DB is unavailable.
# Brain v2 read-only SQLite surfaces stay available because they are a separate derived plane.
@app.middleware("http")
async def signalforge_database_truth_guard(request: Request, call_next):
    path = request.url.path
    db_backed = (
        path.startswith("/api/signalforge/opportunity/")
        or path.startswith("/api/candidates")
        or path.startswith("/api/opportunities")
    )
    if db_backed and SIGNALFORGE_LOCAL_MODE:
        return JSONResponse(
            status_code=503,
            content={
                "status": "LEGACY_DATABASE_DISABLED_IN_LOCAL_MODE",
                "detail": "This legacy DB-backed surface is disabled. Current SignalForge Research Backlog remains available from .radar_runtime.",
                "storage_mode": SIGNALFORGE_STORAGE_MODE,
                "docker_required": False,
            },
        )
    if db_backed and not bool(getattr(request.app.state, "database_ready", False)):
        # Recovery probe: if the database came back after startup, restore service without
        # requiring a process restart. The query changes no state.
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            request.app.state.database_ready = True
            request.app.state.database_error = None
            request.app.state.database_last_checked_at = time.time()
        except Exception as exc:
            request.app.state.database_ready = False
            request.app.state.database_error = f"{type(exc).__name__}: {exc}"
            request.app.state.database_last_checked_at = time.time()
            return JSONResponse(
                status_code=503,
                content={
                    "status": "PRODUCTION_DATABASE_UNAVAILABLE",
                    "detail": "SignalForge DB-backed truth is unavailable; no fallback truth was fabricated.",
                    "error": request.app.state.database_error,
                    "brain_v2_read_only_may_remain_available": True,
                },
            )
    return await call_next(request)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    if not request.url.path.startswith("/api/ws"):
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed=f"{elapsed:.3f}s",
        )
    return response


# Include routers
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(personas.router, prefix="/api/personas", tags=["personas"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(intelligence.router, prefix="/api/intelligence", tags=["intelligence"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(source_data.router, prefix="/api/sources", tags=["source-data"])
app.include_router(websocket.router, prefix="/api/ws", tags=["websocket"])
app.include_router(job_intelligence.router, prefix="/api/job-intelligence", tags=["job-intelligence"])
app.include_router(product_reviews.router, prefix="/api/product-reviews", tags=["product-reviews"])
app.include_router(gig_board.router, prefix="/api/gig-board", tags=["gig-board"])
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(opportunities.router, prefix="/api/opportunities", tags=["opportunities"])
app.include_router(signalforge.router, prefix="/api/signalforge", tags=["signalforge"])
# SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_ROUTER_R1
app.include_router(signalforge_brain_v2.router, prefix="/api/signalforge/brain-v2", tags=["signalforge-brain-v2"])


@app.get("/healthz")
@app.get("/api/healthz")
@app.get("/api/health")
async def health_check(request: Request):
    db_ready = bool(getattr(request.app.state, "database_ready", False))
    local_mode = bool(SIGNALFORGE_LOCAL_MODE)
    return {
        "status": "ok" if (local_mode or db_ready) else "degraded",
        "service": "community-mind-mirror",
        "storage_mode": SIGNALFORGE_STORAGE_MODE,
        "signalforge_core_ready": True,
        "docker_required": not local_mode,
        "database": {
            "enabled": not local_mode,
            "ready": db_ready,
            "last_error": getattr(request.app.state, "database_error", None),
            "last_checked_at_epoch": getattr(request.app.state, "database_last_checked_at", None),
        },
        "research_backlog_store": ".radar_runtime/founder_opportunity_research_v1.json",
        "truth_boundary": "Local SignalForge research state is independent from the optional legacy database.",
    }


@app.get("/api/system/spending")
async def spending_status():
    """Project-local LLM spend recorded by spending_tracker.py."""
    from spending_tracker import get_spending_data
    return get_spending_data()


@app.post("/api/pipeline/trigger")
async def trigger_pipeline():
    """Manually trigger the legacy DB-backed scraper pipeline."""
    if SIGNALFORGE_LOCAL_MODE:
        return JSONResponse(
            status_code=409,
            content={
                "status": "LEGACY_PIPELINE_DISABLED_IN_LOCAL_MODE",
                "detail": "Current SignalForge Research Backlog can research directly without the legacy PostgreSQL/Redis pipeline.",
            },
        )
    if is_running():
        return {"status": "already_running", "message": "Pipeline is already in progress."}
    asyncio.create_task(run_pipeline())
    return {"status": "started", "message": "Pipeline triggered. Check logs for progress."}


class RunScrapersRequest(BaseModel):
    scrapers: list[str]


@app.post("/api/scrapers/run")
async def run_scrapers_endpoint(req: RunScrapersRequest, background_tasks: BackgroundTasks):
    """Run specific scrapers by name without triggering the full pipeline."""
    from run_scrapers_bg import run_scrapers, get_scraper, SCRAPER_ORDER
    unknown = [s for s in req.scrapers if s not in SCRAPER_ORDER]
    if unknown:
        return {"status": "error", "message": f"Unknown scrapers: {unknown}"}

    async def _run():
        import time
        results = {}
        for name in req.scrapers:
            t0 = time.time()
            try:
                scraper = get_scraper(name)
                await asyncio.wait_for(scraper.run(), timeout=600)
                results[name] = {
                    "status": "ok",
                    "fetched": scraper.records_fetched,
                    "new": scraper.records_new,
                    "duration_s": round(time.time() - t0, 1),
                }
            except asyncio.TimeoutError:
                results[name] = {"status": "timeout", "error": "Timed out after 600s"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
        return results

    background_tasks.add_task(_run)
    return {"status": "started", "scrapers": req.scrapers, "message": f"Running {len(req.scrapers)} scrapers in background."}


@app.get("/api/pipeline/status")
async def pipeline_status():
    """Return whether the pipeline is currently running."""
    return {"running": is_running()}


@app.get("/api/pipeline/state")
async def pipeline_state_endpoint():
    """Full pipeline state: step progress, log tail, phase."""
    return get_pipeline_state()


@app.get("/api/debug-db")
async def debug_db():
    """Debug endpoint to test DB connectivity."""
    import traceback
    from config.settings import DATABASE_URL
    import socket
    # Show masked URL and DNS resolution
    masked_url = DATABASE_URL.replace(DATABASE_URL.split("@")[0].split("://")[1], "****") if "@" in DATABASE_URL else DATABASE_URL
    host = DATABASE_URL.split("@")[-1].split("/")[0].split(":")[0] if "@" in DATABASE_URL else "unknown"
    try:
        ip = socket.gethostbyname(host)
        dns_ok = True
    except Exception as dns_err:
        ip = str(dns_err)
        dns_ok = False

    try:
        async with async_session() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM platforms"))
            count = result.scalar()
            result2 = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"))
            tables = [r[0] for r in result2.fetchall()]
        return {"status": "ok", "platforms": count, "tables": tables, "host": host, "dns": ip}
    except Exception as e:
        return {"status": "error", "error": str(e), "host": host, "dns_ok": dns_ok, "dns_ip": ip, "db_url_masked": masked_url}


@app.get("/api/stats")
async def stats():
    """Return record counts for all tables."""
    async with async_session() as session:
        users = (await session.execute(select(func.count(User.id)))).scalar()
        posts = (await session.execute(select(func.count(Post.id)))).scalar()
        personas = (await session.execute(select(func.count(Persona.id)))).scalar()
        topics_count = (await session.execute(select(func.count(Topic.id)))).scalar()
        mentions = (await session.execute(select(func.count(TopicMention.id)))).scalar()
        graph_edges = (await session.execute(select(func.count(CommunityGraph.id)))).scalar()
        news_events = (await session.execute(select(func.count(NewsEvent.id)))).scalar()
        scraper_runs = (await session.execute(select(func.count(ScraperRun.id)))).scalar()

    async with async_session() as session:
        products = (await session.execute(select(func.count(DiscoveredProduct.id)))).scalar()
        product_mentions = (await session.execute(select(func.count(ProductMention.id)))).scalar()
        migrations = (await session.execute(select(func.count(Migration.id)))).scalar()
        pain_points = (await session.execute(select(func.count(PainPoint.id)))).scalar()
        hype_index = (await session.execute(select(func.count(HypeIndex.id)))).scalar()
        leader_shifts = (await session.execute(select(func.count(LeaderShift.id)))).scalar()
        platform_tones = (await session.execute(select(func.count(PlatformTone.id)))).scalar()
        funding_rounds = (await session.execute(select(func.count(FundingRound.id)))).scalar()

    async with async_session() as session:
        agent_runs = (await session.execute(select(func.count(AgentRun.id)))).scalar()
        research_pipeline = (await session.execute(select(func.count(ResearchPipeline.id)))).scalar()
        traction_scores = (await session.execute(select(func.count(TractionScore.id)))).scalar()
        tech_lifecycle = (await session.execute(select(func.count(TechnologyLifecycle.id)))).scalar()
        market_gaps = (await session.execute(select(func.count(MarketGap.id)))).scalar()
        competitive_threats = (await session.execute(select(func.count(CompetitiveThreat.id)))).scalar()
        platform_divergence = (await session.execute(select(func.count(PlatformDivergence.id)))).scalar()

    async with async_session() as session:
        github_repos = (await session.execute(select(func.count(GithubRepo.id)))).scalar()
        hf_models = (await session.execute(select(func.count(HFModel.id)))).scalar()
        package_downloads = (await session.execute(select(func.count(PackageDownload.id)))).scalar()
        yc_companies = (await session.execute(select(func.count(YCCompany.id)))).scalar()
        so_questions = (await session.execute(select(func.count(SOQuestion.id)))).scalar()
        ph_launches = (await session.execute(select(func.count(PHLaunch.id)))).scalar()

    async with async_session() as session:
        product_reviews_count = (await session.execute(select(func.count(ProductReview.id)))).scalar()
        gig_posts_count = (await session.execute(select(func.count(GigPost.id)))).scalar()
        research_projects_count = (await session.execute(select(func.count(ResearchProject.id)))).scalar()

    return {
        "users": users,
        "posts": posts,
        "personas": personas,
        "topics": topics_count,
        "topic_mentions": mentions,
        "graph_edges": graph_edges,
        "news_events": news_events,
        "scraper_runs": scraper_runs,
        "discovered_products": products,
        "product_mentions": product_mentions,
        "migrations": migrations,
        "pain_points": pain_points,
        "hype_index": hype_index,
        "leader_shifts": leader_shifts,
        "platform_tones": platform_tones,
        "funding_rounds": funding_rounds,
        "agent_runs": agent_runs,
        "research_pipeline": research_pipeline,
        "traction_scores": traction_scores,
        "technology_lifecycle": tech_lifecycle,
        "market_gaps": market_gaps,
        "competitive_threats": competitive_threats,
        "platform_divergence": platform_divergence,
        "github_repos": github_repos,
        "hf_models": hf_models,
        "package_downloads": package_downloads,
        "yc_companies": yc_companies,
        "so_questions": so_questions,
        "ph_launches": ph_launches,
        "product_reviews": product_reviews_count,
        "gig_posts": gig_posts_count,
        "research_projects": research_projects_count,
    }


# Serve React frontend from /static if it exists
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_dir, "assets")), name="assets")

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(os.path.join(_static_dir, "favicon.svg"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — catch-all for frontend routes."""
        return FileResponse(os.path.join(_static_dir, "index.html"))


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)

# SIGNALFORGE_RESEARCH_PERSISTENCE_V2_5_3_BEGIN
# Durable research jobs: browser navigation owns no research lifecycle.
from api.signalforge_research_persistence_v253 import SignalForgeResearchPersistenceMiddleware
if not getattr(app.state, "_signalforge_research_persistence_v253", False):
    app.add_middleware(SignalForgeResearchPersistenceMiddleware)
    app.state._signalforge_research_persistence_v253 = True
# SIGNALFORGE_RESEARCH_PERSISTENCE_V2_5_3_END
