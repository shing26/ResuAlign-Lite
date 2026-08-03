#!/usr/bin/env python3
# ResuAlign Lite
import argparse,json,os,sys,time
from pathlib import Path

PROVIDER=os.environ.get("LLM_PROVIDER","deepseek")
PK=os.environ.get(PROVIDER.upper()+"_API_KEY","")
MODEL=os.environ.get(PROVIDER.upper()+"_MODEL","deepseek-chat")
_URLS={"deepseek":"https://api.deepseek.com","openrouter":"https://openrouter.ai/api/v1","ollama":"http://localhost:11434/v1"}
BASE=os.environ.get(PROVIDER.upper()+"_BASE_URL",_URLS.get(PROVIDER,"https://api.openai.com/v1"))
if PROVIDER=="ollama":PK="ollama"

class DiffItem:pass
class Analysis:
    def __init__(self):
        self.score=0
        self.issues=[]
        self.skills=[]
        self.diffs=[]

import httpx,fitz

def llm_json(system,user,model=None):
 headers={"Authorization":"Bearer "+PK,"Content-Type":"application/json"}
 body={"model":model or MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0.1,"max_tokens":4096,"response_format":{"type":"json_object"}}
 for _ in range(3):
  try:
   r=httpx.post(BASE.rstrip("/")+"/chat/completions",headers=headers,json=body,timeout=180)
   r.raise_for_status()
   t=r.json()["choices"][0]["message"]["content"]
   a=t.find("{")
   if a<0:return {}
   import json as _json
   obj,_pos=_json.JSONDecoder().raw_decode(t,a)
   return obj
  except Exception as e:
   print("[WARN] LLM call failed (attempt",_+1,"):",e,file=sys.stderr)
   body.pop("response_format",None);time.sleep(1)
 return {}

def parse_pdf(path):
 doc=fitz.open(path)
 r=chr(10).join([l.strip() for p in doc for l in p.get_text().splitlines() if l.strip()])
 doc.close()
 return r

DIAG="You are a resume auditor. Return JSON with score 0-100, issues(list), skills(list). Output ONLY JSON."
TAIL="You are a precise resume editor. Given a resume and a job description, return JSON with one key: \"diffs\", a list of edit items. Each item: {\"type\":\"modify|add|remove\",\"original\":\"exact sentence or empty\",\"proposed\":\"new sentence\",\"reason\":\"why\",\"confidence\":\"high|medium|low\"}. Change ONLY what makes the resume fit the JD better. Never invent skills. Output ONLY a single JSON object, no explanation."

def run(rt,jt=None):
 d=llm_json(DIAG,rt)
 a=Analysis()
 a.score=d.get("score",0);a.issues=d.get("issues",[]);a.skills=d.get("skills",[])
 if jt:
  print("[...] Analyzing JD alignment...")
  for item in llm_json(TAIL,rt+chr(10)*2+"JD:"+chr(10)+jt).get("diffs",[]):
   di=DiffItem();di.type=item.get("type","modify");di.original=item.get("original","");di.proposed=item.get("proposed","");di.reason=item.get("reason","");di.confidence=item.get("confidence","medium")
   a.diffs.append(di)
  print("[OK]",len(a.diffs),"alignment suggestions")
 return a

if __name__=="__main__":
 p=argparse.ArgumentParser()
 p.add_argument("resume");p.add_argument("--jd","-j");p.add_argument("--model","-m")
 args=p.parse_args()
 if not Path(args.resume).exists():print("Error: file not found:",args.resume);sys.exit(1)
 if args.model:MODEL=args.model
 t0=time.monotonic()
 rt=parse_pdf(args.resume);print("[OK]",len(rt),"chars extracted")
 jt=None
 if args.jd:jt=Path(args.jd).read_text(encoding="utf-8") if Path(args.jd).exists() else args.jd;print("[OK] JD:",len(jt),"chars")
 a=run(rt,jt)
 print("Score:",a.score,"/100")
 print("Skills:"+chr(44).join(a.skills[:10]) if a.skills else "Skills: none")
 if a.issues:
  for i in a.issues:print("  !",i)
 if a.diffs:
  for i,d in enumerate(a.diffs,1):
   tag=" ["+d.confidence.upper()+"]" if d.confidence else " [MEDIUM]"
   print("  #"+str(i)+tag,d.reason)
   if d.original:print("    - "+d.original[:120])
   print("    + "+d.proposed[:120])
 print("Time:",round(time.monotonic()-t0,1),"s | Model:",MODEL)
