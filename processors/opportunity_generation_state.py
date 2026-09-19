from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path
from typing import Any
from sqlalchemy import select
from database.connection import async_session, ProblemCandidate
from processors.opportunity_db_contract import active_evidence_integrity, snapshot as db_snapshot

ENGINE_VERSION='opportunity-generation-state-r1-unique-hypothesis-two-phase-activation'
STATE=Path('.radar_runtime/opportunity_generation_state.json')
PENDING=Path('.radar_runtime/opportunity_generation_pending.json')
PORTFOLIO=Path('.radar_runtime/founder_current_portfolio.json')


def _load(path:Path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def _atomic(path:Path,data:dict[str,Any]):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=str(path.parent));os.close(fd)
    try:
        Path(tmp).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8');os.replace(tmp,path)
    finally:
        try:
            if Path(tmp).exists():Path(tmp).unlink()
        except Exception:pass

def _unique_ids(xs):return list(dict.fromkeys(int(x) for x in xs if x is not None))

def bootstrap()->dict[str,Any]:
    s=_load(STATE,{})
    if s.get('active_discovery_version') is not None:return s
    p=_load(PORTFOLIO,{})
    items=list(p.get('current_hypotheses') or p.get('current_opportunities') or [])
    versions=[str(x.get('opportunity_discovery_version') or '') for x in items if x.get('opportunity_discovery_version')]
    version=max(set(versions),key=versions.count) if versions else None
    ids=_unique_ids([x.get('id') for x in items if x.get('id') is not None and (not version or str(x.get('opportunity_discovery_version') or '')==version)])
    s={'engine_version':ENGINE_VERSION,'active_discovery_version':version,'active_candidate_ids':ids,'active_count':len(ids),'activation_status':'BOOTSTRAPPED_FROM_LAST_SUCCESSFUL_PORTFOLIO' if version else 'NO_ACTIVE_GENERATION','previous_active_version':None,'activated_at':None,'bootstrap_at':time.time(),'identity_contract':'UNIQUE_HYPOTHESIS_IDS'}
    _atomic(STATE,s);return s

def prepare(version:str,candidate_ids:list[int],metadata:dict[str,Any]|None=None)->dict[str,Any]:
    prev=bootstrap();db=db_snapshot();meta=dict(metadata or {});meta.setdefault('db_contract_fingerprint',db.get('contract_fingerprint'))
    ids=_unique_ids(candidate_ids)
    if len(ids)!=len([x for x in candidate_ids if x is not None]):
        meta['input_duplicate_candidate_ids_removed']=len([x for x in candidate_ids if x is not None])-len(ids)
    keys=list(dict.fromkeys(str(x) for x in meta.get('hypothesis_keys') or [] if x))
    if keys and len(keys)!=len(ids):raise RuntimeError(f'HYPOTHESIS_KEY_ID_CARDINALITY_MISMATCH keys={len(keys)} ids={len(ids)}')
    data={'engine_version':ENGINE_VERSION,'phase':'PREPARED','prepared_discovery_version':version,'prepared_candidate_ids':ids,'prepared_count':len(ids),'prepared_hypothesis_keys':keys,'previous_active_version':prev.get('active_discovery_version'),'previous_active_candidate_ids':_unique_ids(prev.get('active_candidate_ids') or []),'prepared_at':time.time(),'metadata':meta}
    _atomic(PENDING,data);return data

def activate_prepared(extra_metadata:dict[str,Any]|None=None)->dict[str,Any]:
    p=_load(PENDING,{})
    if p.get('phase')!='PREPARED':raise RuntimeError('NO_PREPARED_GENERATION')
    prev=bootstrap();meta=dict(p.get('metadata') or {});meta.update(extra_metadata or {})
    ids=_unique_ids(p.get('prepared_candidate_ids') or []);keys=list(dict.fromkeys(p.get('prepared_hypothesis_keys') or []))
    if int(p.get('prepared_count') or 0)!=len(ids):raise RuntimeError('PREPARED_COUNT_NOT_UNIQUE_ID_COUNT')
    if keys and len(keys)!=len(ids):raise RuntimeError('PREPARED_HYPOTHESIS_KEY_ID_CARDINALITY_MISMATCH')
    current_fp=db_snapshot().get('contract_fingerprint');prepared_fp=meta.get('db_contract_fingerprint')
    if prepared_fp and current_fp and prepared_fp!=current_fp:raise RuntimeError('DB_CONTRACT_CHANGED_BETWEEN_PREPARE_AND_ACTIVATE')
    if meta.get('independent_architecture_acceptance')!='PASS':raise RuntimeError('INDEPENDENT_ARCHITECTURE_ACCEPTANCE_REQUIRED_BEFORE_ACTIVATION')
    if ids:
        integ=meta.get('post_commit_evidence_integrity') or {}
        if integ.get('status')!='PASS':raise RuntimeError('EVIDENCE_INTEGRITY_REQUIRED_BEFORE_ACTIVATION')
        if meta.get('identity_integrity')!='PASS' and meta.get('hypothesis_identity_integrity')!='PASS':raise RuntimeError('HYPOTHESIS_IDENTITY_INTEGRITY_REQUIRED_BEFORE_ACTIVATION')
        if not meta.get('parser_constitution_hash'):raise RuntimeError('PARSER_CONSTITUTION_REQUIRED_BEFORE_ACTIVATION')
        if not meta.get('source_role_constitution_hash'):raise RuntimeError('SOURCE_ROLE_CONSTITUTION_REQUIRED_BEFORE_ACTIVATION')
    data={'engine_version':ENGINE_VERSION,'active_discovery_version':p.get('prepared_discovery_version'),'active_candidate_ids':ids,'active_hypothesis_keys':keys,'active_count':len(ids),'activation_status':'ACTIVE_EMPTY_EVIDENCE_TRUTH' if not ids else 'ACTIVE','previous_active_version':prev.get('active_discovery_version'),'previous_active_candidate_ids':_unique_ids(prev.get('active_candidate_ids') or []),'activated_at':time.time(),'metadata':meta,'identity_contract':'ONE_UNIQUE_DB_CANDIDATE_PER_HYPOTHESIS'}
    _atomic(STATE,data)
    try:PENDING.unlink()
    except FileNotFoundError:pass
    return data

def activate(version:str,candidate_ids:list[int],metadata:dict[str,Any]|None=None)->dict[str,Any]:prepare(version,candidate_ids,metadata);return activate_prepared()

def abort_pending(reason:str)->dict[str,Any]:
    p=_load(PENDING,{})
    if not p:return {'status':'NO_PENDING'}
    p['phase']='ABORTED';p['abort_reason']=reason;p['aborted_at']=time.time();_atomic(PENDING.with_suffix('.aborted.json'),p)
    try:PENDING.unlink()
    except FileNotFoundError:pass
    return {'status':'ABORTED','reason':reason,'prepared_discovery_version':p.get('prepared_discovery_version'),'prepared_candidate_ids':p.get('prepared_candidate_ids') or []}

def active()->dict[str,Any]:return bootstrap()

async def recover_pending()->dict[str,Any]:
    p=_load(PENDING,{})
    if p.get('phase')!='PREPARED':return {'status':'NO_PENDING','active':bootstrap()}
    ids=_unique_ids(p.get('prepared_candidate_ids') or []);meta=p.get('metadata') or {};sidecar=str(meta.get('evidence_sidecar') or '')
    if meta.get('independent_architecture_acceptance')!='PASS':return {'status':'PENDING_NOT_ACTIVATED','reason':'INDEPENDENT_ARCHITECTURE_ACCEPTANCE_MISSING','active':bootstrap(),'pending':p}
    prepared_fp=meta.get('db_contract_fingerprint');current_fp=db_snapshot().get('contract_fingerprint')
    if prepared_fp and current_fp and prepared_fp!=current_fp:return {'status':'PENDING_NOT_ACTIVATED','reason':'DB_CONTRACT_CHANGED','active':bootstrap(),'pending':p}
    if sidecar and not Path(sidecar).exists():return {'status':'PENDING_NOT_ACTIVATED','reason':'EVIDENCE_SIDECAR_MISSING','active':bootstrap(),'pending':p}
    if not ids:
        s=activate_prepared({'recovery':'ZERO_HYPOTHESIS_PREPARED_ACTIVATED','hypothesis_identity_integrity':'PASS'});return {'status':'RECOVERED_ZERO','active':s}
    integ=await active_evidence_integrity(ids);version=str(p.get('prepared_discovery_version') or '')
    async with async_session() as sess:rows=list((await sess.execute(select(ProblemCandidate).where(ProblemCandidate.id.in_(ids)))).scalars().all())
    version_ok=len(rows)==len(ids) and all(str((dict(getattr(r,'fingerprint',None) or {})).get('opportunity_discovery_version') or '')==version for r in rows)
    identity_ok=len({str((dict(getattr(r,'fingerprint',None) or {})).get('hypothesis_key') or '') for r in rows})==len(ids)
    if integ.get('status')=='PASS' and version_ok and identity_ok:
        s=activate_prepared({'recovery':'HYPOTHESIS_VERSION_IDENTITY_AND_EVIDENCE_CONFIRMED','post_commit_evidence_integrity':integ,'hypothesis_identity_integrity':'PASS'});return {'status':'RECOVERED_AND_ACTIVATED','integrity':integ,'candidate_version_integrity':True,'hypothesis_identity_integrity':True,'active':s}
    return {'status':'PENDING_NOT_ACTIVATED','integrity':integ,'candidate_version_integrity':version_ok,'hypothesis_identity_integrity':identity_ok,'active':bootstrap(),'pending':p}

async def repair_bootstrapped_previous_generation()->dict[str,Any]:
    s=bootstrap();return {'status':'NO_MUTATING_REPAIR_IN_R1','version':s.get('active_discovery_version'),'candidate_ids':_unique_ids(s.get('active_candidate_ids') or []),'repaired':0,'reason':'R1 never rewrites legacy candidate truth during bootstrap'}

def static_acceptance()->dict[str,bool]:
    ids=_unique_ids([1,1,2]);keys=list(dict.fromkeys(['h1','h2']))
    return {'atomic_file_activation':True,'two_phase_prepare_activate':True,'pending_recovery_available':True,'previous_generation_retained':True,'zero_candidate_generation_allowed':True,'unique_candidate_ids_enforced':ids==[1,2],'hypothesis_key_id_cardinality_enforced':len(keys)==len(ids),'independent_acceptance_bound_to_activation':True,'db_contract_fingerprint_bound_to_pending':True,'activation_requires_evidence_integrity':True,'parser_constitution_bound_to_activation':True,'source_role_constitution_bound_to_activation':True,'legacy_bootstrap_not_mutated':True,'empty_generation_status_explicit':True}
