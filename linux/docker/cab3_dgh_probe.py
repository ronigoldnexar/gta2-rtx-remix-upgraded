#!/usr/bin/env python3
"""FIX-DRIVER-GEOM pmab1/pfl71: first-person hands on the rim. Per spot (one car class each): get in, first person,
stopped: [devtools] force_steer_deg swept (0, +-4, +-8, +-12, +-17: the rim at 0..~100 deg), a frame each
(/out/dgh_<model>_s<deg>.png); then (CRASH=1) a 30 fps clip: a turn, two drives into the wall ahead with the turn held,
reverse (/out/b_dgh_crash_<model>.mp4)."""
import os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
import feel17_probe as X
import a3_lib as A3
CAMB = re.compile(r"cam\[(\d+)\] bounds=([-\d.]+),([-\d.]+)\.\.([-\d.]+),([-\d.]+)")
def settle_game_cam(timeout=45):
    t0 = time.time(); ok = 0; last = None
    while time.time() - t0 < timeout:
        m = CAMB.findall(A3.Q.log_text(300000)); st = A3.D.state()
        if m and st and m[-1][0] != last:
            last = m[-1][0]; x0, y0, x1, y1 = map(float, m[-1][1:])
            inside = x0 - 0.5 <= st["x"] <= x1 + 0.5 and y0 - 0.5 <= st["y"] <= y1 + 0.5
            ok = ok + 1 if inside else 0
            if ok >= 2: mark(f"SETTLED {time.time() - t0:.1f}s {m[-1][1:]}"); return True
        time.sleep(0.5)
    mark("NOT_SETTLED"); return False
vto = X.vto
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def setkey(k, v):
    s = open(INI, "rb").read().decode("latin-1")
    if re.search(rf"(?m)^{k}=", s): s = re.sub(rf"(?m)^{k}=[^\r\n]*", f"{k}={v}", s)
    else: s = s.replace("[devtools]", f"[devtools]\r\n{k}={v}", 1)
    open(INI, "wb").write(s.encode("latin-1"))
def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/{name}.png"]); mark(f"shot {name}")
def model():
    try:
        t = open("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", errors="ignore").read()[-400000:]
        m = re.findall(r"view: player .*?carmodel=(\d+)", t)
        return int(m[-1]) if m else None
    except Exception: return None
SPOTS = [tuple(map(float, s.split(":"))) for s in os.environ.get("SPOTS", "97.5:68.5,198.5:178.5,19.5:35.5").split(",")]
SWEEP = [int(v) for v in os.environ.get("SWEEP", "0,4,8,12,17,-4,-8,-12,-17,0").split(",")]
for (wx, wy) in SPOTS:
    try:
        if os.environ.get("NOWARP") != "1": T.warp(wx, wy, 2, why="spot"); time.sleep(2)
        ok = into_car(); time.sleep(1.0); m = model()
        mark(f"spot {wx},{wy} in={ok} model={m}")
        if not ok: continue
        if os.environ.get("SETTLE", "1") == "1": settle_game_cam()
        vto("first", 3.0)
        for d in SWEEP:
            setkey("force_steer_deg", d); mark(f"steer {d}"); time.sleep(1.6)
            shot(f"dgh_{m:03d}_s{d}" if m is not None else f"dgh_x_s{d}")
            time.sleep(1.4); shot(f"dgh_{m:03d}_s{d}b" if m is not None else f"dgh_x_s{d}b")
        setkey("force_steer_deg", 0); time.sleep(1.0)
        if os.environ.get("CRASH", "1") == "1":
            p = burst(f"dgh_crash_{m}", 16.0); time.sleep(0.3)
            down("Up"); time.sleep(1.2); down("Left"); time.sleep(0.6); up("Left"); time.sleep(2.5); up("Up")
            down("Down"); time.sleep(0.9); up("Down"); time.sleep(0.3)
            down("Right"); down("Up"); time.sleep(2.5); up("Right"); time.sleep(1.0); up("Up")
            down("Down"); time.sleep(1.2); up("Down"); time.sleep(2.0)
            p.wait()
        tap("Return", 0.3); time.sleep(3)
    except Exception as e: mark(f"spot {wx},{wy} failed {e!r}")
setkey("force_steer_deg", 0)
mark("done")
