#!/usr/bin/env python3
"""The demonstration: opening, menu, area 1 in the classic view, a walk to the
street by the map, then the live switch to third person and to first person,
walking along the pavement with the traffic beside."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import gmp

say = D.say
D.start()                                   # window, focus, intro, menu, level
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
level = int(s["z"]) - 1
blocks, columns = gmp.load("/tmp/wp/drive_c/Games/GTA2/data/wil.gmp")
say("classic view: walking to the street")
s = D.wait_state()
def plan(s):
    """a route to the road from the player's cell, or from the nearest walkable cell to it, or the known one"""
    sx, sy = int(s["x"]), int(s["y"])
    r = gmp.route(blocks, columns, sx, sy, level)
    if r: return r
    best = None
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if gmp.ground(blocks, columns, sx + dx, sy + dy, level) in (1, 2, 3):
                r = gmp.route(blocks, columns, sx + dx, sy + dy, level)
                if r and (best is None or len(r) < len(best)): best = r
    if best: return [(sx, sy)] + best
    say("no route from the map; using the known start-to-road route")
    return [(159, 139), (158, 139), (157, 139), (157, 140), (156, 140), (156, 141), (156, 142), (156, 143),
            (156, 144), (156, 145), (156, 146), (156, 147), (156, 148), (156, 149)]
sx, sy = int(s["x"]), int(s["y"])
path = gmp.route_to(blocks, columns, sx, sy, 156, 147, level) or plan(s)
say("route:", path)
for cx, cy in D.straighten(path)[1:]:
    s = D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=20)
# Back one cell onto the pavement beside the road, then along it.
here = (156, 147)   # pavement corner at the traffic road (y=148..150), run along x
s = D.goto(here[0] + 0.5, here[1] + 0.5, tol=0.4, limit=10)
# The pavement beside the Downtown carriageway (y=148..150), verified walkable
# from x=156 to x=168 at y=147 (the driving runs): walk it east, then back.
KERB = 0.32   # toward the road so the building wall is not at the camera's nose
end_a = (156.6, 147.5 + KERB)
end_b = (167.4, 147.5 + KERB)

def walking_switch(what):
    """V while already walking, and keep walking through the 1.4 s move, so the
    camera's travel is seen over a moving player rather than a standing one"""
    D.xdo("keydown", "Up"); time.sleep(0.4)
    D.tap("v"); say(f"V: {what}")
    time.sleep(1.8)
    D.xdo("keyup", "Up")

# Classic view: face along the pavement and take a couple of steps.
s = D.goto(end_a[0], end_a[1], tol=0.3, limit=12)
s = D.goto(end_a[0] + 1.5, end_a[1], tol=0.3, limit=6)
D.hold("Up", 1.5); time.sleep(1.0)
def mark(what):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {what}\n")
# Straight to first person: V twice while walking (classic -> third -> first, blended).
mark("to_first")
D.xdo("keydown", "Up"); time.sleep(0.4)
D.tap("v"); time.sleep(0.5); D.tap("v"); say("V V: first person")
time.sleep(2.0); D.xdo("keyup", "Up")
t0 = time.time()
# First person: along the run to its far end and back, 22+ s; goto turns him the short way.
s = D.goto(end_b[0], end_b[1], tol=0.35, limit=14)
D.hold("Left", 0.5); time.sleep(0.6); D.hold("Right", 0.5)
s = D.goto(end_a[0], end_a[1], tol=0.35, limit=14)
while time.time() - t0 < 22:
    s = D.goto(end_a[0] + (end_b[0] - end_a[0]) * 0.3, end_a[1] + (end_b[1] - end_a[1]) * 0.3, tol=0.35, limit=8)
    s = D.goto(end_a[0], end_a[1], tol=0.35, limit=8)
mark("to_classic")
D.xdo("keydown", "Up"); time.sleep(0.4); D.tap("v"); say("V: classic"); time.sleep(1.8); D.xdo("keyup", "Up")
s = D.goto(end_b[0], end_b[1], tol=0.35, limit=12)
mark("end")
say("done")
