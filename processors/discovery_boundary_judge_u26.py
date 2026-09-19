from __future__ import annotations
import json,os,re
from pathlib import Path
from processors.discovery_boundary_contracts_u26 import ASPECTS,VERDICTS,norm_space

def load_project_env(repo:Path):
    env=repo/".env";before=bool(os.getenv("OPENAI_API_KEY"));method="PROCESS_ENV"
    if not before and env.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env,override=False);method="PYTHON_DOTENV"
        except Exception:
            for raw in env.read_text(encoding="utf-8").splitlines():
                s=raw.strip()
                if not s or s.startswith("#") or "=" not in s:continue
                k,v=s.split("=",1);k=k.strip();v=v.strip().strip('"').strip("'")
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",k):os.environ.setdefault(k,v)
            method="FALLBACK_ENV_PARSER"
    return {"env_file_exists":env.exists(),"openai_key_before":before,
            "openai_key_after":bool(os.getenv("OPENAI_API_KEY")),"method":method}

def grounded_substring(span,text):
    s=norm_space(span);t=norm_space(text)
    if not s or s=="UNKNOWN":return True
    return s in t

class BoundaryJudge:
    def __init__(self,repo:Path,max_calls=6,point_batch=16,pair_batch=8,client_factory=None):
        self.repo=repo;self.env=load_project_env(repo)
        self.max_calls=max_calls;self.point_batch=point_batch;self.pair_batch=pair_batch
        self.calls=0;self.errors=[];self.client_factory=client_factory
        self.model=os.getenv("SIGNALFORGE_U26_MODEL","gpt-5-mini")
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None
    def _client(self):
        if self.client_factory:return self.client_factory()
        from openai import OpenAI
        return OpenAI()
    def _ask(self,prompt):
        if self.calls>=self.max_calls:raise RuntimeError("U26_LLM_CALL_BUDGET_EXHAUSTED")
        self.calls+=1
        cl=self._client();text=None
        if hasattr(cl,"responses"):
            r=cl.responses.create(model=self.model,input=prompt);text=getattr(r,"output_text",None)
        if not text and hasattr(cl,"chat"):
            r=cl.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
            text=r.choices[0].message.content
        if not text:raise RuntimeError("U26_EMPTY_LLM_RESPONSE")
        m=re.search(r"\{.*\}",text,re.S)
        return json.loads(m.group(0) if m else text)
    def pointwise_extract(self,observations):
        out={}
        for st in range(0,len(observations),self.point_batch):
            batch=observations[st:st+self.point_batch]
            prompt=(
              "SignalForge shadow benchmark. Extract only what the text explicitly supports. "
              "Do not infer demand, WTP, market size, opportunity quality, or solution value. "
              "Return JSON {\"items\":[...]}. For each item return id and aspects object with WORKFLOW, FRICTION, "
              "MECHANISM, CONSTRAINT, CONSEQUENCE. Each aspect must be {\"value\":\"short phrase or UNKNOWN\","
              "\"evidence\":\"exact substring from the supplied text or UNKNOWN\"}. "
              "If unsupported use UNKNOWN. Do not use outside knowledge. Items="+json.dumps(
                  [{"id":x["observation_key"],"text":x["text"][:2200]} for x in batch],ensure_ascii=False)
            )
            try:
                data=self._ask(prompt);valid={x["observation_key"]:x for x in batch}
                for item in data.get("items") or []:
                    oid=str(item.get("id") or "")
                    if oid not in valid:continue
                    aspects={};ground=True
                    src=valid[oid]["text"]
                    raw=item.get("aspects") or {}
                    for a in ASPECTS:
                        z=raw.get(a) or {}
                        v=norm_space(z.get("value") or "UNKNOWN")[:320] or "UNKNOWN"
                        ev=norm_space(z.get("evidence") or "UNKNOWN")[:700] or "UNKNOWN"
                        ok=grounded_substring(ev,src)
                        if not ok:ground=False
                        aspects[a]={"value":v,"evidence":ev,"grounded":ok}
                    out[oid]={"aspects":aspects,"all_evidence_grounded":ground}
            except Exception as e:self.errors.append(f"POINT:{type(e).__name__}:{e}"[:500])
        return out
    def pairwise(self,cases,pointwise,reverse=False):
        out={}
        for st in range(0,len(cases),self.pair_batch):
            batch=cases[st:st+self.pair_batch]
            items=[]
            for c in batch:
                left=c["right"] if reverse else c["left"]
                right=c["left"] if reverse else c["right"]
                items.append({
                  "case_id":c["case_id"],
                  "A":{"id":left["observation_key"],"text":left["text"][:1800],
                       "pointwise":pointwise.get(left["observation_key"],{})},
                  "B":{"id":right["observation_key"],"text":right["text"][:1800],
                       "pointwise":pointwise.get(right["observation_key"],{})},
                })
            prompt=(
              "SignalForge semantic boundary adjudication. Weak labels are intentionally hidden. "
              "Compare A and B independently for each aspect. Return JSON {\"cases\":[...]}. "
              "For every case return case_id and aspects. Each aspect WORKFLOW, FRICTION, MECHANISM, CONSTRAINT, CONSEQUENCE "
              "must contain {\"criteria\":\"short comparison criterion\", \"verdict\":\"SAME|RELATED|DISTINCT|UNKNOWN\"}. "
              "SAME means materially the same semantic concept for that aspect; RELATED means connected/nearby but not identical; "
              "DISTINCT means materially different; UNKNOWN means evidence is insufficient. Similar wording alone is not SAME. "
              "Do not infer market demand/WTP/opportunity. Do not use outside knowledge. Cases="+json.dumps(items,ensure_ascii=False)
            )
            try:
                data=self._ask(prompt)
                valid={x["case_id"] for x in batch}
                for item in data.get("cases") or []:
                    cid=str(item.get("case_id") or "")
                    if cid not in valid:continue
                    aspects={}
                    for a in ASPECTS:
                        z=(item.get("aspects") or {}).get(a) or {}
                        v=str(z.get("verdict") or "UNKNOWN").upper()
                        if v not in VERDICTS:v="UNKNOWN"
                        aspects[a]={"criteria":norm_space(z.get("criteria") or "")[:300],"verdict":v}
                    out[cid]={"aspects":aspects}
            except Exception as e:self.errors.append(f"PAIR:{type(e).__name__}:{e}"[:500])
        return out
    def diagnostics(self):
        return {"available":self.available,"model":self.model,"calls":self.calls,"max_calls":self.max_calls,
                "point_batch":self.point_batch,"pair_batch":self.pair_batch,"errors":self.errors,"env":self.env}
