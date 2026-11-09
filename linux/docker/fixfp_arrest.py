#!/usr/bin/env python3
"""FIX-FP probe (pm7-fp-own-head-and-shoulder-fill-left-third-of-view): on foot in first person with
force_wanted=1 until the police arrest him (BUSTED), the star cleared in the ini, then after the
release in first person: still, walk back (Down), walk on, turns; bursts of shots."""
import re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
LOG = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.log"
def setini(key, val):
    t = open(INI, encoding="latin-1").read()
    t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    open(INI, "w", encoding="latin-1").write(t)
def logtxt(): return open(LOG, encoding="latin-1", errors="replace").read()

Q.start("fixfp_arrest")
# the street where the filer was arrested (bil), on foot (GTA2DX9_SCENE_NO_CAR=1)
setini("scene_xy", "130.8,132.7")
tap("F10", 0.3); time.sleep(2.5); say("after warp:", Q.words(D.wait_state()))
Q.set_view("first", settle=1.0)
setini("force_wanted", 2)
t0 = time.time(); n = 0; started = False
while time.time() - t0 < 150:
    if "beat: BUSTED start" in logtxt() or "beat: WASTED start" in logtxt(): started = True; break
    if n % 8 == 0: shot(f"a_wait_{n:03d}")
    n += 1; time.sleep(1.0)
say("RESULT arrest:", "busted" if started else "no arrest")
setini("force_wanted", -1)
t0 = time.time()
while time.time() - t0 < 25:
    if ("beat: BUSTED end" in logtxt() or "beat: WASTED end" in logtxt()): break
    time.sleep(0.5)
say("busted end seen" if ("beat: BUSTED end" in logtxt() or "beat: WASTED end" in logtxt()) else "no busted end")
Q.set_view("first", settle=0.5)
for i in range(8): shot(f"b_still_{i:02d}"); time.sleep(0.15)
for leg, keys in [("back", ["Down"]), ("fwd", ["Up"]), ("backturn", ["Down", "Left"]), ("turn", ["Right"]), ("back2", ["Down"])]:
    for k in keys: D.xdo("keydown", k)
    for i in range(10): shot(f"c_{leg}_{i:02d}"); time.sleep(0.15)
    for k in keys: D.xdo("keyup", k)
    time.sleep(0.3)
say("CHECK", Q.counts()); say("done")
