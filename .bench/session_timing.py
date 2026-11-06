#!/usr/bin/env python3
"""Turn-1 timing breakdown for DSH sessions (MCP vs CLI benchmark)."""
import json, os, subprocess, sys, collections

BASE = os.path.expanduser("~/.dsh/sessions")

SESSIONS = {
    "c82b154c": "MCP#1 11-03",
    "7ddd1600": "MCP#2 11-06",
    "4516e4f1": "CLI#1",
    "e23ac349": "CLI#2",
    "0e25abab": "CLI#3",
    "ea3835c3": "CLI#4",
    "8ecead0f": "CLI-extra",
    "8c781836": "RUN#5 mixed",
    "ca770c39": "RUN#6 0.6.3",
    "2df482bb": "RUN#7 0.6.4 mixed",
}


def find(sid):
    for root, dirs, _ in os.walk(BASE):
        for d in dirs:
            if d.startswith("session-" + sid):
                return os.path.join(root, d, "session.v4.jsonl.zstd")
    return None


def load(path):
    out = subprocess.run(["zstd", "-dc", path], capture_output=True, text=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def short(name):
    if name.startswith("mcp__bookmark-research__"):
        return name.split("__")[-1]
    return name


def bash_kind(cmd):
    c = cmd or ""
    kinds = []
    if "src/cli.py" in c or "bookmark-research " in c:
        kinds.append("cli.py")
    if "sqlite3" in c:
        kinds.append("sqlite3")
    if "python3 - " in c or "python3 -<<" in c or "<<'PY'" in c or '<<\'PY\'' in c:
        kinds.append("inline-py")
    if "| head" in c or "| tail" in c:
        kinds.append("head/tail")
    if "| jq" in c:
        kinds.append("jq")
    return kinds or ["other-bash"]


def summarize(sid, label):
    path = find(sid)
    if not path:
        return None
    evs = load(path)
    t1 = next((e["time"] for e in evs if e["type"] == "turn/start" and e["data"].get("turn") == 1), None)
    t_end = next((e["time"] for e in evs if e["type"] == "turn/end" and e["data"].get("turn") == 1), None)
    if t1 is None or t_end is None:
        return None
    steps = [e for e in evs if e["type"] == "step/start" and e["data"].get("turn") == 1]

    calls, order = {}, []
    for e in evs:
        d = e.get("data") or {}
        if e["type"] == "tool/call" and d.get("turn") == 1:
            calls[d["callId"]] = {"name": short(d["name"]), "raw": d["name"], "args": d.get("arguments"),
                                  "t0": e["time"], "step": d.get("step")}
            order.append(d["callId"])
    for e in evs:
        d = e.get("data") or {}
        if e["type"] == "tool/result" and d.get("turn") == 1:
            cid = (d.get("message") or {}).get("source", {}).get("callId") or d.get("toolCallId")
            if cid in calls and "t1" not in calls[cid]:
                calls[cid]["t1"] = e["time"]

    by_name = collections.defaultdict(lambda: {"n": 0, "ms": 0.0})
    kinds = collections.Counter()
    detail = []
    tool_ms = 0.0
    for cid in order:
        c = calls[cid]
        dur = (c.get("t1", c["t0"]) - c["t0"]) / 1000.0
        tool_ms += dur
        by_name[c["name"]]["n"] += 1
        by_name[c["name"]]["ms"] += dur
        extra = ""
        if c["name"] == "bash":
            try:
                cmd = json.loads(c["args"] or "{}").get("command", "")
            except Exception:
                cmd = ""
            ks = bash_kind(cmd)
            for k in ks:
                kinds[k] += 1
            extra = " ".join(ks) + " :: " + cmd.replace("\n", " ")[:110]
        detail.append({"n": c["name"], "s": round(dur, 2), "step": c["step"], "note": extra})

    usage = {"out": 0, "first_in": None, "first_cache": None, "peak": 0, "steps_with_usage": 0}
    for e in evs:
        d = e.get("data") or {}
        u = d.get("usage")
        if u and d.get("turn") == 1:
            usage["out"] += u.get("outputTokens", 0)
            if usage["first_in"] is None:
                usage["first_in"] = u.get("inputTokens")
                usage["first_cache"] = u.get("cacheReadTokens")
            usage["peak"] = max(usage["peak"], u.get("totalTokens", 0))
            usage["steps_with_usage"] += 1

    wait = sum(c["s"] for c in detail if c["n"] == "ask_user_question")
    return {
        "sid": sid, "label": label,
        "wall": round((t_end - t1) / 1000.0, 1),
        "wall_no_human": round((t_end - t1) / 1000.0 - wait, 1),
        "steps": len(steps), "calls": len(order),
        "tool_s": round(tool_ms, 1),
        "llm_s": round((t_end - t1) / 1000.0 - tool_ms, 1),
        "s_per_step": round(((t_end - t1) / 1000.0) / max(len(steps), 1), 2),
        "usage": usage,
        "by_tool": {k: {"n": v["n"], "s": round(v["ms"], 2)} for k, v in sorted(by_name.items(), key=lambda kv: -kv[1]["ms"])},
        "bash_kinds": dict(kinds),
        "detail": detail,
    }


if __name__ == "__main__":
    out = []
    for sid, label in SESSIONS.items():
        r = summarize(sid, label)
        if r:
            out.append(r)
    if "--detail" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        hdr = f"{'id':10} {'label':12} {'wall':>6} {'noHuman':>7} {'steps':>5} {'calls':>5} {'tool':>6} {'llm':>6} {'s/step':>6} {'peak':>7} {'out':>6}"
        print(hdr)
        for r in out:
            print(f"{r['sid']:10} {r['label']:12} {r['wall']:6} {r['wall_no_human']:7} {r['steps']:5} {r['calls']:5} "
                  f"{r['tool_s']:6} {r['llm_s']:6} {r['s_per_step']:6} {r['usage']['peak']:7} {r['usage']['out']:6}")
        for r in out:
            print("\n==", r["sid"], r["label"], "bash kinds:", r["bash_kinds"])
            print("   tools:", ", ".join(f"{k}x{v['n']}({v['s']}s)" for k, v in r["by_tool"].items()))
