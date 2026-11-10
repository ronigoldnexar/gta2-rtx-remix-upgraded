#!/usr/bin/env python3
"""FIX-AIM-1 (owner10nov B9): a FIGHT_SECS (180) scripted gun fight in third person, played the way a player aims:
pick up the Downtown pistol, then on the wil pavement turn roughly toward the nearest standing civilian within 6 blocks
(FIGHT_TOL radians, default 0.35: about 20 degrees, as coarse as camera-relative arrows allow) and tap the fire key once,
again and again. The renderer's own counter ('aim: shots= with_target= hits= on_highlighted=', the owner's line) is
read from the log at the end. Run with GTA2_DIRECT_KEYS=1, GTA2DX9_STATE_EVERY=3, GTA2DX9_PEDS_EVERY=3, INI_SED
set_player_ammo=300 and scene_key=F11; GTA2DX9_AIM_ASSIST=0 for the assist-off number. keys: keys_fixaim1_fight.sh."""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import fa3_demo as F   # noqa: E402
D, M, Q, T = F.D, F.M, F.Q, F.T
say, tap, hold, mark = F.say, F.tap, F.hold, F.mark
TOL = float(os.environ.get("FIGHT_TOL", "0.35"))


def pick(x, y, lvl, name):
    T.warp(x, y, lvl, why=name)
    hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
    s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
    mark(f"pickup {name} at {s['x']:.2f},{s['y']:.2f}")
    time.sleep(0.8)


mark("fight start")
s = D.wait_state(40)
if not s: mark("NO PLAYER STATE"); sys.exit(1)
D.calibrate_turn()
pick(166.5, 140.5, 2, "pistol")
T.warp(F.WEST + 6.0, F.PAV_Y, 2, why="fixaim1 fight: the pavement"); time.sleep(2.0)
F.view_to("third", "third person for the fight"); time.sleep(10.0); F.view_to("third", "third (again)")
t_end = time.time() + float(os.environ.get("FIGHT_SECS", "180")); taps = 0
while time.time() < t_end:
    s = D.wait_state()
    if s["driving"]: tap("Return", 0.3); time.sleep(2); continue
    if F.current_view() != "third": F.view_to("third", "back to third")
    c = [(math.hypot(p["x"] - s["x"], p["y"] - s["y"]), p) for p in M.peds()
         if p["car"] is None and p["type"] == "civ" and M.ped_alive(p) and abs(p["z"] - s["z"]) < 0.6]
    c = sorted([t for t in c if t[0] < 6.0], key=lambda t: t[0])
    if not c:
        far = F.BOX[1] - 1.5 if s["x"] < (F.BOX[0] + F.BOX[1]) / 2 else F.BOX[0] + 1.5
        F.step_to(far, F.PAV_Y, tol=0.5, secs=6); continue
    d, p = c[0]
    a = D.angle_to(s, p["x"], p["y"])
    if abs(a) > TOL:
        hold(F.turn_key(a), min(abs(a) / D.rate, 0.3)); time.sleep(0.15); continue
    tap("Control_L", 0.1); taps += 1
    time.sleep(0.45)
time.sleep(11.0)   # the counter line is written every 10 s
lines = [l for l in open(D.LOG, encoding="latin-1") if "aim: shots=" in l]
mark(f"FIGHT taps {taps}; the owner's counter: {lines[-1].split('] ', 1)[-1].strip() if lines else 'none'}")
fl = [l for l in open(D.LOG, encoding="latin-1") if "aim: fists swings=" in l]
if fl: mark("FIGHT swing tally: " + fl[-1].split("] ", 1)[-1].strip())
mark("end")
say("done")
