"""Founder-facing Opportunity API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_db
from database.connection import Opportunity, OpportunityEvidence

router = APIRouter()
VALID = {"new","watch","investigate","validate","build","reject"}

class StatusUpdate(BaseModel):
    status: str

def ser(o):
    return {k:getattr(o,k) for k in [
        "id","canonical_key","title","problem_statement","who_has_problem","why_now","status",
        "opportunity_score","confidence_score","pain_score","demand_score","growth_score",
        "buyer_score","supply_gap_score","cross_source_score","independent_users","evidence_count",
        "source_counts","score_breakdown","workarounds","existing_solutions","buyer_signals",
        "cluster_cohesion","first_seen_at","last_seen_at","calculated_at","updated_at"
    ]}

@router.get("/summary")
async def summary(db: AsyncSession=Depends(get_db)):
    total=(await db.execute(select(func.count(Opportunity.id)))).scalar() or 0
    hs=(await db.execute(select(func.count(Opportunity.id)).where(Opportunity.opportunity_score>=70))).scalar() or 0
    hc=(await db.execute(select(func.count(Opportunity.id)).where(Opportunity.confidence_score>=70))).scalar() or 0
    statuses={}
    for st in VALID:
        statuses[st]=(await db.execute(select(func.count(Opportunity.id)).where(Opportunity.status==st))).scalar() or 0
    return {"total":total,"high_score":hs,"high_confidence":hc,"statuses":statuses}

@router.get("")
async def list_opportunities(status:str|None=None,min_score:float|None=None,limit:int=Query(30,ge=1,le=100),db:AsyncSession=Depends(get_db)):
    stmt=select(Opportunity)
    if status: stmt=stmt.where(Opportunity.status==status)
    if min_score is not None: stmt=stmt.where(Opportunity.opportunity_score>=min_score)
    rows=(await db.execute(stmt.order_by(Opportunity.opportunity_score.desc(),Opportunity.confidence_score.desc()).limit(limit))).scalars().all()
    return [ser(o) for o in rows]

@router.get("/{opportunity_id}")
async def detail(opportunity_id:int,db:AsyncSession=Depends(get_db)):
    o=(await db.execute(select(Opportunity).where(Opportunity.id==opportunity_id))).scalar_one_or_none()
    if not o: raise HTTPException(404,"Opportunity not found")
    ev=(await db.execute(select(OpportunityEvidence).where(OpportunityEvidence.opportunity_id==opportunity_id)
        .order_by(OpportunityEvidence.strength.desc(),OpportunityEvidence.observed_at.desc().nullslast()))).scalars().all()
    data=ser(o)
    data["evidence"]=[{k:getattr(e,k) for k in ["id","post_id","source_type","platform","source_ref","evidence_type","title","excerpt","url","strength","observed_at"]} for e in ev]
    return data

@router.patch("/{opportunity_id}/status")
async def update_status(opportunity_id:int,payload:StatusUpdate,db:AsyncSession=Depends(get_db)):
    if payload.status not in VALID: raise HTTPException(400,f"Invalid status: {payload.status}")
    o=(await db.execute(select(Opportunity).where(Opportunity.id==opportunity_id))).scalar_one_or_none()
    if not o: raise HTTPException(404,"Opportunity not found")
    o.status=payload.status
    await db.commit(); await db.refresh(o)
    return ser(o)
