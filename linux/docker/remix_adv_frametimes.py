#!/usr/bin/env python3
"""REMIX-ADVANCED: frame cost in the bench windows of remix_adv.py runs.
  remix_adv_frametimes.py <run dir> [<run dir> ...]
Reads <run>/frames.tsv (GTA2DX9_FRAME_LOG, one line per frame) and <run>/marks.txt
(bench_<tag>_<tod>_begin n=<line>, ..._still_end n=, ..._end n=). Per window: frames, the
frame cost (whole minus the 30 fps cap's wait) p50/p90/p99/max and the present stage
(the CPU waits in Present for the GPU's path tracing) p50/p99."""
import re, statistics, sys

def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))] if v else float("nan")

def windows(run):
    marks = {}
    for line in open(f"{run}/marks.txt"):
        m = re.search(r"(bench_\S+?)_(begin|still_end|end) n=(-?\d+)", line)
        if m: marks.setdefault(m.group(1), {})[m.group(2)] = int(m.group(3))
    return marks

def main():
    for run in sys.argv[1:]:
        rows = open(f"{run}/frames.tsv").read().splitlines()
        head = rows[0].split("\t"); ix = {h: i for i, h in enumerate(head)}
        def col(a, b, name):
            out = []
            for r in rows[max(a, 1):b]:
                f = r.split("\t")
                if len(f) < len(head): continue
                try:
                    if name == "cost": out.append(float(f[ix["whole"]]) - float(f[ix["wait"]]))
                    else: out.append(float(f[ix[name]]))
                except ValueError: pass
            return out
        print(f"== {run}  ({len(rows) - 1} frames logged)")
        for name, w in sorted(windows(run).items()):
            for part, a, b in (("still", w.get("begin"), w.get("still_end")), ("turn", w.get("still_end"), w.get("end"))):
                if a is None or b is None or a < 0: continue
                c, p = col(a, b, "cost"), col(a, b, "present")
                if not c: continue
                print(f"{name:28s} {part:5s} n={len(c):4d} cost p50 {pct(c,50):6.1f} p90 {pct(c,90):6.1f} "
                      f"p99 {pct(c,99):6.1f} max {max(c):6.1f} | present p50 {pct(p,50):6.1f} p99 {pct(p,99):6.1f} "
                      f"| fps(1000/mean cost) {1000 / statistics.mean(c):5.1f}")

if __name__ == "__main__":
    main()
