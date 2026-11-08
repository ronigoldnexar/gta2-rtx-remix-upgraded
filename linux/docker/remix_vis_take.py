#!/usr/bin/env python3
"""VISUALS-REMIX material take (keys_remix_vis.sh): the same spots and headings in
every run, so a run with the old material layer and one with the new (MODS_HD_SRC)
can be compared frame for frame. Downtown, clock paused; at each spot a first-person
look round (4 headings) and the chase view; by day (14:00), at golden hour and at
night ([devtools] set_hour_tenths). Every step is a line in /out/marks.txt; frames
are cut from game.mp4 with remix_frames.py dump.
Env: VIS_SPOTS ("x,y;x,y;..."), VIS_HOURS ("14,18.6,22"), SCENE_KEY (F11)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, hold, mark, view, warp

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t): t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else: t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

def hour(h):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(4.0); mark(f"hour {h:.1f}")

def round_look(tag):
    T.clear_of_cars() if Q.current_view() == "first" else None
    mark(f"{tag}_0"); time.sleep(1.3)
    for i in range(3):
        hold("Left", 0.55); time.sleep(1.5); mark(f"{tag}_{i + 1}")

spots = [tuple(float(c) for c in p.split(",")) for p in os.environ.get("VIS_SPOTS", "164.5,149.5;187.5,196.9").split(";") if p]
hours = [float(h) for h in os.environ.get("VIS_HOURS", "14,18.6,22").split(",")]
mark("script start"); s = D.wait_state(); say("start:", T.words(s)); time.sleep(2)
for hi, h in enumerate(hours):
    hour(h)
    view("first"); round_look(f"h{h:g}_spawn_first")
    view("third"); round_look(f"h{h:g}_spawn_third")
    for si, (x, y) in enumerate(spots if hi == 0 else spots[:1]):
        warp(x, y, None, why=f"spot {si}")
        view("first"); round_look(f"h{h:g}_s{si}_first")
        view("third"); round_look(f"h{h:g}_s{si}_third")
mark("take end")
