from __future__ import annotations
import json,os,re
from pathlib import Path
from processors.discovery_sentinel_review_contracts_u28 import ASPECTS,VERDICTS,norm_space

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

class SecondPassReviewer:
    def __init__(self,repo:Path,u27_model:str,max_calls=2,batch_size=8,client_factory=None):
        self.repo=repo;self.env=load_project_env(repo);self.calls=0;self.errors=[]
        self.max_calls=max_calls;self.batch_size=batch_size;self.client_factory=client_factory
        self.model=os.getenv("SIGNALFORGE_U28_REVIEW_MODEL") or "gpt-5-mini"
        self.u27_model=u27_model or "UNKNOWN"
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None
        self.independence_level=("MODEL_DISTINCT" if self.model!=self.u27_model else "PROMPT_CONTEXT_DISTINCT_ONLY")
    def _client(self):
        if self.client_factory:return self.client_factory()
        from openai import OpenAI
        return OpenAI()
    def _ask(self,prompt):
        if self.calls>=self.max_calls:raise RuntimeError("U28_LLM_CALL_BUDGET_EXHAUSTED")
        self.calls+=1;cl=self._client();text=None
        if hasattr(cl,"responses"):
            r=cl.responses.create(model=self.model,input=prompt);text=getattr(r,"output_text",None)
        if not text and hasattr(cl,"chat"):
            r=cl.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
            text=r.choices[0].message.content
        if not text:raise RuntimeError("U28_EMPTY_REVIEW_RESPONSE")
        m=re.search(r"\{.*\}",text,re.S)
        return json.loads(m.group(0) if m else text)
    def review(self,cases):
        out={}
        for st in range(0,len(cases),self.batch_size):
            batch=cases[st:st+self.batch_size]
            prompt=(
              "SignalForge SECOND-PASS SENTINEL REVIEW. This is an independent review context. "
              "You cannot see weak labels, candidate type, previous verdicts, forward/reverse order, or prior case status. "
              "The item_1/item_2 order is canonical and has no semantic meaning. Use ONLY the frozen texts and supplied shared criteria. "
              "Return JSON {\"cases\":[...]}. Each case returns case_id, criteria_hash, aspects. "
              "Each aspect WORKFLOW, FRICTION, MECHANISM, CONSTRAINT, CONSEQUENCE returns "
              "{\"verdict\":\"SAME|RELATED|DISTINCT|UNKNOWN\",\"reason\":\"brief evidence-based reason\"}. "
              "If usable=false verdict MUST be UNKNOWN. SAME = materially the same concept; RELATED = connected but not identical; "
              "DISTINCT = materially different; UNKNOWN = insufficient evidence. Do not infer demand/WTP/opportunity/build value. "
              "Cases="+json.dumps(batch,ensure_ascii=False)
            )
            try:
                data=self._ask(prompt);valid={x["case_id"]:x for x in batch}
                for item in data.get("cases") or []:
                    cid=str(item.get("case_id") or "")
                    if cid not in valid:continue
                    expected=valid[cid]["criteria_hash"]
                    if str(item.get("criteria_hash") or "")!=expected:
                        self.errors.append("CRITERIA_HASH_MISMATCH:"+cid);continue
                    aspects={}
                    for a in ASPECTS:
                        cr=(valid[cid]["criteria"].get(a) or {});z=((item.get("aspects") or {}).get(a) or {})
                        v=str(z.get("verdict") or "UNKNOWN").upper()
                        if not cr.get("usable"):v="UNKNOWN"
                        if v not in VERDICTS:v="UNKNOWN"
                        aspects[a]={"verdict":v,"reason":norm_space(z.get("reason") or "")[:350]}
                    out[cid]={"criteria_hash":expected,"aspects":aspects}
            except Exception as e:self.errors.append(f"{type(e).__name__}:{e}"[:500])
        return out
    def diagnostics(self):
        return {"available":self.available,"review_model":self.model,"u27_model":self.u27_model,
                "independence_level":self.independence_level,"calls":self.calls,"max_calls":self.max_calls,
                "batch_size":self.batch_size,"errors":self.errors,"env":self.env}
