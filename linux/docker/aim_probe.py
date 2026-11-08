#!/usr/bin/env python3
"""QB-6 probe: the aim camera, the reticle and the hit markers. Picks up the pistol
(obj1) and the COLLECT_02 machine gun in Downtown, then on busy pavements fires
bursts in third person (turning a little between bursts so people cross the line
of fire) and in first person, with a screenshot every ~0.1 s while firing.
Run with GTA2_DIRECT_KEYS=1, INI_SED adding set_player_ammo=300 under [devtools], INI_SED scene_key=F11 and -e SCENE_KEY=F11."""
import sys, time, shutil
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import tour_lib as T

def pick(x, y, lvl, name):
    s = T.warp(x, y, lvl, why=name)
    hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
    s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
    say("at", f"{s['x']:.2f},{s['y']:.2f}", "pickup", name)
    time.sleep(0.8)

def burst(label, seconds, every=0.08):
    n = 0; t0 = time.time()
    D.xdo("keydown", "Control_L")
    while time.time() - t0 < seconds:
        shot(f"{label}_{n:02d}"); n += 1
        time.sleep(every)
    D.xdo("keyup", "Control_L")
    for k in range(4):   # the markers fade over 0.25-0.45 s
        time.sleep(0.1); shot(f"{label}_after{k}")

import re, math
NEAR = re.compile(r"aim: near ped x=([\d.]+) y=([\d.]+) d=([\d.]+)")

def nearest():
    m = None
    for m in NEAR.finditer(D.log_tail()[-6000:]): pass
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None

def face(tx, ty, tries=4):
    for _ in range(tries):
        s = D.wait_state(); a = D.angle_to(s, tx, ty)
        if abs(a) < 0.10: return True
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, max(0.04, min(0.6, abs(a) / max(D.rate, 0.5)))); time.sleep(0.25)
    return False

def hunt(tag, seconds, view):
    t0 = time.time(); n = 0
    while time.time() - t0 < seconds:
        p = nearest()
        if not p:
            hold("Left", 0.3); time.sleep(0.5); continue
        face(p[0], p[1])
        shot(f"{tag}_{view}_h{n:02d}_aim")
        burst(f"{tag}_{view}_h{n:02d}", float(os.environ.get("AIM_BURST", "2.0")), every=0.15)
        n += 1

s = Q.start("aim_probe")
import os
if os.environ.get("AIM_PISTOL", "0") == "1": pick(166.5, 140.5, 2, "pistol")
pick(154.5, 129.5, 3, "machine gun")   # kept loaded by [devtools] set_player_ammo when the run sets it
for (x, y, lvl, tag, tsec, fsec) in [(150.5, 133.5, 3, "st1", 60, 30)]:
    s = T.warp(x, y, lvl, why=tag)
    Q.set_view("third", settle=1.5)
    shot(f"{tag}_armed_idle")
    hunt(tag, tsec, "t")
    Q.set_view("first", settle=1.2)
    shot(f"{tag}_fp_idle")
    hunt(tag, fsec, "f")
say("CHECK", Q.counts())
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
say("done")
