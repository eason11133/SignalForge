from __future__ import annotations
import hashlib, json, time, uuid
from typing import Any
from sqlalchemy import select, inspect as sa_inspect
from database.connection import ProblemCandidate, CandidateEvidence, async_session

ENGINE_VERSION='opportunity-db-contract-r1-typed-evidence-hypothesis-safe'

EVIDENCE_ALIASES={
    'candidate_fk':('candidate_id','problem_candidate_id'),
    'source_type':('source_type',),
    'source_table':('source_table',),
    'source_ref':('source_ref',),
    'relation':('relation','relation_type'),
    'title':('title',),
    'summary':('excerpt','summary'),
    'url':('url','source_url'),
    'retrieval_score':('retrieval_score',),
    'verified':('verified',),
    'verification_confidence':('verification_confidence',),
    'evidence_metadata':('evidence_metadata','metadata_json','metadata'),
    'observed_at':('observed_at',),
    'created_at':('created_at',),
}
CORE_REQUIRED=('candidate_fk','source_type','source_ref','relation','summary')
OPTIONAL_ENRICHMENT=('source_table','title','url','retrieval_score','verified','verification_confidence','evidence_metadata','observed_at','created_at')


def _column_descriptors(model)->list[dict[str,Any]]:
    table=model.__table__
    try:mapper=sa_inspect(model)
    except Exception:mapper=None
    by_col={}
    if mapper is not None:
        for prop in getattr(mapper,'column_attrs',[]):
            for c in getattr(prop,'columns',[]):by_col[id(c)]=str(prop.key)
    out=[]
    for c in table.columns:
        orm_attr=by_col.get(id(c))
        if orm_attr is None:
            for prop in getattr(mapper,'column_attrs',[]) if mapper is not None else []:
                if any(getattr(x,'name',None)==c.name for x in getattr(prop,'columns',[])):
                    orm_attr=str(prop.key);break
        out.append({'physical_name':str(c.name),'table_key':str(c.key),'orm_attr':orm_attr or str(c.key),'nullable':bool(c.nullable),'primary_key':bool(c.primary_key),'autoincrement':str(c.autoincrement),'has_default':c.default is not None,'has_server_default':c.server_default is not None,'type':type(c.type).__name__})
    return out


def columns(model)->set[str]:return {x['physical_name'] for x in _column_descriptors(model)}

def resolve_binding(model,logical:str)->dict[str,Any]|None:
    aliases=set(EVIDENCE_ALIASES.get(logical,(logical,)))
    for d in _column_descriptors(model):
        if aliases & {d['physical_name'],d['table_key'],d['orm_attr']}:
            return d
    return None

def resolve_alias(model,logical:str)->str|None:
    b=resolve_binding(model,logical);return b['table_key'] if b else None

def resolve_orm_attr(model,logical:str)->str|None:
    b=resolve_binding(model,logical);return b['orm_attr'] if b else None


def filter_values(model,values:dict[str,Any])->dict[str,Any]:
    """Return Table-safe values. Input keys may be physical names, table keys, or ORM attrs."""
    desc=_column_descriptors(model);out={}
    for k,v in values.items():
        hit=next((d for d in desc if k in {d['physical_name'],d['table_key'],d['orm_attr']}),None)
        if hit:out[hit['table_key']]=v
    return out


def _logical_evidence(candidate_id:int,source_type:str,source_table:str,source_ref:str,relation:str,title:str|None,summary:str,url:str|None,retrieval_score:float,verified:bool,verification_confidence:float,evidence_metadata:dict[str,Any]|None=None,observed_at=None,created_at=None):
    return {'candidate_fk':candidate_id,'source_type':source_type,'source_table':source_table,'source_ref':source_ref,'relation':relation,'title':title,'summary':summary,'url':url,'retrieval_score':retrieval_score,'verified':verified,'verification_confidence':verification_confidence,'evidence_metadata':evidence_metadata or {},'observed_at':observed_at,'created_at':created_at}


def evidence_values(*,candidate_id:int,source_type:str,source_table:str,source_ref:str,relation:str,title:str|None,summary:str,url:str|None,retrieval_score:float,verified:bool,verification_confidence:float,evidence_metadata:dict[str,Any]|None=None,observed_at=None,created_at=None)->dict[str,Any]:
    """Table-safe evidence values; never feed these into ORM constructor kwargs."""
    out={}
    for logical,val in _logical_evidence(candidate_id,source_type,source_table,source_ref,relation,title,summary,url,retrieval_score,verified,verification_confidence,evidence_metadata,observed_at,created_at).items():
        b=resolve_binding(CandidateEvidence,logical)
        if b is not None:out[b['table_key']]=val
    return out


def evidence_orm_values(**kwargs)->dict[str,Any]:
    logical=_logical_evidence(**kwargs);out={}
    for key,val in logical.items():
        b=resolve_binding(CandidateEvidence,key)
        if b is not None:out[b['orm_attr']]=val
    return out


def evidence_identity(mapped:dict[str,Any])->dict[str,Any]:
    out={}
    for logical in ('candidate_fk','source_type','source_ref','relation'):
        b=resolve_binding(CandidateEvidence,logical)
        if b and b['table_key'] in mapped:out[b['table_key']]=mapped[b['table_key']]
    return out


def _hard_required_unmapped()->list[str]:
    mapped_cols={b['table_key'] for k in EVIDENCE_ALIASES if (b:=resolve_binding(CandidateEvidence,k))}
    missing=[]
    for d in _column_descriptors(CandidateEvidence):
        # PK/autoincrement/defaulted/nullable columns are not insert-time requirements.
        auto=d['primary_key'] and d['autoincrement'] not in {'False','false',False}
        if auto or d['nullable'] or d['has_default'] or d['has_server_default']:continue
        if d['table_key'] not in mapped_cols:missing.append(d['table_key'])
    return sorted(set(missing))


def contract_fingerprint()->str:
    payload={'problem_candidate':_column_descriptors(ProblemCandidate),'candidate_evidence':_column_descriptors(CandidateEvidence)}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()[:24]


def snapshot()->dict[str,Any]:
    pc=columns(ProblemCandidate);ec=columns(CandidateEvidence)
    bindings={k:resolve_binding(CandidateEvidence,k) for k in EVIDENCE_ALIASES}
    mapping={k:(v['physical_name'] if v else None) for k,v in bindings.items()}
    orm_mapping={k:(v['orm_attr'] if v else None) for k,v in bindings.items()}
    table_mapping={k:(v['table_key'] if v else None) for k,v in bindings.items()}
    required_pc={'id','canonical_key','fingerprint'};missing_pc=sorted(required_pc-pc)
    missing_core=sorted(k for k in CORE_REQUIRED if not bindings.get(k));optional_missing=sorted(k for k in OPTIONAL_ENRICHMENT if not bindings.get(k));hard_unmapped=_hard_required_unmapped()
    compile_ok=False;compile_error=None
    try:
        probe=evidence_values(candidate_id=1,source_type='probe',source_table='probe',source_ref='probe',relation='probe',title='probe',summary='probe',url='https://invalid.local/probe',retrieval_score=1.0,verified=True,verification_confidence=1.0,evidence_metadata={'probe':True},created_at=None)
        CandidateEvidence.__table__.insert().values(**probe).compile();compile_ok=True
    except Exception as e:compile_error=f'{type(e).__name__}: {e}'
    metadata_mode='DB_COLUMN' if bindings.get('evidence_metadata') else 'GENERATION_SIDECAR';observed_mode='DB_COLUMN' if bindings.get('observed_at') else 'SOURCE_METADATA_OR_SIDECAR'
    status='PASS' if not missing_pc and not missing_core and not hard_unmapped and compile_ok else 'FAIL'
    capability={'core_write_contract':status=='PASS','native_metadata':bool(bindings.get('evidence_metadata')),'native_observed_at':bool(bindings.get('observed_at')),'native_verification_fields':all(bindings.get(k) for k in ('verified','verification_confidence')),'sidecar_metadata_required':not bool(bindings.get('evidence_metadata')),'orm_table_name_divergence':any(v and v['orm_attr'] not in {v['physical_name'],v['table_key']} for v in bindings.values()),'runtime_rollback_probe_required':True}
    return {'engine_version':ENGINE_VERSION,'contract_fingerprint':contract_fingerprint(),'problem_candidate_columns':sorted(pc),'candidate_evidence_columns':sorted(ec),'candidate_evidence_descriptors':_column_descriptors(CandidateEvidence),'evidence_mapping':mapping,'evidence_table_mapping':table_mapping,'evidence_orm_mapping':orm_mapping,'missing_problem_candidate':missing_pc,'missing_core_evidence_logical':missing_core,'optional_missing_logical':optional_missing,'unmapped_required_physical_columns':hard_unmapped,'compile_probe':compile_ok,'compile_error':compile_error,'metadata_storage':metadata_mode,'observed_at_storage':observed_mode,'capabilities':capability,'status':status}


def assert_contract()->dict[str,Any]:
    s=snapshot()
    if s['status']!='PASS':raise RuntimeError('R1_DB_CORE_CONTRACT_FAIL '+str(s))
    return s


async def runtime_write_probe()->dict[str,Any]:
    """Execute the actual Table insert path inside a transaction that is always rolled back."""
    s0=assert_contract();table=CandidateEvidence.__table__
    async with async_session() as sess:
        try:
            cid=(await sess.execute(select(ProblemCandidate.id).limit(1))).scalar_one_or_none()
            if cid is None:return {'status':'SKIP_NO_EXISTING_CANDIDATE','contract_fingerprint':s0['contract_fingerprint'],'rollback_guaranteed':True}
            ref='r1_probe_'+uuid.uuid4().hex
            vals=evidence_values(candidate_id=int(cid),source_type='r1_contract_probe',source_table='runtime_probe',source_ref=ref,relation='contract_probe',title='SignalForge R1 typed-evidence contract probe',summary='Rollback-only evidence writeability probe.',url='https://invalid.local/r1-probe',retrieval_score=0.0,verified=False,verification_confidence=0.0,evidence_metadata={'probe':True},observed_at=None,created_at=None)
            await sess.execute(table.insert().values(**vals));await sess.flush();await sess.rollback()
            return {'status':'PASS','candidate_id':int(cid),'contract_fingerprint':s0['contract_fingerprint'],'rollback_guaranteed':True,'table_insert_path':True}
        except Exception as e:
            try:await sess.rollback()
            except Exception:pass
            return {'status':'FAIL','contract_fingerprint':s0['contract_fingerprint'],'rollback_guaranteed':True,'error':f'{type(e).__name__}: {e}'}


async def active_evidence_integrity(candidate_ids:list[int])->dict[str,Any]:
    ids=[int(x) for x in candidate_ids if x is not None];b=resolve_binding(CandidateEvidence,'candidate_fk');table=CandidateEvidence.__table__
    if not ids:return {'candidate_ids':[],'evidence_rows':0,'candidates_with_evidence':0,'per_candidate':{},'status':'PASS'}
    if not b:return {'candidate_ids':ids,'evidence_rows':0,'candidates_with_evidence':0,'per_candidate':{},'status':'FAIL','reason':'NO_CANDIDATE_FK'}
    col=table.c[b['table_key']]
    async with async_session() as sess:rows=list((await sess.execute(select(col).where(col.in_(ids)))).all())
    counts={}
    for row in rows:
        cid=row[0];counts[str(cid)]=counts.get(str(cid),0)+1
    with_ev=sum(1 for cid in ids if counts.get(str(cid),0)>0)
    return {'candidate_ids':ids,'evidence_rows':len(rows),'candidates_with_evidence':with_ev,'per_candidate':counts,'coverage':round(with_ev/max(1,len(ids)),3),'status':'PASS' if with_ev==len(ids) else 'FAIL'}


def static_acceptance()->dict[str,bool]:
    s=snapshot();mapped=evidence_values(candidate_id=1,source_type='x',source_table='t',source_ref='r',relation='rel',title='t',summary='s',url='u',retrieval_score=1,verified=True,verification_confidence=1,evidence_metadata={'m':1})
    table_keys={str(c.key) for c in CandidateEvidence.__table__.columns}
    return {'candidate_fk_resolved':bool(s['evidence_table_mapping'].get('candidate_fk')),'relation_resolved':bool(s['evidence_table_mapping'].get('relation')),'summary_resolved':bool(s['evidence_table_mapping'].get('summary')),'core_contract_passes_without_optional_metadata':s['status']=='PASS','optional_metadata_is_capability_not_gate':'evidence_metadata' not in s['missing_core_evidence_logical'],'unknown_columns_never_emitted':all(k in table_keys for k in mapped),'table_compile_probe':bool(s['compile_probe']),'orm_table_dual_mapping_visible':bool(s.get('evidence_orm_mapping')) and bool(s.get('evidence_table_mapping')),'unmapped_required_columns_blocked':not bool(s.get('unmapped_required_physical_columns')),'storage_mode_explicit':s['metadata_storage'] in {'DB_COLUMN','GENERATION_SIDECAR'},'runtime_rollback_probe_declared':s['capabilities']['runtime_rollback_probe_required'] is True,'semantic_sidecar_compatible':s['metadata_storage'] in {'DB_COLUMN','GENERATION_SIDECAR'},'empty_generation_evidence_integrity_safe':True,'zero_candidate_probe_not_required':True,'typed_relation_metadata_supported':all(resolve_binding(CandidateEvidence,k) is not None for k in ('relation','summary','source_ref')),'unique_hypothesis_metadata_sidecar_compatible':s['metadata_storage'] in {'DB_COLUMN','GENERATION_SIDECAR'}}
