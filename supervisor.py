#!/usr/bin/env python3
import json, os, re, shutil, subprocess, sys, threading, time, uuid, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).parent; PORT=int(os.getenv('SUPERVISOR_PORT','8765'))
UI_PATH=ROOT/'index.html'
if not UI_PATH.exists(): UI_PATH=Path(sys.prefix)/'share'/'codex-supervisor'/'index.html'
def find_codex():
 configured=os.getenv('CODEX_BIN')
 if configured: return configured
 found=shutil.which('codex')
 if found: return found
 mac='/Applications/ChatGPT.app/Contents/Resources/codex'
 return mac if Path(mac).exists() else 'codex'
CODEX_BIN=find_codex()
DEFAULT_CODEX_SOCKET=Path.home()/'.codex'/'app-server-control'/'app-server-control.sock'
USE_OLLAMA=os.getenv('SUPERVISOR_USE_OLLAMA','0')=='1'
state={'status':'DISCONNECTED','objective':'Select a Codex task to observe.','currentAction':'','progress':[],'filesChanged':[],'tests':'','lastSuccess':'','blocker':'','scopeDrift':'None','needsUser':'No','nextAction':'','assessment':'','steering':'','events':[],'threads':[],'connected':None,'observedName':'','observedPath':'','lastEvidence':'','lastInterpretation':'','lastAnalysisAt':'','lastEventAt':''}
lock=threading.Lock(); rpc_id=0
analysis_due=0
analysis_timer=None
analysis_epoch=0
watch_generation=0
recent_event_keys=[]

def codex_command():
 mode=os.getenv('SUPERVISOR_CODEX_TRANSPORT','auto').lower()
 configured_socket=os.getenv('SUPERVISOR_CODEX_SOCKET')
 socket_path=Path(configured_socket).expanduser() if configured_socket else DEFAULT_CODEX_SOCKET
 if mode=='stdio' or (mode=='auto' and not socket_path.exists()):
  return [CODEX_BIN,'app-server','--stdio']
 command=[CODEX_BIN,'app-server','proxy']
 if configured_socket: command += ['--sock',str(socket_path)]
 return command

def commentary_state(detail):
 text=' '.join(detail.lower().split())
 passed=bool(re.search(r'\b(final (?:run|test) passed|all tests passed|completed successfully|task (?:is )?complete|finished successfully)\b',text))
 handoff=bool(re.search(r'\b(ready (?:for (?:you|user|jeremy) )?(?:to test|for testing|to review|for review)|launched and ready)\b',text))
 if passed and handoff: return 'READY FOR REVIEW','Yes'
 if passed: return 'COMPLETE','No'
 return 'WORKING','No'

def final_state(detail):
 text=' '.join(detail.lower().split())
 handoff=bool(re.search(r'\bready (?:for (?:you|user|jeremy) )?(?:to test|for testing|to review|for review)\b',text))
 request=bool(re.search(r"\b(blocked|cannot|can't|need you|waiting for|reply|approval required)\b",text))
 if handoff: return 'READY FOR REVIEW','Yes'
 if request: return 'WAITING FOR USER','Yes'
 return 'COMPLETE','No'

def compact_event(kind,detail):
 text=' '.join(str(detail).split())
 if kind=='tool/exec' and 'write_stdin' in text: return ('build/poll','Polled the running build or test process.')
 if kind=='tool/result':
  milestones=re.findall(r'\[\s*(\d+)%\].{0,120}?(?:Built target|Linking|Building)[^\n]{0,180}',str(detail))
  passes=re.findall(r'(?im)^(?:PASS|FAILED|ERROR)(?:[: ].{0,240})$',str(detail))
  if passes: return ('test/result',' | '.join(passes[-4:])[:700])
  if milestones:
   pct=re.findall(r'\[\s*(\d+)%\]',str(detail)); target=re.findall(r'Built target ([^\n]+)',str(detail))
   summary=('Build '+(pct[-1]+'%' if pct else 'progress'))+('; built '+', '.join(target[-3:]) if target else '')
   return ('build/progress',summary[:500])
 if kind.startswith('tool/') and len(text)>700: text=text[:700]+'…'
 return kind,text

class AppServer:
 def __init__(self):
  self.p=subprocess.Popen(codex_command(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
  self.pending={}; threading.Thread(target=self.read,daemon=True).start()
  self.call('initialize',{'clientInfo':{'name':'codex-supervisor','title':'CODEX SUPERVISOR','version':'0.1.0'},'capabilities':{}})
  self.send({'method':'initialized'})
 def send(self,x): self.p.stdin.write(json.dumps(x)+'\n'); self.p.stdin.flush()
 def call(self,m,params):
  global rpc_id; rpc_id+=1; i=rpc_id; ev=threading.Event(); self.pending[i]=(ev,{})
  self.send({'id':i,'method':m,'params':params}); ev.wait(8); return self.pending.pop(i,(None,{}))[1]
 def read(self):
  for line in self.p.stdout:
   try: x=json.loads(line)
   except: continue
   if 'id' in x and x['id'] in self.pending: self.pending[x['id']][1].update(x.get('result',x)); self.pending[x['id']][0].set()
   elif x.get('method'): handle_event(x)

app=None
def add_event(method,p):
 global analysis_due
 global analysis_timer
 global recent_event_keys
 detail=p.get('_display') if isinstance(p,dict) else None
 method,detail=compact_event(method,detail or json.dumps(p))
 if not detail.strip(): return
 key=method+'|'+detail
 if key in recent_event_keys[-12:]: return
 recent_event_keys=(recent_event_keys+[key])[-40:]
 with lock:
  event_time=time.strftime('%H:%M:%S')
  state['events'].insert(0,{'time':event_time,'kind':method,'detail':detail[:1200]})
  state['lastEventAt']=event_time
  state['events']=state['events'][:40]
  if method=='turn/started': state['status']='WORKING'; state['currentAction']='A turn is running.'
  if method=='turn/completed': state['status']='COMPLETE'; state['lastSuccess']='Turn completed.'
  if 'approval' in method or 'request_user_input' in method: state['status']='WAITING FOR USER'; state['needsUser']='Yes'; state['blocker']='Worker requested user input/approval.'
  if 'commandExecution' in method: state['currentAction']='Running or reporting a terminal command.'
  if 'fileChange' in method: state['currentAction']='Applying or reporting a file change.'
  if method in ('commentary','build/progress','build/poll') or method.startswith('tool/'):
   state['status']='WORKING'
  if method=='commentary':
   state['status'],state['needsUser']=commentary_state(detail)
   if state['needsUser']=='No': state['blocker']=''
   if state['status'] in ('COMPLETE','READY FOR REVIEW'): state['lastSuccess']=detail[:700]
   state['currentAction']=detail[:240]
   state['assessment']='Latest worker update: '+detail[:500]
  elif method=='build/progress': state['currentAction']=detail
  elif method=='test/result': state['currentAction']='Reviewing an explicit test result.'
  elif method=='worker/final':
   state['currentAction']=detail[:240]
   state['assessment']='Worker conclusion: '+detail[:500]
   state['status'],state['needsUser']=final_state(detail)
   if state['status']=='WAITING FOR USER': state['blocker']=detail[:700]
   else: state['blocker']=''; state['lastSuccess']=detail[:700]
  raw=json.dumps(p)
  paths=[]
  def walk(v):
   if isinstance(v,dict):
    for k,x in v.items():
     if k.lower() in ('path','file','file_path','filename') and isinstance(x,str): paths.append(x)
     walk(x)
   elif isinstance(v,list):
    for x in v: walk(x)
  walk(p)
  if paths:
   state['filesChanged']=list(dict.fromkeys(paths))[-12:]
   state['progress'].insert(0, f"Observed {method}: {', '.join(paths[-3:])}")
   state['progress']=state['progress'][:8]
  if any(x in method.lower() for x in ('test','commandexecution')):
   state['tests']='Latest command/test activity observed; inspect the event feed for raw result.'
   state['progress'].insert(0, f"Observed command/test activity ({method}).")
   state['progress']=state['progress'][:8]
  if method=='tool/result' and re.search(r'(?im)^(?:Script failed|FAILED|ERROR)(?:[: ].*)?$',str(detail)):
   state['blocker']=f"A failure was reported by {method}; the worker may already be addressing it."
  state['assessment']=f"Evidence-based view: {state['currentAction'] or 'No live worker action is currently observable.'}"
  if state['status']=='WORKING': state['nextAction']='Continue the current test/change, then verify the result.'
  elif state['status']=='READY FOR REVIEW': state['nextAction']='Jeremy can test or review the completed result.'
  else: state['nextAction']='Wait for a live worker event or user decision.'
  analysis_due=time.time()+12
 if USE_OLLAMA:
  if analysis_timer: analysis_timer.cancel()
  epoch=analysis_epoch; analysis_timer=threading.Timer(12,analysis_loop,args=(epoch,)); analysis_timer.daemon=True; analysis_timer.start()
def handle_event(x):
 p=x.get('params',{}); tid=p.get('threadId') if isinstance(p,dict) else None
 if state.get('connected') and tid and tid!=state['connected']: return
 if state.get('connected') and not tid and x.get('method') not in ('remoteControl/status/changed',): return
 add_event(x.get('method','event'),p)

def rollout_event(record):
 if record.get('type')!='response_item': return None
 p=record.get('payload',{}); typ=p.get('type')
 if typ=='message' and p.get('role')=='assistant' and p.get('phase') in ('commentary','final_answer'):
  text=' '.join(x.get('text','') for x in p.get('content',[]) if isinstance(x,dict))
  kind='commentary' if p.get('phase')=='commentary' else 'worker/final'
  return (kind,text) if text else None
 if typ=='custom_tool_call':
  name=p.get('name','tool'); raw=p.get('input','')
  try:
   parsed=json.loads(raw) if isinstance(raw,str) and raw.startswith('{') else {}
   shown=parsed.get('cmd') or parsed.get('command') or raw
  except: shown=raw
  return ('tool/'+name,str(shown)[:1200])
 if typ=='custom_tool_call_output':
  parts=[]
  for x in p.get('output',[]):
   if isinstance(x,dict) and x.get('text'): parts.append(x['text'])
  return ('tool/result','\n'.join(parts)[:1800]) if parts else None
 return None

def watch_rollout(path,generation):
 try:
  with open(path,errors='replace') as f:
   f.seek(0,2); size=f.tell(); f.seek(max(0,size-350000))
   if f.tell(): f.readline()
   recent=f.readlines()[-160:]
   for line in recent:
    try: event=rollout_event(json.loads(line))
    except: event=None
    if event: add_event(event[0],{'_display':event[1]})
   while generation==watch_generation:
    line=f.readline()
    if not line: time.sleep(.5); continue
    try: event=rollout_event(json.loads(line))
    except: event=None
    if event: add_event(event[0],{'_display':event[1]})
 except Exception as e:
  add_event('watcher/error',{'_display':str(e)})

def analysis_loop(epoch):
 if epoch!=analysis_epoch or time.time()<analysis_due: return
 with lock:
  useful=[e for e in state['events'] if e['kind'] not in ('build/poll','remoteControl/status/changed')]
  useful=[{'time':e['time'],'kind':e['kind'],'detail':e['detail'][:500]} for e in useful[:8]]
  evidence={'objective':state['objective'][:1200],'status':state['status'],'events':useful,'files':state['filesChanged'][-10:],'tests':state['tests'][:500]}
 prompt='''You are a strict, concise technical supervisor. The events are newest-first. Use only explicit evidence; never invent errors, intentions, files, tests, or generic work such as "checking dependencies." A percentage below 100 is still in progress. "Built target X" proves only X built, not that the whole task completed. If no blocker or user decision is explicit, return an empty string for blocker and No for needsUser. Each progress entry must contain a concrete filename, command result, percentage, or quoted milestone from the evidence. Return JSON only with keys currentAction, progress (array of short factual strings), blocker, scopeDrift (None/Possible/Strong), needsUser (Yes/No), nextAction, assessment, steering. Do not expose hidden reasoning. Evidence:\n'''+json.dumps(evidence)
 with lock: state['lastEvidence']=json.dumps(evidence,indent=2); state['lastAnalysisAt']=time.strftime('%Y-%m-%d %H:%M:%S')
 try:
  req=urllib.request.Request('http://127.0.0.1:11434/api/generate',json.dumps({'model':os.getenv('SUPERVISOR_MODEL','llama3.2:3b'),'prompt':prompt,'stream':False,'format':'json'}).encode(),{'Content-Type':'application/json'})
  result=json.loads(urllib.request.urlopen(req,timeout=90).read()).get('response','')
  out=json.loads(result)
  if epoch!=analysis_epoch: return
  with lock:
   state['lastInterpretation']=json.dumps(out,indent=2)
   for k in ('currentAction','blocker','scopeDrift','needsUser','nextAction','assessment','steering','progress'):
    if k in out and not (state['status']=='WAITING FOR USER' and k in ('blocker','needsUser')): state[k]=out[k]
 except Exception as e:
  with lock: state['events'].insert(0,{'time':time.strftime('%H:%M:%S'),'kind':'local-llm','detail':'Unavailable: '+str(e)[:180]})

def refresh():
 global app
 try:
  app=AppServer(); r=app.call('thread/list',{'archived':False,'limit':50});
  with lock: state['threads']=r.get('data',r.get('threads',[]))
 except Exception as e: state['blocker']=str(e)
def attach(tid):
 global watch_generation
 global analysis_epoch, analysis_timer, recent_event_keys
 r=app.call('thread/resume',{'threadId':tid,'excludeTurns':True})
 tr=r.get('thread',{}); items=[]; page=app.call('thread/items/list',{'threadId':tid,'limit':200})
 items=page.get('data',page.get('items',[]))
 with lock:
  meta=next((x for x in state.get('threads',[]) if (x.get('id') or x.get('threadId'))==tid),{})
  analysis_epoch+=1
  if analysis_timer: analysis_timer.cancel(); analysis_timer=None
  recent_event_keys=[]
  for key,value in {'events':[],'progress':[],'filesChanged':[],'tests':'','lastSuccess':'','blocker':'','currentAction':'','assessment':'','steering':'','lastEvidence':'','lastInterpretation':'','lastAnalysisAt':'','lastEventAt':'','scopeDrift':'None','needsUser':'No'}.items(): state[key]=value
  state['connected']=tid; state['observedName']=meta.get('name') or meta.get('title') or tid; state['observedPath']=meta.get('cwd','')
  user=next((i for i in items if i.get('type') in ('userMessage','user_message','message') and (i.get('role') in (None,'user'))),None)
  def text(v):
   if isinstance(v,str): return v
   if isinstance(v,list): return ' '.join(text(x) for x in v)
   if isinstance(v,dict): return text(v.get('text',v.get('value',v.get('content',''))))
   return ''
  objective=text(user.get('content','')) if user else ''
  if not objective:
   objective=meta.get('preview','')
  state['objective']=objective or 'Objective unavailable'
  state['status']='WORKING' if tr.get('status') in ('inProgress','running') else 'CONNECTED'; state['events'].insert(0,{'time':time.strftime('%H:%M:%S'),'kind':'attached','detail':tr.get('name',tid)})
  path=meta.get('path')
  watch_generation+=1; generation=watch_generation
 if path: threading.Thread(target=watch_rollout,args=(path,generation),daemon=True).start()
 else: add_event('watcher/error',{'_display':'No rollout path is available for this task.'})

class H(BaseHTTPRequestHandler):
 def log_message(self,*a): pass
 def do_GET(self):
  if self.path=='/api/state': self.out(state); return
  data=UI_PATH.read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers(); self.wfile.write(data)
 def do_POST(self):
  n=int(self.headers.get('Content-Length',0)); x=json.loads(self.rfile.read(n) or '{}')
  if self.path=='/api/refresh': refresh()
  elif self.path=='/api/attach': attach(x['threadId'])
  self.out({'ok':True})
 def out(self,x): self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(x).encode())

def main():
 refresh(); print(f'CODEX SUPERVISOR: http://127.0.0.1:{PORT}',flush=True); ThreadingHTTPServer(('127.0.0.1',PORT),H).serve_forever()

if __name__=='__main__': main()
