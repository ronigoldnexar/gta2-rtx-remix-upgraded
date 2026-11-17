#!/usr/bin/env python3
# FIX-GETUP: per-frame jump check of each get-up from the GTA2DX9_LOG_GETUP=1 trace: tools/getup_trace.py <gta2dx9.log> [-v]
import re, sys, math, collections
"""per-frame jump check of the figure's pelvis/head/heading through each get-up (getup: trace)"""
log = sys.argv[1]
rx = re.compile(r"getup: f=(\d+) o=(\w+) st=(-?\d+) sub=\w+ pf=(\d+) corpse=(\d) act=(\d+) rev=(\d) kd=(\d) rise=(\d) lie=(\d) t=(-?[\d.]+) aw=([\d.]+) clip=(\S+) rag=(\d) hd=(-?[\d.]+) org (\S+) pel (\S+) head (\S+) lf (-?[\d.]+) rf (-?[\d.]+) g (\S+)")
by = collections.defaultdict(list)
for line in open(log, encoding="latin-1"):
    m = rx.search(line)
    if not m: continue
    g = m.groups()
    p = [float(v) for v in g[16].split(",")]; h = [float(v) for v in g[17].split(",")]
    by[g[1]].append(dict(f=int(g[0]), st=int(g[2]), act=int(g[5]), rev=int(g[6]), kd=int(g[7]), clip=g[12], t=float(g[10]), aw=float(g[11]), rag=int(g[13]), hd=float(g[14]), p=p, h=h, lf=float(g[18]), rf=float(g[19])))
for o, rows in by.items():
    # rise windows: from first rev=1 to 20 frames after the last of that run
    i = 0
    while i < len(rows):
        if rows[i]['rev'] != 1: i += 1; continue
        j = i + 1
        while j < len(rows) and rows[j]['rev'] == 1 and rows[j]['f'] - rows[j - 1]['f'] <= 2: j += 1
        a, b = max(0, i - 3), min(len(rows), j + 20)
        seg = rows[a:b]
        mh = mx = md = mhd = 0.0; fl = 9
        for k in range(1, len(seg)):
            r0, r1 = seg[k - 1], seg[k]
            if r1['f'] - r0['f'] != 1: continue
            mh = max(mh, abs(r1['p'][1] - r0['p'][1]))
            mx = max(mx, math.hypot(r1['p'][0] - r0['p'][0], r1['p'][2] - r0['p'][2]))
            md = max(md, math.dist(r1['h'], r0['h']))
            d = (r1['hd'] - r0['hd'] + math.pi) % (2 * math.pi) - math.pi
            mhd = max(mhd, abs(d))
        for r in rows[i:j]: fl = min(fl, r['lf'], r['rf'])
        print(f"{o} rise f{rows[i]['f']}-{rows[j-1]['f']} ({j-i} fr, clip {rows[i]['clip']} kd={rows[i]['kd']}) max/frame: pelvis dy {mh:.3f} dxz {mx:.3f}, head {md:.3f}, heading {math.degrees(mhd):.1f} deg; lowest foot {fl:.3f}; pelvis {rows[i]['p'][1]:.3f}->{rows[j-1]['p'][1]:.3f}")
        if '-v' in sys.argv:
            for r in seg: print("   ", r['f'], r['act'], r['rev'], r['clip'], f"t={r['t']:.2f} hd={r['hd']:.2f} pel {r['p'][0]:.3f},{r['p'][1]:.3f},{r['p'][2]:.3f} head {r['h'][1]:.3f} lf {r['lf']:.3f} rf {r['rf']:.3f}")
        i = j
