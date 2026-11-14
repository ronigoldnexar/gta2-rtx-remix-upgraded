#!/usr/bin/env python3
"""DISTRICTS merge check (inside a game container; keys_districts_night*.sh): a level change with the facade kit
(the game starts in Industrial: SWAP_LEVEL=bil; PLAYER QUIT, Downtown restored over level 1, START PLAY, the load
verified in the log), then at night (the [weather] clock held at DK_NIGHT, dry, clear) in the DK_POINTS district:
the drive-camera poses and two storefront poses looking at each side of the street (the lit sign words), kit on and
off, then into a car and a short drive (DK_ROUTE legs). Frames /out/dk_*.png; MARK lines in keys.log."""
import json, os, sys, time
import districts_capture as C
D, Q, T = C.D, C.Q, C.T
from a3_lib import tap
G = "/tmp/wp/drive_c/Games/GTA2"
LOG = G + "/gta2dx9.log"
NIGHT = int(os.environ.get("DK_NIGHT", "2130"))


def loads(name="facade kit stream"):
    """lines naming the kit stream of a level (wil.kit2 for Downtown) so far: one per map the renderer builds"""
    try:
        return sum(1 for l in open(LOG, encoding="latin-1", errors="replace") if "facade kit stream" in l and name in l)
    except OSError:
        return 0


C.cam("off")
D.start()
D.wait_state(40)
# 1) the level change: Industrial -> Downtown
Q.set_view("third", settle=2.5)
# the game builds its first level twice at start (the second ~45 s in): wait until the count has held for 20 s
last, since = loads(), time.time()
while time.time() - since < 20:
    time.sleep(1.0)
    if loads() != last:
        last, since = loads(), time.time()
C.say("MARK industrial loaded", loads("bil.kit2"))
n0 = loads("wil.kit2")
for attempt in range(3):
    tap("Escape", 0.1); time.sleep(1.5); tap("Return", 0.1); time.sleep(4)
    tap("Down", 0.1); time.sleep(0.5); tap("Down", 0.1); time.sleep(0.5); tap("Return", 0.1)
    time.sleep(3)
    if attempt == 0:
        import subprocess
        d = G + "/data"
        subprocess.run(["bash", "-c", f"for e in gmp sty SCR; do cp /game/data/wil.$e {d}/wil.$e; done; rm -rf {d}/wil && cp -r /game/data/wil {d}/wil"])
    t1 = time.time()
    while time.time() - t1 < 75 and loads("wil.kit2") == n0:
        time.sleep(1.5)
        el = time.time() - t1
        if 12 < el < 40 and int(el) % 6 < 2:
            tap("Return", 0.15)
        if el > 40 and Q.current_view() == "classic":
            Q.set_view("third", settle=1.0)
    if loads("wil.kit2") > n0:
        break
C.say("MARK level change", "verified (wil.kit2)" if loads("wil.kit2") > n0 else "NOT VERIFIED", loads())
# 2) night
for k, v in (("rain_percent", 0), ("cloud_percent", 0), ("fog_percent", 0), ("wet_percent", 0), ("time_of_day", 1),
             ("hour_hhmm", NIGHT), ("clock_paused", 1), ("enabled", 1), ("cycle", 0)):
    C.ini_sec("weather", k, v)
time.sleep(4)
for p in C.POINTS:
    D.wait_state(40)
    T.warp(p["x"], p["y"], int(p["z"]), why=f"districts night {p['name']}")
    time.sleep(2.0)
    Q.set_view("third", settle=3.0)
    dx, dy = p["dir"]
    poses = list(p["poses"]) + [
        {"name": "shops_left", "eye": [2 * dx, 2 * dy, 1.0], "at": [6 * dx + 3 * dy, 6 * dy - 3 * dx, 0.85], "fov": 55},
        {"name": "shops_right", "eye": [2 * dx, 2 * dy, 1.0], "at": [6 * dx - 3 * dy, 6 * dy + 3 * dx, 0.85], "fov": 55}]
    for pose in poses:
        C.cam(C.pose_line(p, pose)); time.sleep(3.0)
        C.ab(f"{p['name']}_night_{pose['name']}")
    C.cam("off"); time.sleep(0.5)
# 3) a short night drive (frame times and faults under traffic, the kit streaming)
route = json.loads(os.environ.get("DK_ROUTE", "{}"))
wp = route.get("waypoints", [])[:4]
if wp:
    import mission_lib as M
    world = M.World("wil")
    T.warp(wp[0][0], wp[0][1], 2, why="districts night drive")
    time.sleep(3)
    for attempt in range(20):
        s = D.wait_state()
        if s and s["driving"]:
            break
        tgt = (s["px"], s["py"]) if s and s.get("parked") and s.get("pd", 99) < 25 else ((s["cx"], s["cy"]) if s and s.get("car") and s.get("cd", 99) < 20 else None)
        if tgt:
            D.goto(tgt[0], tgt[1], tol=0.9, limit=16); tap("Return", 0.3); time.sleep(2.5)
        else:
            time.sleep(2.0)
    T.view("third")
    C.say("MARK night drive start")
    for i, (x, y) in enumerate(wp[1:]):
        T.drive(world, x, y, f"night leg {i}", budget=60, fp_after=10 ** 6)
        C.grab(f"night_drive_{i}")
    C.say("MARK night drive end")
C.say("districts night: done in", round(time.time() - C.T0), "s")
open("/out/.dk_done", "w").write("ok\n")
