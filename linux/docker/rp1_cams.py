#!/usr/bin/env python3
"""REMIX-PARITY-1 probe: frn9_cams.py's fixed cameras plus a frame-cost window per camera.
SPOTS = 'hour@x,y,lvl@view@cam|cam;...' (cam = 'ex ey ez tx ty tz fov' game coords, or 'classic').
Marks: S<i>_<tag>_c<j>_<k> (frames), bench_S<i>_c<j>_begin/end n=<frames.tsv line> (cost window, BENCH s).
Fixed cams via GTA2DX9_REGRESS_CAM=Z:\\tmp\\frn9_cam.txt; frame log via GTA2DX9_FRAME_LOG=Z:\\out\\frames.tsv."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import mark, view, warp
CAM = "/tmp/frn9_cam.txt"; open(CAM, "w").close()
FLOG = "/out/frames.tsv"
def flog_n():
    try:
        with open(FLOG, "rb") as f: return sum(1 for _ in f)
    except OSError: return -1
def ini_set(key, val):
    t = open(T.INI, "rb").read().decode("latin-1")
    if re.search(rf"(?m)^{key}=", t): t = re.sub(rf"(?m)^{key}=.*?(\r?)$", rf"{key}={val}\1", t)
    else: t = re.sub(r"(?m)^\[devtools\](\r?)$", rf"[devtools]\1\n{key}={val}\1", t, count=1)
    open(T.INI, "wb").write(t.encode("latin-1"))
WAIT = float(os.environ.get("CAM_WAIT", "6")); BENCH = float(os.environ.get("BENCH", "8"))
mark("script start"); time.sleep(float(os.environ.get("SHADER_WAIT", "20"))); mark("shaders settled")
cur_h = None
for i, spot in enumerate([s for s in os.environ["SPOTS"].split(";") if s.strip()]):
    h, at, vw, cams = spot.split("@")
    h = float(h)
    if h != cur_h: ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(5); cur_h = h; mark(f"hour {h:g}")
    x, y, lv = at.split(","); warp(float(x), float(y), int(lv), why=f"S{i}"); time.sleep(4)
    tag = f"S{i}_h{h:g}_{vw}"
    view(vw); time.sleep(8)
    for j, c in enumerate(cams.split("|")):
        c = c.strip()
        if c == "classic":
            open(CAM, "w").close(); view("classic"); time.sleep(8); mark(f"{tag}_classic_0"); time.sleep(1); mark(f"{tag}_classic_1"); view(vw); time.sleep(6)
        else:
            f = open(CAM, "w"); f.write("cam " + c + "\n"); f.close(); time.sleep(WAIT)
            for k in range(2): mark(f"{tag}_c{j}_{k}"); time.sleep(1.0)
            mark(f"bench_S{i}_c{j}_begin n={flog_n()}"); time.sleep(BENCH); mark(f"bench_S{i}_c{j}_end n={flog_n()}")
    open(CAM, "w").close()
T.finish("rp1 cams")
