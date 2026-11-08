#!/usr/bin/env python3
"""Frame cost per take step, from GTA2DX9_FRAME_LOG (frames.tsv) and marks.txt, for runs of
the same take (keys_remix_pbr.sh): pbr_frame_cost.py <run dir> [<run dir> ...]
The frame log's t_ms counts from the DLL's first log line, whose wall time is in
gta2dx9.log; marks are epoch seconds. Per step (the frames between a mark and the next,
first 0.5 s dropped): median of whole-minus-limiter-wait and of present (Remix's Present,
where the path tracer's GPU time shows), and the frame count; then the per-run median
over the vis-take steps (h14_/h22_ labels) every run has."""
import datetime, os, re, sys, statistics as st

def load(run):
    log = open(os.path.join(run, "gta2dx9.log"), errors="replace").read(4000)
    m = re.search(r"\[(\d\d):(\d\d):(\d\d)\.(\d+)\]", log)
    day = datetime.datetime.utcfromtimestamp(os.path.getmtime(os.path.join(run, "marks.txt"))).date()
    t0 = datetime.datetime(day.year, day.month, day.day, int(m[1]), int(m[2]), int(m[3]), int(m[4][:3]) * 1000,
                           tzinfo=datetime.timezone.utc).timestamp()
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(run, "frames.tsv"))]
    head = rows[0]; ix = {k: i for i, k in enumerate(head)}
    fr = [(t0 + float(r[ix["t_ms"]]) / 1000, float(r[ix["whole"]]) - float(r[ix["wait"]]), float(r[ix["present"]]))
          for r in rows[1:] if len(r) == len(head)]
    marks = [(float(l.split(None, 1)[0]), l.split(None, 1)[1].strip()) for l in open(os.path.join(run, "marks.txt")) if l.strip()]
    steps = {}
    for (ta, la), (tb, _) in zip(marks, marks[1:]):
        sel = [f for f in fr if ta + 0.5 <= f[0] < tb]
        if len(sel) >= 5:
            steps[la] = (st.median(f[1] for f in sel), st.median(f[2] for f in sel), len(sel))
    return steps

runs = {r: load(r) for r in sys.argv[1:]}
common = sorted(set.intersection(*(set(k for k in s if re.match(r"h\d", k)) for s in runs.values())))
for r, s in runs.items():
    w = [s[k][0] for k in common]; p = [s[k][1] for k in common]
    print(f"{os.path.basename(r)}: {len(common)} common steps, median frame (no limiter wait) {st.median(w):.1f} ms, "
          f"median present {st.median(p):.1f} ms")
for k in common:
    print(k, "  ".join(f"{os.path.basename(r)} {s[k][0]:.1f}/{s[k][1]:.1f} ({s[k][2]})" for r, s in runs.items()))
