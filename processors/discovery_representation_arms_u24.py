from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ.setdefault(_k,"1")
import json,math,os,re
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from scipy.sparse import hstack,csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from processors.discovery_representation_contracts_u24 import clean_text

ACTION_PATTERNS={
 "TRANSFORM":r"\b(convert|transform|format|formatting|export|render|presentation|slides?|powerpoint)\b|轉換|格式",
 "IMPORT_PARSE":r"\b(import|parse|parser|ingest|upload)\b|匯入|解析|上傳",
 "SYNC":r"\b(sync|synchroni[sz]e|replicate)\b|同步",
 "RECORD":r"\b(record|recording|capture)\b|錄製|記錄",
 "ACCESS":r"\b(access|login|permission|auth|authentication)\b|存取|登入|權限",
 "PROCESS":r"\b(process|processing|compute|generate|generation)\b|處理|生成",
}
FRICTION_PATTERNS={
 "DELAY":r"\b(slow|delay|latency|wait|waiting|takes forever)\b|慢|延遲|等待",
 "CRASH_FREEZE":r"\b(crash|freeze|hang|stuck)\b|當機|凍結|卡住",
 "FAILURE":r"\b(fail|failure|error|broken|doesn.t work|unable)\b|失敗|錯誤|無法",
 "STATE_LOSS":r"\b(state loss|lost state|context loss|lost context)\b|狀態遺失|上下文遺失",
 "DATA_LOSS":r"\b(data loss|lost data|missing data)\b|資料遺失",
 "MANUAL_REENTRY":r"\b(manual|re.?enter|copy.?paste|duplicate entry|retype)\b|手動|重複輸入",
 "LIMIT":r"\b(limit|quota|usage cap|rate limit)\b|限制|額度",
 "PRICE_VALUE":r"\b(price|pricing|expensive|subscription|pay|paid|cost)\b|價格|訂閱|付費",
 "QUALITY":r"\b(quality|accuracy|poor output|bad output)\b|品質|準確",
}
CONSTRAINT_PATTERNS={
 "PRIVACY":r"\b(privacy|private|confidential|local only|offline)\b|隱私|機密|本地",
 "INTEGRATION":r"\b(integration|integrate|api|connector|plugin)\b|整合",
 "SUBSCRIPTION":r"\b(subscription|paywall|paid plan)\b|訂閱|付費牆",
 "USAGE_LIMIT":r"\b(rate limit|usage limit|quota)\b|使用限制|額度",
}
CONSEQUENCE_PATTERNS={
 "TIME_COST":r"\b(hours?|minutes?|time consuming|takes forever|waste time)\b|耗時|時間",
 "MONEY_COST":r"\b(cost|expensive|price|money)\b|成本|價格|金錢",
 "RISK":r"\b(risk|security|compliance)\b|風險|合規|安全",
}

def build_r0(texts):
    word=TfidfVectorizer(lowercase=True,ngram_range=(1,2),min_df=2,max_df=0.97,max_features=6000,sublinear_tf=True)
    char=TfidfVectorizer(lowercase=True,analyzer="char_wb",ngram_range=(3,5),min_df=2,max_features=4000,sublinear_tf=True)
    Xw=word.fit_transform(texts);Xc=char.fit_transform(texts)
    X=normalize(hstack([Xw,Xc]).tocsr())
    return X,{"word_features":len(word.get_feature_names_out()),"char_features":len(char.get_feature_names_out())},word,Xw

def salient_codes(word_vectorizer,Xw,topn=6):
    names=np.array(word_vectorizer.get_feature_names_out())
    out=[]
    for i in range(Xw.shape[0]):
        row=Xw.getrow(i)
        if row.nnz==0:out.append("UNKNOWN");continue
        order=np.argsort(row.data)[::-1][:topn]
        feats=names[row.indices[order]]
        out.append(" | ".join(feats.tolist()))
    return out

def vectorize_short(texts):
    vec=TfidfVectorizer(lowercase=True,ngram_range=(1,2),analyzer="word",min_df=1,max_features=5000,sublinear_tf=True)
    return normalize(vec.fit_transform(texts)),vec

def _matches(text,patterns):
    out=[]
    for k,p in patterns.items():
        if re.search(p,text,re.I):out.append(k)
    return out or ["UNKNOWN"]

def fixed_atom_text(text):
    t=clean_text(text)
    return " ".join([
      "ACTION="+"+".join(_matches(t,ACTION_PATTERNS)),
      "FRICTION="+"+".join(_matches(t,FRICTION_PATTERNS)),
      "CONSTRAINT="+"+".join(_matches(t,CONSTRAINT_PATTERNS)),
      "CONSEQUENCE="+"+".join(_matches(t,CONSEQUENCE_PATTERNS)),
    ])

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

class FrameExtractor:
    def __init__(self,repo:Path,max_calls=2,batch_size=24,client_factory=None):
        self.env=load_project_env(repo);self.calls=0;self.max_calls=max_calls;self.batch_size=batch_size
        self.model=os.getenv("SIGNALFORGE_U24_FRAME_MODEL","gpt-5-mini");self.client_factory=client_factory
        self.available=bool(os.getenv("OPENAI_API_KEY")) or client_factory is not None
        self.errors=[]
    def _client(self):
        if self.client_factory:return self.client_factory()
        from openai import OpenAI
        return OpenAI()
    def _prompt(self,items):
        compact=[{"id":x["observation_key"],"text":x["text"][:1800],"route":x.get("route")} for x in items]
        return (
          "You are extracting SHADOW semantic structure for SignalForge. Do not infer demand, willingness-to-pay, "
          "market size, opportunity quality, or build recommendations. Use only the supplied text. "
          "For each item return JSON only as {\"items\":[...]}. Each item must contain id, workflow, friction, mechanism, "
          "constraint, consequence, response, emergent_frame. Every field is a short string. If unsupported use UNKNOWN. "
          "workflow = what task/process is being attempted; friction = observed difficulty; mechanism = how/why the friction "
          "occurs if text supports it; constraint = limiting condition; consequence = observed impact; response = workaround "
          "or current response; emergent_frame = concise problem-structure label grounded only in those fields. "
          "Do not collapse UNKNOWN to a guess. Items="+json.dumps(compact,ensure_ascii=False)
        )
    def extract(self,items):
        out={}
        for a in range(0,len(items),self.batch_size):
            if self.calls>=self.max_calls:break
            batch=items[a:a+self.batch_size];self.calls+=1
            try:
                cl=self._client();prompt=self._prompt(batch);text=None
                if hasattr(cl,"responses"):
                    r=cl.responses.create(model=self.model,input=prompt);text=getattr(r,"output_text",None)
                if not text and hasattr(cl,"chat"):
                    r=cl.chat.completions.create(model=self.model,messages=[{"role":"user","content":prompt}],temperature=0)
                    text=r.choices[0].message.content
                if not text:continue
                m=re.search(r"\{.*\}",text,re.S);data=json.loads(m.group(0) if m else text)
                valid={x["observation_key"] for x in batch}
                for x in data.get("items") or []:
                    oid=str(x.get("id") or "")
                    if oid not in valid:continue
                    row={}
                    for k in ("workflow","friction","mechanism","constraint","consequence","response","emergent_frame"):
                        v=clean_text(x.get(k) or "UNKNOWN")[:300]
                        row[k]=v or "UNKNOWN"
                    out[oid]=row
            except Exception as e:
                self.errors.append(f"{type(e).__name__}: {e}"[:500])
        return out
    def diag(self):
        return {"available":self.available,"model":self.model,"max_calls":self.max_calls,"calls":self.calls,
                "batch_size":self.batch_size,"errors":self.errors,"env":self.env}

def frame_serialization(x):
    return " | ".join(f"{k.upper()}={x.get(k,'UNKNOWN')}" for k in
                    ("workflow","friction","mechanism","constraint","consequence","response","emergent_frame"))

def frame_description(x):
    # R4 is deliberately a deterministic description alignment over the same R3 extracted facts:
    # no extra model call, so R3 vs R4 tests representation formatting rather than additional model intelligence.
    return (
      f"Problem frame {x.get('emergent_frame','UNKNOWN')}. "
      f"The workflow is {x.get('workflow','UNKNOWN')}. "
      f"The observed friction is {x.get('friction','UNKNOWN')}. "
      f"The supported mechanism is {x.get('mechanism','UNKNOWN')}. "
      f"The limiting constraint is {x.get('constraint','UNKNOWN')}. "
      f"The consequence is {x.get('consequence','UNKNOWN')}. "
      f"The current response or workaround is {x.get('response','UNKNOWN')}."
    )
