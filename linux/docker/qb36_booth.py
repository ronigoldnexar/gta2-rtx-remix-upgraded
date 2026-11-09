#!/usr/bin/env python3
"""QB-36 (booth scale): stand beside the Downtown spawn phone booth (map 158.5,137.5)
from two sides and take a frame in classic, third and first person each time.
Pattern from props_check.py (PROPS-2). Owner: QB-36-BOOTH."""
import math, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
import drive_lib as D
from tour_lib import mark, shot, view, warp

def approach(tx, ty, tol, tries=16):
    s = D.wait_state()
    for _ in range(tries):
        d = math.hypot(tx - s["x"], ty - s["y"])
        a = D.angle_to(s, tx, ty)
        if abs(a) > 0.25:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.35)
            if d > tol + 0.3:
                D.hold("Up", 0.15); time.sleep(0.4)
        elif d > tol:
            D.hold("Up", min(1.5, max(0.12, (d - tol) / 1.9))); time.sleep(0.5)
        else:
            break
        s = D.wait_state()
    return s

BX, BY = 158.5, 137.5

def face(tx, ty, tries=8):
    """turn in place toward (tx,ty)"""
    s = D.wait_state()
    for _ in range(tries):
        a = D.angle_to(s, tx, ty)
        if abs(a) < 0.15:
            break
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.35)
        s = D.wait_state()
    return s

T.Q.start("qb36_booth")
# (name, stand at, look at): beside the booth at the same depth (east, looking north),
# and facing it from about a block (south, looking at it)
for name, px, py, lx, ly in (("beside", 159.05, 137.5, 159.05, 132.0),
                             ("front", 158.5, 138.7, BX, BY)):
    s = warp(px, py, 2, why=f"booth {name}")
    try:
        s = face(lx, ly)
        mark(f"at {s['x']:.2f},{s['y']:.2f} dist {math.hypot(BX - s['x'], BY - s['y']):.2f} facing {s['fx']:.2f},{s['fy']:.2f} booth {name}")
    except Exception as e:
        mark(f"face failed {e}")
    time.sleep(0.8); shot(f"qb36_{name}_classic")
    view("third"); time.sleep(2.0); shot(f"qb36_{name}_third")
    view("first"); time.sleep(1.5); shot(f"qb36_{name}_first")
    view("classic")
T.finish("qb36_booth")
