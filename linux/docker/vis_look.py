#!/usr/bin/env python3
"""VISUALS-PLAIN look check: the same frames with the plain renderer's modern passes on and off
([visuals] enabled, re-read live every 2 s), at three Downtown spots, in the chase and
first-person views on foot, at day / golden hour / night ([visuals] sun_elevation_tenths, a live
sun override); then the three quality tiers at the first spot. The game's traffic and people
move between the on and off frames; the buildings, the sun and the camera do not.
Shots in /out/t_*.png, marks in /out/marks.txt. Env: VIS_SPOTS (default 3)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, tap, mark, shot, view, warp
INI = T.INI

def setv(key, val):
    """set key=val inside [visuals] (added when missing)"""
    s = open(INI, encoding="latin-1").read()
    if "[visuals]" not in s: s += "\n[visuals]\n"
    head, sec = s.split("[visuals]", 1)
    nxt = re.search(r"(?m)^\[", sec)
    body, rest = (sec[:nxt.start()], sec[nxt.start():]) if nxt else (sec, "")
    if re.search(rf"(?m)^{key}=.*$", body): body = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", body)
    else: body = f"\n{key}={val}" + body
    open(INI, "w", encoding="latin-1").write(head + "[visuals]" + body + rest)
    mark(f"SET visuals {key}={val}")

TODS = [("day", 340, 2350), ("golden", 70, 2600), ("night", -150, 2350)]
T.Q.start("vis_look")
setv("sun_azimuth_tenths", 2350)
spots = [(164.5, 149.5), (122.5, 155.5), (124.5, 212.5)][:int(os.environ.get("VIS_SPOTS", "3"))]
for i, spot in enumerate(spots):
    warp(*spot, None, why=f"look spot {i}")
    for v in ("third", "first"):
        view(v); time.sleep(2.0)
        if v == "first": T.clear_of_cars()
        for name, el, az in TODS:
            setv("sun_elevation_tenths", el); setv("sun_azimuth_tenths", az)
            setv("enabled", 1); time.sleep(2.6); shot(f"s{i}_{v}_{name}_on")
            setv("enabled", 0); time.sleep(2.6); shot(f"s{i}_{v}_{name}_off")
            setv("enabled", 1)
warp(*spots[0], None, why="quality tiers")
view("third"); time.sleep(2.0)
for name, el, az in TODS[:1] + TODS[2:]:
    setv("sun_elevation_tenths", el); setv("sun_azimuth_tenths", az)
    for qn in ("low", "medium", "high"):
        setv("quality", qn); time.sleep(2.6); shot(f"tier_{name}_{qn}")
setv("quality", "medium"); setv("sun_elevation_tenths", -9999)
view("classic"); time.sleep(1.0); shot("classic_after")
open("/out/.keys_done", "w").close()
