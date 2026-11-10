#!/usr/bin/env python3
"""REMIX-PARITY-1: per-camera frame cost of rp1_cams.py takes.
  rp1_cost.py <run dir> [...]   reads frames.tsv + marks.txt (bench_S<i>_c<j>_begin/end n=<line>).
Prints whole (frame interval) and present (CPU blocked in Present = GPU path tracing) p50/p90 per window."""
import re, sys
def pct(v, p):
    v = sorted(v); return v[min(len(v)-1, int(round(p/100*(len(v)-1))))] if v else float("nan")
for run in sys.argv[1:]:
    rows = open(f"{run}/frames.tsv").read().splitlines(); head = rows[0].split("\t"); ix = {h: i for i, h in enumerate(head)}
    w = {}
    for line in open(f"{run}/marks.txt"):
        m = re.search(r"bench_(S\d+_c\d+)_(begin|end) n=(-?\d+)", line)
        if m: w.setdefault(m.group(1), {})[m.group(2)] = int(m.group(3))
    print(run)
    for k, d in w.items():
        if "begin" not in d or "end" not in d: continue
        wh, pr = [], []
        for r in rows[max(d["begin"], 1):d["end"]]:
            f = r.split("\t")
            if len(f) < len(head): continue
            wh.append(float(f[ix["whole"]])); pr.append(float(f[ix["present"]]))
        print(f"  {k}: n={len(wh)} whole p50 {pct(wh,50):.1f} p90 {pct(wh,90):.1f} ms ({1000/max(pct(wh,50),1e-3):.1f} fps)  present p50 {pct(pr,50):.1f} p90 {pct(pr,90):.1f}")
