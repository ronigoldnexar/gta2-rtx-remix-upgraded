#!/usr/bin/env python3
"""ACTIONS-3D check: arm at the COLLECT_02 pickup (154.5,129.5), fire the machine
gun in third and first person with 4 fps strips (weapon in the hand, muzzle flash,
bullet streaks), then watch the carriageway traffic for lamps (car_lamps=2 via
QA_SED, brake lamps at the lights)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def retarget(x, y):
    t = open(INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={x},{y}", t)
    open(INI, "w", encoding="latin-1").write(t)

def strip(label, seconds, every=0.25, fire=False):
    n = 0; t0 = time.time()
    if fire: D.xdo("keydown", "Control_L")
    while time.time() - t0 < seconds:
        shot(f"{label}_{n:02d}"); n += 1
        time.sleep(every)
    if fire: D.xdo("keyup", "Control_L")

s = Q.start("actions3d")
Q.set_view("third")
retarget(154.5, 129.5)
tap("F10", 0.3); time.sleep(2.0); s = D.wait_state(); say("after F10:", Q.words(s))
for tgt in [(154.5, 129.5), (154.2, 129.8), (154.8, 129.2)]:
    s = D.goto(tgt[0], tgt[1], tol=0.3, limit=20) or D.wait_state()
    say(f"goto {tgt}: at {s['x']:.2f},{s['y']:.2f}")
hold("Up", 0.4); hold("Down", 0.4)
hold("Left", 0.95); time.sleep(0.6)   # about-turn: away from the wall, into the park
shot("a_armed_third")
def bursts(label, n=3):
    k = 0
    for i in range(n):
        D.xdo("keydown", "Control_L")
        t0 = time.time()
        while time.time() - t0 < 1.0:
            shot(f"{label}_{k:02d}"); k += 1
        D.xdo("keyup", "Control_L"); time.sleep(0.35)
        shot(f"{label}_{k:02d}"); k += 1
# Third person: bursts, a quarter turn, bursts.
bursts("b_fire_third")
hold("Left", 0.45); time.sleep(0.4)
bursts("c_fire_third2", 2)
Q.set_view("first"); time.sleep(1.0)
bursts("d_fire_first")
hold("Right", 0.5); time.sleep(0.4)
bursts("e_fire_first2", 2)
say("CHECK", Q.counts())
import shutil
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
say("done"); sys.exit(0)
# Traffic lamps: to the carriageway kerb (the warp needs him out of the attack state).
Q.set_view("third"); time.sleep(3.0)
retarget(164.5, 149.5)
for attempt in range(3):
    tap("F10", 0.3); time.sleep(2.0); s = D.wait_state(); say("after F10 road:", Q.words(s))
    if abs(s["x"] - 164.5) < 3 and abs(s["y"] - 149.5) < 3: break
    hold("Down", 0.3); time.sleep(1.5)
D.goto(164.5, 147.6, tol=0.4, limit=12)
hold("Down", 0.5)   # face the road (south is the carriageway)
def near_cars(label, seconds, want=3.0):
    t0 = time.time(); n = 0
    while time.time() - t0 < seconds and n < 10:
        s = D.wait_state()
        if s and s["car"] and s["cd"] < want:
            say(f"car at d={s['cd']:.1f}"); shot(f"{label}_{n:02d}"); n += 1; time.sleep(0.5)
        else:
            time.sleep(0.3)
    if n == 0: shot(f"{label}_none")
near_cars("f_lamps_third", 45)
Q.set_view("first"); time.sleep(1.0)
near_cars("g_lamps_first", 40)
say("CHECK", Q.counts())
import shutil
try:
    shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log"); say("log copied")
except OSError as e:
    say("log copy failed", e)
say("done")
