#!/usr/bin/env python3
"""ACTIONS-3D probe 5: vehicles that are not cars. The renderer's 'vehicles:'
line (GTA2DX9_LOG_VEHICLES=1, every two seconds) lists the live trains (models
59-61), tank (54), fire truck (17), ambulance (34), buses (11, 86), SWAT van
(52) and cop cars (12) with position and heading; the script warps beside each
kind in turn (a block and a half to the side of its line of travel, on its
level) and takes classic / third / first frames while it passes, then follows
it for a few seconds in third person."""
import os, re, sys, time, math
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
def vehicles():
    last = None
    for line in Q.log_text(60000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6]), m[7])
            for m in VEH.findall(last or "")]

ORDER = [(59, 60, 61), (54,), (17,), (34,), (11, 86), (52,)]
s = Q.start("a3_vehicles")
Q.set_view("third", settle=0.5)
t0 = time.time(); done = set(); n = 0
while time.time() - t0 < float(os.environ.get("A3_VEH_SECS", "330")):
    vs = vehicles()
    say("vehicles seen:", sorted(set(v[0] for v in vs)))
    pick = None
    for group in ORDER:
        if group in done: continue
        c = [v for v in vs if v[0] in group]
        if c: pick = (group, c[0]); break
    if not pick:
        # wander: warp somewhere else to let other kinds spawn
        spots = [(120.5, 60.5, 2), (60.5, 120.5, 2), (200.5, 200.5, 2), (150.5, 180.5, 2), (90.5, 160.5, 2)]
        x, y, l = spots[n % len(spots)]; n += 1
        T.warp(x, y, l, why="wander for vehicles"); time.sleep(4.0)
        continue
    group, (m, x, y, z, fx, fy, d, ptr) = pick
    side = 1.5
    wx, wy = x - fy * side + fx * 3.0, y + fx * side + fy * 3.0   # ahead of it and to the side
    say(f"MARK vehicle m{m} at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}: warp to {wx:.1f},{wy:.1f}")
    T.warp(round(wx, 1), round(wy, 1), int(round(z)), why=f"beside model {m}")
    L = f"v_m{m}"
    Q.set_view("third", settle=0.3)
    for k in range(6): shot(f"{L}_t{k}"); time.sleep(0.35)
    Q.set_view("first", settle=0.3)
    for k in range(5): shot(f"{L}_f{k}"); time.sleep(0.35)
    Q.set_view("classic", settle=0.3); shot(f"{L}_c")
    Q.set_view("third", settle=0.3)
    for k in range(4): hold("Left", 0.3); shot(f"{L}_t2_{k}")
    done.add(group)
    if len(done) == len(ORDER): break
A.finish()
