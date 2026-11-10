#!/usr/bin/env python3
"""FIX-CAR-SHADING-1: frame-time A/B of csh_perf.py. usage: csh_perf_an.py <run dir> (frames.tsv, keys.log, gta2dx9.log)."""
import sys, re, statistics as st
d = sys.argv[1]
log = open(f"{d}/gta2dx9.log", errors="replace").read()
m = re.search(r"\[(\d+):(\d+):(\d+)\.(\d+)\] frame log: t_ms 0", log)
t0 = (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])) * 1000 + int(m[4])
phases = []
cur = None
for line in open(f"{d}/keys.log", errors="replace"):
    mm = re.match(r"(\d+):(\d+):(\d+) MARK coat=(\d) (start|end)", line)
    if not mm: continue
    t = (int(mm[1]) * 3600 + int(mm[2]) * 60 + int(mm[3])) * 1000 - t0
    if mm[5] == "start": cur = (int(mm[4]), t)
    elif cur: phases.append((cur[0], cur[1], t)); cur = None
rows = [l.rstrip("\n").split("\t") for l in open(f"{d}/frames.tsv")]
head, rows = rows[0], rows[1:]
ix = {k: i for i, k in enumerate(head)}
def col(r, k): return float(r[ix[k]])
res = {0: {"busy": [], "cars": [], "present": [], "draws": []}, 1: {"busy": [], "cars": [], "present": [], "draws": []}}
for v, a, b in phases:
    for r in rows:
        t = col(r, "t_ms")
        if a + 1000 <= t <= b:
            res[v]["busy"].append(col(r, "whole") - col(r, "wait"))
            res[v]["cars"].append(col(r, "cars"))
            res[v]["present"].append(col(r, "present"))
            res[v]["draws"].append(col(r, "draws"))
for v in (0, 1):
    q = res[v]
    if not q["busy"]: print(v, "no frames"); continue
    print(f"coat={v}: {len(q['busy'])} frames, busy mean {st.mean(q['busy']):.2f} median {st.median(q['busy']):.2f} ms, "
          f"cars stage mean {st.mean(q['cars']):.3f} ms, present mean {st.mean(q['present']):.2f} ms, draws mean {st.mean(q['draws']):.0f}")
for v, a, b in phases:
    sel = [r for r in rows if a + 1000 <= col(r, "t_ms") <= b]
    if sel: print(f"  phase coat={v} {a/1000:.0f}-{b/1000:.0f} s: busy {st.mean([col(r,'whole')-col(r,'wait') for r in sel]):.2f}, cars {st.mean([col(r,'cars') for r in sel]):.3f}, draws {st.mean([col(r,'draws') for r in sel]):.0f}")
