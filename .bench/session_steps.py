import json,os,subprocess,sys,collections
BASE=os.path.expanduser("~/.dsh/sessions")
def find(sid):
    for root,dirs,_ in os.walk(BASE):
        for d in dirs:
            if d.startswith("session-"+sid):
                return os.path.join(root,d,"session.v4.jsonl.zstd")
def load(p):
    return [json.loads(l) for l in subprocess.run(["zstd","-dc",p],capture_output=True,text=True).stdout.splitlines() if l.strip()]
def chars(content):
    n=0
    for c in content or []:
        if isinstance(c,dict): n+=len(c.get("text") or "")
    return n
sid=sys.argv[1]
evs=load(find(sid))
t1=next(e["time"] for e in evs if e["type"]=="turn/start" and e["data"].get("turn")==1)
tend=next(e["time"] for e in evs if e["type"]=="turn/end" and e["data"].get("turn")==1)
steps={}
for e in evs:
    if e["type"]=="step/start" and e["data"].get("turn")==1:
        steps[e["data"]["step"]]={"t":e["time"],"calls":[],"result_chars":0}
# usage per step
for e in evs:
    d=e.get("data") or {}
    u=d.get("usage"); s=d.get("step")
    if u and d.get("turn")==1 and s in steps:
        steps[s]["usage"]=u
calls={}
for e in evs:
    d=e.get("data") or {}
    if e["type"]=="tool/call" and d.get("turn")==1:
        calls[d["callId"]]={"name":d["name"].split("__")[-1],"t0":e["time"],"step":d.get("step"),"args":d.get("arguments")}
        steps[d["step"]]["calls"].append(d["callId"])
for e in evs:
    d=e.get("data") or {}
    if e["type"]=="tool/result" and d.get("turn")==1:
        cid=(d.get("message") or {}).get("source",{}).get("callId")
        if cid in calls:
            calls[cid]["dur"]=e["time"]-calls[cid]["t0"]
            n=chars((d.get("message") or {}).get("content"))
            calls[cid]["chars"]=n
            steps[calls[cid]["step"]]["result_chars"]+=n
order=sorted(steps)
print(f"sid={sid} turn1 wall={(tend-t1)/1000:.1f}s steps={len(order)}")
for i,s in enumerate(order):
    st=steps[s]; end=steps[order[i+1]]["t"] if i+1<len(order) else tend
    u=st.get("usage") or {}
    print(f"step {s:2}  {((end-st['t'])/1000):6.2f}s  in={u.get('inputTokens','-'):>5} cache={u.get('cacheReadTokens','-'):>6} out={u.get('outputTokens','-'):>4} resultChars={st['result_chars']:>6}")
    for cid in st["calls"]:
        c=calls[cid]
        note=json.loads(c["args"] or "{}").get("command") or json.loads(c["args"] or "{}").get("targets") or json.loads(c["args"] or "{}").get("question") or ""
        if isinstance(note,(list,dict)): note=json.dumps(note,ensure_ascii=False)
        print(f"        - {c['name']:22} {(c.get('dur',0))/1000:5.2f}s out={c.get('chars',0):>6} {str(note)[:90]}")
