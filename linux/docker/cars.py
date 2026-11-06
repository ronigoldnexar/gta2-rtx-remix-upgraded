#!/usr/bin/env python3
"""The car check. F10 (the mod's devtools scene key, see [devtools] in
gta2dx9.ini) brings the nearest parked car to the Downtown carriageway with
the player at its door; from there, in third person and in first person, he
faces the car, then up and down the road (traffic passes), with a screenshot
each time the game reports a car in reach; then the classic view of the same
spot. Screenshots are named by view."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D

say = D.say
def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/view_{name}.png"])
D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
for _ in range(40):
    s = D.wait_state()
    if s["parked"]: break
    D.hold("Up", 0.6); time.sleep(0.4)
say(f"start {s['x']:.1f},{s['y']:.1f} parked d={s['pd']:.1f}")
for attempt in range(3):
    D.tap("F10", 0.3); time.sleep(1.5)
    s = D.wait_state()
    say(f"after F10: at {s['x']:.1f},{s['y']:.1f} parked {s['px']:.1f},{s['py']:.1f} d={s['pd']:.1f}")
    if 0.3 < s["pd"] < 3.0: break
kx, ky = s["x"], s["y"]
def face(tx, ty, tol=0.25):
    for _ in range(8):
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < tol: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, min(abs(a) / D.rate, 0.5)); time.sleep(0.5)
    return D.wait_state()
def look_round(prefix, seconds=40):
    t0 = time.time(); n = 0
    while time.time() - t0 < seconds:
        s = D.wait_state()
        best = None
        for kind in ("p", "c"):
            d = s[kind + "d"]
            if 0.3 < d < 9.0 and (best is None or d < best[0]): best = (d, s[kind + "x"], s[kind + "y"], kind)
        if best:
            face(best[1], best[2], tol=0.2); time.sleep(0.6)
            shot(f"{prefix}_car{n:02d}"); say(f"{prefix}: car {best[3]} at d={best[0]:.1f}"); n += 1
            time.sleep(1.5)
        else:
            tgt = [(kx + 8, ky), (kx - 8, ky), (kx, ky + 3)][n % 3]
            face(*tgt, tol=0.25); time.sleep(0.8)
            shot(f"{prefix}_look{n:02d}"); n += 1
            time.sleep(1.5)
say("third person"); D.tap("v"); time.sleep(2.5)
look_round("1_third")
say("first person"); D.tap("v"); time.sleep(2.5)
look_round("2_first")
say("classic"); D.tap("v"); time.sleep(2.5)
for k in range(6):
    shot(f"3_classic_{k}"); time.sleep(3)
say("done")
