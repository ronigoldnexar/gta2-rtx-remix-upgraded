#!/usr/bin/env python3
"""ACTIONS-3D probe 10, Downtown: the special vehicles where they are. The
renderer's 'vehicles:' line (GTA2DX9_LOG_VEHICLES=1) gives the elevated train
(model 60, along y=25.5 at level 3) and the parked tank and fire truck; the
player stands on the street below the line ahead of the train, faces it, and is
photographed in third person and in first person looking up (the mouse), then
beside the tank and the fire truck. Run with nav_map=0 (tank controls)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
def vehicles():
    last = None
    for line in Q.log_text(60000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5])) for m in VEH.findall(last or "")]

s = Q.start("a3_train")
time.sleep(2.5)
trains = [v for v in vehicles() if v[0] == 60]
say("trains:", trains)
for k in range(3):
    trains = [v for v in vehicles() if v[0] == 60]
    if not trains: time.sleep(2.0); continue
    m, x, y, z, fx, fy = trains[0]
    # ahead of it by eight blocks, on the street below, two blocks to the side
    wx, wy = x + fx * 18.0 - fy * 2.5, y + fy * 18.0 + fx * 2.5
    say(f"MARK train {k} at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}; warp {wx:.1f},{wy:.1f}")
    s = T.warp(round(wx, 1), round(wy, 1), 2, why="ahead of the train")
    A.face(x, y)
    Q.set_view("first", settle=0.2)
    D.xdo("mousemove_relative", "--", "0", "-50"); time.sleep(0.2)
    for i in range(24):
        shot(f"tr{k}_f{i}"); time.sleep(0.3)
        tr = [v for v in vehicles() if v[0] == 60]
        if tr: A.face(tr[0][1], tr[0][2], tries=2)
    D.xdo("mousemove_relative", "--", "0", "50")
    Q.set_view("third", settle=0.3); shot(f"tr{k}_t_after")
    Q.set_view("classic", settle=0.3); shot(f"tr{k}_c")
    A.save_log()
for (m, label, dx, dy) in [(54, "tank", 2.0, -2.0), (17, "firetruck", 2.0, 0.0)]:
    vs = [v for v in vehicles() if v[0] == m]
    if not vs: say("no", label); continue
    _, x, y, z, fx, fy = vs[0]
    say(f"MARK {label} at {x:.1f},{y:.1f},{z:.1f}")
    T.warp(round(x + dx, 1), round(y + dy, 1), int(round(z)), why=label)
    A.face(x, y)
    Q.set_view("third", settle=0.5); shot(f"{label}_t0")
    hold("Left", 0.3); shot(f"{label}_t1")
    Q.set_view("first", settle=0.5); A.face(x, y); shot(f"{label}_f0")
    Q.set_view("classic", settle=0.5); shot(f"{label}_c")
    A.save_log()
A.finish()
