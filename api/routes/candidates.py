from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_db
from database.connection import ProblemCandidate, CandidateEvidence

router=APIRouter()
VALID={"new","watch","investigate","validate","build","dismissed"}
class FounderStatusUpdate(BaseModel): status:str

def ser(c):
    return {k:getattr(c,k) for k in (
        "id","canonical_key","title","problem_statement","actor","actor_category","task","object",
        "failure_mode","consequence","buyer_context","workaround","community_platform","discussion_key",
        "community_evidence_count","community_user_count","stage","founder_status","market_score",
        "confidence_score","community_problem_score","corroboration_score","buyer_demand_score",
        "supply_gap_score","cross_source_score","source_support","relation_support","fingerprint",
        "first_seen_at","last_seen_at","calculated_at","updated_at"
    )}

@router.get("/summary")
async def summary(db:AsyncSession=Depends(get_db)):
    total=(await db.execute(select(func.count(ProblemCandidate.id)))).scalar() or 0
    stages={}
    for st in ("candidate","market_supported","corroborated","opportunity"):
        stages[st]=(await db.execute(select(func.count(ProblemCandidate.id)).where(ProblemCandidate.stage==st))).scalar() or 0
    active=(await db.execute(select(func.count(ProblemCandidate.id)).where(
        ProblemCandidate.founder_status.in_(["watch","investigate","validate"])
    ))).scalar() or 0
    return {"total":total,"stages":stages,"active_founder_work":active}

@router.get("")
async def list_candidates(stage:str|None=None,founder_status:str|None=None,limit:int=Query(60,ge=1,le=200),db:AsyncSession=Depends(get_db)):
    stmt=select(ProblemCandidate)
    if stage: stmt=stmt.where(ProblemCandidate.stage==stage)
    if founder_status: stmt=stmt.where(ProblemCandidate.founder_status==founder_status)
    rows=(await db.execute(stmt.order_by(
        ProblemCandidate.market_score.desc(),ProblemCandidate.confidence_score.desc()
    ).limit(limit))).scalars().all()
    return [ser(x) for x in rows]

@router.get("/{candidate_id}")
async def detail(candidate_id:int,db:AsyncSession=Depends(get_db)):
    c=(await db.execute(select(ProblemCandidate).where(ProblemCandidate.id==candidate_id))).scalar_one_or_none()
    if not c: raise HTTPException(404,"Problem candidate not found")
    ev=(await db.execute(select(CandidateEvidence).where(
        CandidateEvidence.candidate_id==candidate_id
    ).order_by(CandidateEvidence.verified.desc(),CandidateEvidence.verification_confidence.desc()))).scalars().all()
    r=ser(c)
    r["evidence"]=[{
        "id":e.id,
        "source_type":e.source_type,
        "source_table":e.source_table,
        "source_ref":e.source_ref,
        "relation":e.relation,
        "title":e.title,
        "excerpt":e.excerpt,
        "url":e.url,
        "retrieval_score":e.retrieval_score,
        "verified":e.verified,
        "verification_confidence":e.verification_confidence,
        "metadata":e.evidence_metadata or {},
    } for e in ev]
    return r

@router.patch("/{candidate_id}/founder-status")
async def update(candidate_id:int,payload:FounderStatusUpdate,db:AsyncSession=Depends(get_db)):
    if payload.status not in VALID: raise HTTPException(400,"Invalid founder status")
    c=(await db.execute(select(ProblemCandidate).where(ProblemCandidate.id==candidate_id))).scalar_one_or_none()
    if not c: raise HTTPException(404,"Problem candidate not found")
    c.founder_status=payload.status
    await db.commit(); await db.refresh(c)
    return ser(c)
