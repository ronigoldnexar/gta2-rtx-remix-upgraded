#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-4 (tracked copy: linux/docker/paint_parity_probe.py, run by keys_paint_parity.sh): the paint apply across hues. The player's stopped car, forced to each model in MODELS, painted
(force_car_paint = a sprite's mean paint, brighter-half) in each of PAINTS, shot from the top pose (the classic
camera) under each devtools mode in MODES. Frames /out/pt_<model>_<paint>_<mode>.png; marks in keys.log."""
import os, re, subprocess, sys, time, math
sys.path.insert(0, "/work")
import feel_probe as F
from a3_lib import Q, T, D, say
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
CAM = os.environ.get("VA2_CAM", "/tmp/va2_cam.txt")
def setkey(k, v):
    # FIX-CAR-IDENTITY-7: "section.key" sets the key in that section's FIRST block (e.g. visuals.shadows); a bare key is [devtools]
    sec, k = k.split(".", 1) if "." in k else ("devtools", k)
    s = open(INI, encoding="latin-1", newline="").read()
    a = s.find(f"[{sec}]")
    if a < 0: s += f"\r\n[{sec}]\r\n{k}={v}\r\n"
    else:
        b = s.find("\n[", a + 1); b = len(s) if b < 0 else b
        blk = s[a:b]
        if re.search(rf"(?m)^{k}=", blk): blk = re.sub(rf"(?m)^{k}=[^\r\n]*", f"{k}={v}", blk, count=1)
        else: blk = blk.replace(f"[{sec}]", f"[{sec}]\r\n{k}={v}", 1)
        s = s[:a] + blk + s[b:]
    open(INI, "w", encoding="latin-1", newline="").write(s)
def getkey(k, default=""):
    sec, k = k.split(".", 1) if "." in k else ("devtools", k)
    s = open(INI, encoding="latin-1", newline="").read()
    a = s.find(f"[{sec}]")
    if a < 0: return default
    b = s.find("\n[", a + 1); b = len(s) if b < 0 else b
    m = re.search(rf"(?m)^{k}=([^\r\n]*)", s[a:b])
    return m.group(1).strip() if m else default
def cam(line):
    with open(CAM + ".tmp", "w") as f: f.write(line + "\n")
    os.replace(CAM + ".tmp", CAM)
def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/{name}.png"]); F.mark(f"shot {name}")
PAINTS = [("red", "133,65,65,189,109,108"), ("navy", "35,45,95,55,65,130"), ("black", "28,28,30,42,42,45"),
          ("yellow", "200,180,50,230,215,90"), ("green", "60,120,60,90,160,90"), ("white", "215,215,215,240,240,240"),
          ("teal", "60,93,102,90,130,140"),
          # FIX-CAR-IDENTITY-5: the G4 bank van's sprite paints by the remap rule (assets-src/cars/sprites 004 default / remap36)
          ("van36", "70,99,85,100,130,115"), ("vanblue", "59,82,115,90,110,140")]
MODES = [("old", {"paint_ref": 0, "paint_gain_percent": 100, "paint_spec_power": 26}),
         ("new", {"paint_ref": 1, "paint_gain_percent": 125, "paint_spec_power": 50})]
if os.environ.get("MODES"):
    MODES = [(x.split(":")[0], dict(kv.split("=") for kv in x.split(":")[1].split(";"))) for x in os.environ["MODES"].split("|") if x]
ALL_PAINTS = dict(PAINTS)
if os.environ.get("PAINTS"):
    PAINTS = [p for p in PAINTS if p[0] in os.environ["PAINTS"].split(",")]
# FIX-CAR-IDENTITY-5: liveries and wrecks keep their own colours (a forced paint changes nothing on them): ONE_PAINT_MODELS
# get only the first paint; EXTRA_PAINTS="4:van36,vanblue;..." adds a model's own sprite paints.
ONE = {int(x) for x in os.environ.get("ONE_PAINT_MODELS", "").split(",") if x.strip()}
EXTRA = {int(k): v.split(",") for k, v in (x.split(":") for x in os.environ.get("EXTRA_PAINTS", "").split(";") if ":" in x)}
POSES = {"top": (-0.08, 0.0, 5.0), "top3": (-0.6, 0.3, 3.0), "chase": (-1.7, 0.0, 0.75), "low": (-1.1, 0.25, 0.02), "under": (-0.7, 0.0, -0.05)}
# FIX-CAR-IDENTITY-7: the gate's car is the parked car nearest 150.5,160.5 (an open plaza, in sun at the gate's fixed sun:
# lit lids 1.00 of shadows-off, out/fci7sc1 spot 4); the old 164.5,147.6 car (the park's chessboard) has stood in a park
# tree's shadow since 9b9e646 (0.66).
T.warp(float(os.environ.get("WX", "150.5")), float(os.environ.get("WY", "160.5")), 2, why="street"); F.into_car(); F.mark(f"driving {F.driving()}")
Q.set_view("third", settle=1.0); time.sleep(4.0)
# BACK_SECS: the reverse after the nudge forward (FIX-CAR-IDENTITY-7: a knob to step the car out of a shadow at WX,WY).
F.down("Up"); time.sleep(0.6); F.up("Up"); F.down("Down"); time.sleep(float(os.environ.get("BACK_SECS", "0.4"))); F.up("Down"); time.sleep(2.5)
# FIX-CAR-IDENTITY-7: SHADE_CHECK=1 (default) shoots each model's first paint once more with the sun shadows off
# ([visuals] shadows=0, mode label "noshade"): tools/paint_parity.py compares its lit lids with the measured frame and
# fails the gate SETUP when the car stands in a world shadow (a tree, a wall, a parked truck), not the paint.
SHADE = os.environ.get("SHADE_CHECK", "1") == "1"
for m in [x for x in os.environ.get("MODELS", "13,18,40").split(",") if x]:
    setkey("force_car_model", m); time.sleep(3.0)
    s = D.wait_state(10)
    x, y, z = s["x"], s["y"], s["z"]
    fx, fy = (s["chx"], s["chy"]) if abs(s.get("chx", 0)) + abs(s.get("chy", 0)) > 0.1 else (s["fx"], s["fy"])
    n = math.hypot(fx, fy) or 1.0; fx, fy = fx / n, fy / n
    rx, ry = -fy, fx
    say("model", m, "at", x, y, z, "head", fx, fy)
    for pose in os.environ.get("POSES", "top").split(","):
        f, r, u = POSES[pose]
        cam(f"cam {x + fx * f + rx * r:.3f} {y + fy * f + ry * r:.3f} {z + u:.3f} {x:.3f} {y:.3f} {z + (0.18 if pose in ("low", "under") else 0.10):.3f} 50")
        time.sleep(0.8)
        mp = PAINTS[:1] if int(m) in ONE else PAINTS + [(e, ALL_PAINTS[e]) for e in EXTRA.get(int(m), []) if e in ALL_PAINTS and e not in dict(PAINTS)]
        for pl, pv in mp:
            setkey("force_car_paint", pv)
            time.sleep(4.0)   # devtools re-read (60 frames) + the record's paint hold (45 frames)
            for ml, kv in MODES:
                for k, v in kv.items(): setkey(k, v)
                time.sleep(float(os.environ.get("SETTLE", "2.5")))
                shot(f"pt_{pose}_{int(m):03d}_{pl}_{ml}")
        if SHADE and pose == "top" and mp:
            pl, pv = mp[0]
            setkey("force_car_paint", pv)
            for k, v in MODES[0][1].items(): setkey(k, v)
            sh0 = getkey("visuals.shadows", "1")
            setkey("visuals.shadows", 0); time.sleep(4.0)   # [visuals] is re-read every 2 s
            shot(f"pt_{pose}_{int(m):03d}_{pl}_noshade")
            setkey("visuals.shadows", sh0); time.sleep(3.0)
    cam(""); time.sleep(0.5)
setkey("force_car_model", -1)
F.mark("done")
