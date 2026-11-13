#!/usr/bin/env python3
"""drive_report.py <run dir> ...: the drive-through numbers from a run's gta2dx9.log and marks.txt: frame-time stages
(avg of the 256-frame averages, worst of the worsts) inside the drive (marks 'drive start'..'drive end'), the stream's
resident chunks / triangles / buffer KB (mean, max), and the address space's largest free block (min) and commit."""
import datetime, os, re, sys


def secs(hms):
    h, m, s = hms.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)


for run in sys.argv[1:]:
    log = open(os.path.join(run, "gta2dx9.log"), encoding="latin-1").read().splitlines()
    marks = open(os.path.join(run, "marks.txt")).read().splitlines()
    t = {}
    for l in marks:
        ts, what = l.split(" ", 1)
        if what.startswith("drive start") or what.startswith("drive end"):
            t[what.split()[1]] = datetime.datetime.utcfromtimestamp(float(ts)).strftime("%H:%M:%S.%f")
    a, b = secs(t.get("start", "00:00:00")), secs(t.get("end", "23:59:59"))
    stages, worst, res, mem = {}, {}, [], []
    for l in log:
        m = re.match(r"\[(\d\d:\d\d:\d\d\.\d+)\] (.*)", l)
        if not m or not (a <= secs(m.group(1)) <= b):
            continue
        body = m.group(2)
        if body.startswith("frame times"):
            for name, av, wo in re.findall(r"(\w+) ([\d.]+)/([\d.]+)", body):
                stages.setdefault(name, []).append(float(av)); worst[name] = max(worst.get(name, 0), float(wo))
        elif body.startswith("districts stream:"):
            g = re.search(r"resident (\d+) chunks .*?, (\d+) triangles, (\d+) KB", body)
            if g: res.append(tuple(map(int, g.groups())))
        if "largest_free=" in body:
            g = re.search(r"commit private=(\d+)MB.*?largest_free=([\d.]+)MB", body)
            if g: mem.append((int(g.group(1)), float(g.group(2))))
    frame = [sum(v[i] for k, v in stages.items()) for i in range(min(len(v) for v in stages.values()))] if stages else []
    print(f"== {os.path.basename(run)}: drive {t.get('start','?')[:8]}..{t.get('end','?')[:8]}, {len(stages.get('world', []))} frame-log windows")
    for k in ("game", "world", "sprites", "wait"):
        if k in stages:
            print(f"   {k:8s} avg {sum(stages[k]) / len(stages[k]):5.2f} ms  worst {worst[k]:6.1f} ms")
    if stages:
        busy = [sum(v[i] for k, v in stages.items() if k != "wait") for i in range(len(stages["world"]))]
        print(f"   busy (all stages but wait) avg {sum(busy) / len(busy):5.2f} ms, max window {max(busy):5.2f} ms")
    if res:
        print(f"   stream: chunks mean {sum(r[0] for r in res) / len(res):.1f} max {max(r[0] for r in res)}; triangles mean {sum(r[1] for r in res) / len(res):.0f} max {max(r[1] for r in res)}; pool use max {max(r[2] for r in res)} KB")
    if mem:
        print(f"   memory: largest free block min {min(x[1] for x in mem):.1f} MB, commit max {max(x[0] for x in mem)} MB ({len(mem)} samples)")
