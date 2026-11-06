#!/usr/bin/env python3
"""Arm the player: the pistol pickup obj1 (166.5,140.5) east of the spawn, else the
COLLECT_02 pickup obj2 (154.5,129.5). Detection: the HUD weapon icon under the
lives (top right), measured as saturated pixels in that strip, plus a fire test."""
import os, sys, time, subprocess
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

def hud_icon():
    """saturation of the HUD strip under the lives (top right): a weapon icon raises it"""
    p = shot("hud")
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", "crop=150:78:1130:62,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    sat = 0
    for i in range(0, len(out) - 2, 3):
        r, g, b = out[i], out[i + 1], out[i + 2]
        if max(r, g, b) - min(r, g, b) > 60: sat += 1
    return sat

s = Q.start("armtest")
base = hud_icon(); say("hud saturated pixels before:", base)
tap("F10", 0.3); time.sleep(2.0); s = D.wait_state(); say("after F10:", Q.words(s))
for tgt in [(166.5, 140.5), (166.5, 139.5), (166.2, 140.8)]:
    s = D.goto(tgt[0], tgt[1], tol=0.3, limit=15) or D.wait_state()
    say(f"goto {tgt}: at {s['x']:.2f},{s['y']:.2f}")
    v = hud_icon(); say("hud:", v)
    if v > base + 40: say("ARMED at", tgt); break
else:
    say("walking to obj2 (154.5,129.5)")
    s = D.goto(154.5, 129.5, tol=0.4, limit=60) or D.wait_state()
    say(f"at {s['x']:.2f},{s['y']:.2f}"); v = hud_icon(); say("hud:", v)
Q.set_view("third"); time.sleep(1); shot("armed_third")
hold("Control_L", 0.8); time.sleep(1); shot("fired_third")
say("done")
