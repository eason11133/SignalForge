from __future__ import annotations
import json,os,re
from pathlib import Path
from processors.discovery_symmetric_contracts_u27 import ASPECTS,VERDICTS,norm_space,sha256_text,canonical_json

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

class SymmetricJudge:
    def __init__(self,repo:Path,max_calls=6,criteria_batch=8,judge_batch=8,client_factory=None):
        self.repo=repo;self.env=load_project_env(repo);self.calls=0;self.errors=[]
        self.max_calls=max_calls;self.criteria_batch=criteria_batch;self.judge_batch=judge_batch
        self.model=os.getenv("SIGNALFORGE_U27_MODEL","gpt-5-mini");self.client_factory=client_factory
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None
    def _client(self):
        if self.client_factory:return self.client_factory()
        from openai import OpenAI
        return OpenAI()
    def _ask(self,prompt):
        if self.calls>=self.max_calls:raise RuntimeError("U27_LLM_CALL_BUDGET_EXHAUSTED")
        self.calls+=1;cl=self._client();text=None
        if hasattr(cl,"responses"):
            r=cl.responses.create(model=self.model,input=prompt);text=getattr(r,"output_text",None)
        if not text and hasattr(cl,"chat"):
            r=cl.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
            text=r.choices[0].message.content
        if not text:raise RuntimeError("U27_EMPTY_LLM_RESPONSE")
        m=re.search(r"\{.*\}",text,re.S)
        return json.loads(m.group(0) if m else text)

    def build_criteria(self,cases,pointwise,canonical_pairs):
        out={}
        for st in range(0,len(cases),self.criteria_batch):
            batch=cases[st:st+self.criteria_batch];items=[]
            for c in batch:
                x,y=canonical_pairs[c["case_id"]]
                items.append({
                  "case_id":c["case_id"],
                  "item_1":{"id":x["id"],"text":x["text"][:1800],"pointwise":pointwise.get(x["id"],{})},
                  "item_2":{"id":y["id"],"text":y["text"][:1800],"pointwise":pointwise.get(y["id"],{})},
                })
            prompt=(
              "SignalForge CRITERIA BUILDER. You are NOT deciding whether two items are same or different. "
              "Weak labels, candidate kind, and previous judgments are unavailable. "
              "For each case, derive one ORDER-INVARIANT comparison criterion per aspect from the two supplied texts and grounded pointwise facts. "
              "Return JSON {\"cases\":[...]}. Each case: case_id and aspects. For WORKFLOW, FRICTION, MECHANISM, CONSTRAINT, CONSEQUENCE return "
              "{\"criterion\":\"what semantic property must be compared\", \"usable\":true|false}. "
              "Set usable=false if the texts do not contain enough information to compare that aspect. "
              "Criterion must not mention item_1/item_2, A/B, first/second, labels, or a verdict. "
              "Do not infer demand/WTP/opportunity. Cases="+json.dumps(items,ensure_ascii=False)
            )
            try:
                data=self._ask(prompt);valid={x["case_id"] for x in batch}
                for item in data.get("cases") or []:
                    cid=str(item.get("case_id") or "")
                    if cid not in valid:continue
                    aspects={}
                    for a in ASPECTS:
                        z=(item.get("aspects") or {}).get(a) or {}
                        crit=norm_space(z.get("criterion") or "")[:350]
                        usable=bool(z.get("usable")) and bool(crit)
                        banned=any(t in crit.lower() for t in ("item_1","item_2","item 1","item 2","first item","second item"))
                        if banned:usable=False
                        aspects[a]={"criterion":crit if not banned else "","usable":usable}
                    ch=sha256_text(canonical_json(aspects))
                    out[cid]={"aspects":aspects,"criteria_hash":ch}
            except Exception as e:self.errors.append(f"CRITERIA:{type(e).__name__}:{e}"[:500])
        return out

    def judge(self,cases,pointwise,criteria,reverse=False):
        out={}
        for st in range(0,len(cases),self.judge_batch):
            batch=cases[st:st+self.judge_batch];items=[]
            for c in batch:
                left_id=c["right_observation_key"] if reverse else c["left_observation_key"]
                right_id=c["left_observation_key"] if reverse else c["right_observation_key"]
                left_text=c["right_text"] if reverse else c["left_text"]
                right_text=c["left_text"] if reverse else c["right_text"]
                cr=criteria.get(c["case_id"]) or {"aspects":{},"criteria_hash":""}
                items.append({
                  "case_id":c["case_id"],"criteria_hash":cr["criteria_hash"],"criteria":cr["aspects"],
                  "X":{"id":left_id,"text":left_text[:1800],"pointwise":pointwise.get(left_id,{})},
                  "Y":{"id":right_id,"text":right_text[:1800],"pointwise":pointwise.get(right_id,{})},
                })
            prompt=(
              "SignalForge SYMMETRIC SEMANTIC JUDGE. For each case you MUST use the supplied shared criteria exactly; do not invent a different criterion. "
              "Weak labels, candidate type, and previous judgments are hidden. X/Y ordering is arbitrary and MUST NOT change the semantic verdict. "
              "Return JSON {\"cases\":[...]}. Each case: case_id, criteria_hash, aspects. "
              "For each WORKFLOW, FRICTION, MECHANISM, CONSTRAINT, CONSEQUENCE return "
              "{\"verdict\":\"SAME|RELATED|DISTINCT|UNKNOWN\",\"reason\":\"brief evidence-based reason\"}. "
              "If criteria usable=false, verdict MUST be UNKNOWN. "
              "SAME = materially the same concept on that criterion; RELATED = connected/nearby but not identical; DISTINCT = materially different; "
              "UNKNOWN = insufficient evidence. Similar wording alone is not SAME. Do not infer market demand/WTP/opportunity. Cases="+json.dumps(items,ensure_ascii=False)
            )
            try:
                data=self._ask(prompt);valid={x["case_id"] for x in batch}
                for item in data.get("cases") or []:
                    cid=str(item.get("case_id") or "")
                    if cid not in valid:continue
                    expected=(criteria.get(cid) or {}).get("criteria_hash","")
                    if str(item.get("criteria_hash") or "")!=expected:
                        self.errors.append("CRITERIA_HASH_MISMATCH:"+cid);continue
                    aspects={}
                    for a in ASPECTS:
                        cr=((criteria.get(cid) or {}).get("aspects") or {}).get(a) or {}
                        z=(item.get("aspects") or {}).get(a) or {}
                        v=str(z.get("verdict") or "UNKNOWN").upper()
                        if not cr.get("usable"):v="UNKNOWN"
                        if v not in VERDICTS:v="UNKNOWN"
                        aspects[a]={"verdict":v,"reason":norm_space(z.get("reason") or "")[:350]}
                    out[cid]={"criteria_hash":expected,"aspects":aspects}
            except Exception as e:self.errors.append(f"JUDGE:{type(e).__name__}:{e}"[:500])
        return out

    def diagnostics(self):
        return {"available":self.available,"model":self.model,"calls":self.calls,"max_calls":self.max_calls,
                "criteria_batch":self.criteria_batch,"judge_batch":self.judge_batch,
                "errors":self.errors,"env":self.env}
