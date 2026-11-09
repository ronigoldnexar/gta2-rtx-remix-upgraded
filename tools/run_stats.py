#!/usr/bin/env python3
"""Per-run numbers from a run folder: time to the level, frame-stage averages
after the level, worst wait, hitch and fault counts.  run_stats.py out/<run> ..."""
import re, sys, datetime
def t(s): return datetime.datetime.strptime(s, "%H:%M:%S.%f")
for d in sys.argv[1:]:
    try: lines = open(f"{d}/gta2dx9.log", errors="replace").read().splitlines()
    except OSError: print(f"{d}: no log"); continue
    att = lvl = None; rows = []; hit = set(); fault = 0
    for l in lines:
        m = re.match(r"\[(\d\d:\d\d:\d\d\.\d+)\] (.*)", l)
        if not m: continue
        ts, msg = m.groups()
        if att is None and "attached to pid" in msg: att = t(ts)
        if lvl is None and "view: classic (player found" in msg: lvl = t(ts)
        if lvl and msg.startswith("frame times"):
            v = dict(re.findall(r"(\w+) ([\d.]+)/([\d.]+)", msg) and [(k, (float(a), float(b))) for k, a, b in re.findall(r"(\w+) ([\d.]+)/([\d.]+)", msg)])
            rows.append(v)
        if lvl and msg.startswith("hitch @"):   # frames over budget; not "hitch detail @" / "slow sprites @"
            mm = re.match(r"hitch @(\d+)", msg); hit.add(mm.group(1) if mm else msg[:30])
        if "FAULT" in msg: fault += 1
    lt = (lvl - att).total_seconds() if att and lvl else None
    def avg(k, i=0): xs = [r[k][i] for r in rows if k in r]; return sum(xs) / len(xs) if xs else float("nan")
    print(f"{d}: level after {lt if lt is None else round(lt,1)} s | {len(rows)} summaries | game {avg('game'):.1f} world {avg('world'):.1f} sprites {avg('sprites'):.1f} present {avg('present'):.1f} wait {avg('wait'):.1f} (worst wait min {min([r['wait'][1] for r in rows if 'wait' in r] or [float('nan')]):.1f}) | hitch frames {len(hit)} faults {fault}")
