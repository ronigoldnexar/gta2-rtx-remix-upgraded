#!/usr/bin/env python3
"""QB-25 facade-depth take (keys_remix_facade.sh): the same pose with Remix's parallax
displacement scaled 0 / 1 / 2 (rtx.displacement.displacementFactor, pushed live through
[devtools] remix_config), at street spots that look along walls of window tiles. Factor 0
is the facade without depth, 1 the shipped scale, 2 an exaggeration that proves the height
maps are read. Run with the facade layer as MODS_HD_SRC. Marks: f<hour>_<spot>_<view>_d<factor>.
Env: FAC_SPOTS ("x,y,fx,fy;..."), FAC_HOURS ("14,17.5"), FAC_FACTORS ("1,0,2,1"), FAC_SETTLE (4 s)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
import a3_lib as A
from tour_lib import D, Q, say, mark, view, warp
E = os.environ.get
SETTLE = float(E("FAC_SETTLE", "4"))
FACTORS = [float(f) if "." in f else int(f) for f in E("FAC_FACTORS", "1,0,2,1").split(",")]

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t): t = re.sub(rf"(?m)^{key}=.*$", lambda m: f"{key}={val}", t)
    else: t = re.sub(r"(?m)^\[devtools\]\s*$", lambda m: f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

N = [0]
def disp(f):
    N[0] += 1
    ini_set("remix_config", f"rtx.displacement.displacementFactor={f}" + ("|" * (N[0] % 2)))
    time.sleep(SETTLE)

spots = [tuple(float(c) for c in p.split(",")) for p in
         E("FAC_SPOTS", "164.5,202.2,172.5,203.1;228.5,137.2,236.5,138.1;239.8,191.5,238.9,199.5").split(";") if p]
hours = [float(h) for h in E("FAC_HOURS", "14,17.5").split(",")]
mark("script start"); s = D.wait_state(timeout=120); say("start:", T.words(s) if s else "no state")
Q.set_view("classic", settle=1.0); D.calibrate_turn()
for hi, h in enumerate(hours):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(4.0); mark(f"hour {h:g}")
    for si, (x, y, fx, fy) in enumerate(spots if hi == 0 else spots[:1]):
        warp(x, y, 2, why=f"facade spot {si}")
        Q.set_view("classic", settle=0.8); A.face(fx, fy)
        for v in ("first", "third"):
            view(v); time.sleep(2.0)
            for f in FACTORS:
                disp(f); mark(f"f{h:g}_s{si}_{v}_d{f}")
mark("take end")
