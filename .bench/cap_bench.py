#!/usr/bin/env python3
"""Per-capability latency bench: fixed tax vs query cost vs payload size.

Runs against a DB copy so the live index (held by the MCP server) is untouched.
Usage: python3 .bench/cap_bench.py [--db PATH] [--source ID]
"""
import argparse, json, os, statistics, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

def ms(v): return round(v * 1000, 2)

def med(fn, n=7, warm=2):
    for _ in range(warm):
        fn()
    out = []
    for _ in range(n):
        t = time.perf_counter(); r = fn(); out.append((time.perf_counter() - t, r))
    return statistics.median(x for x, _ in out), out[-1][1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, ".bench/run7-data/index.sqlite3"))
    ap.add_argument("--source", default="user-bookmark-canvas-package-20261101")
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--live", default=os.path.expanduser("~/.local/share/bookmark-research/index.sqlite3"),
                    help="source index to copy when --db does not exist yet")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        os.makedirs(os.path.dirname(args.db), exist_ok=True)
        # .backup reads the live index without taking the MCP server's writer lock.
        subprocess.run(["sqlite3", args.live, ".backup '%s'" % args.db], check=True)
    os.environ.setdefault("BOOKMARK_RESEARCH_DATA_DIR", os.path.dirname(args.db))

    rows = []
    def rec(cap, fixed, query, payload, note=""):
        rows.append((cap, fixed, query, payload, note))

    # 1. interpreter + import floor
    t0 = time.perf_counter(); import bookmark_index; imp = time.perf_counter() - t0
    from bookmark_index import BookmarkIndex
    from source_manager import SourceManager
    from locate import locate as locate_core

    # 2. open cost: readonly vs read-write (rw runs executescript(SCHEMA) every time)
    def open_ro():
        i = BookmarkIndex(args.db, readonly=True); return i
    def open_rw():
        i = BookmarkIndex(args.db); return i
    t_ro, i_ro = med(lambda: (lambda x: (x.close(), x)[1])(open_ro()), args.n)
    t_rw, i_rw = med(lambda: (lambda x: (x.close(), x)[1])(open_rw()), args.n)
    rec("BookmarkIndex open (ro)", 0, ms(t_ro), 0)
    rec("BookmarkIndex open (rw+DDL)", 0, ms(t_rw), 0)

    idx = BookmarkIndex(args.db)
    src = SourceManager(idx)

    # 3. per-call live refresh (what MCP does by default on every locate/read)
    def refresh():
        return src.refresh(args.source)
    t_ref, r = med(refresh, 5)
    rec("SourceManager.refresh (live, no change)", 0, ms(t_ref), 0)

    # 4. capabilities
    def q_search():
        return idx.search(args.source, targets=["3D"], limit=10)
    def q_search_multi():
        return idx.search(args.source, targets=["3D", "2D", "gaussian"], limit=10)
    def q_locate():
        return locate_core(idx, src, {"text": "3D", "in": ["canvas"], "limit": 10, "refresh": False}, wiki=None, raw=None)
    def q_locate_note():
        return locate_core(idx, src, {"text": "3D", "in": ["canvas"], "has_note": True, "limit": 10, "refresh": False}, wiki=None, raw=None)
    def q_context():
        return idx.context(args.source, item_id="tempId_20261026_hash_1i5z632")
    def q_traverse():
        return idx.traverse(args.source, item_id="tempId_20260624_hash_5o102d2", max_depth=2, limit=50)
    def q_lookup():
        return idx.lookup_url("https://app.unifans.io/posts/5de382cab28ea4f0be886de14a8e45cb")
    def q_count():
        return idx.search(args.source, targets=["3D"], count_only=True)

    for name, fn in [("search (1 target, 10 hits)", q_search), ("search (3 targets)", q_search_multi),
                     ("locate (text)", q_locate), ("locate (text+has_note)", q_locate_note),
                     ("context (1 item)", q_context), ("traverse (depth2)", q_traverse),
                     ("lookup-url", q_lookup), ("search count-only", q_count)]:
        t, res = med(fn, args.n)
        size = len(json.dumps(res, ensure_ascii=False, default=str))
        rec(name, 0, ms(t), size)

    # 5. payload share of the tool-call cost: json.dumps of the same result
    t_out, _ = med(lambda: len(json.dumps(q_locate(), ensure_ascii=False, default=str)), args.n)
    rec("render locate payload (json.dumps)", 0, ms(t_out), 0)

    print(f"{'capability':34} {'ms':>8} {'payload B':>10}")
    for cap, _, q, p, _ in rows:
        print(f"{cap:34} {q:8.2f} {p:10}")
    print(f"\nimport bookmark_index: {ms(imp)} ms")
    print(f"python startup floor: {ms(float(subprocess.run([sys.executable,'-c','import time;t=time.perf_counter();print(time.perf_counter()-t)'],capture_output=True,text=True).stdout.strip() or 0))}")

if __name__ == "__main__":
    main()
