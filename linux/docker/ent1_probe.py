#!/usr/bin/env python3
"""FIX-ENTRY-1 probe (ped-state-7-blocks-vehicle-entry). Run with GTA2DX9_LOG_ENTRY=1, GTA2DX9_STATE_EVERY=3,
GTA2_DIRECT_KEYS=1, GTA2DX9_SCENE_NO_CAR=1, INI_SED adding warp_key=F9, scene_key=F11, enter_key=F8.
 A  the operator's spot (172.94,125.74 Downtown), facing north as logged; Return taps 70-120 ms, then x5
 B  F9 to the nearest parked car's driver door; face ALONG the car (as the operator stood); Return x2 (refused)
 C  face the car's centre; Return (boards: the game's own path); Return (exits)
 D  face along the car again; enter_key F8 (boards whatever the facing); Return (exits)
 E  F9 + Return, unchanged (the owner demo's / feel probes' path)."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
from qa_lib import say

def mark(what): T.mark(what)
def snap(tag): Q.shot(tag)
def st(tag):
    s = D.wait_state()
    say("S", tag, Q.words(s) if s else None, f"face={s['fx']:.3f},{s['fy']:.3f} car d={s['cd']:.2f}{' driven' if s['driven'] else ''} "
        f"parked {s['px']:.2f},{s['py']:.2f} d={s['pd']:.2f} phead={s['phx']:.2f},{s['phy']:.2f} cmodel={s.get('cmodel')}" if s else "")
    return s

def face(tx, ty, tag, tol=0.12):
    """turn on the spot until the sprite heading (view line face=) points along (tx,ty)"""
    n = math.hypot(tx, ty) or 1.0; tx, ty = tx / n, ty / n
    for i in range(30):
        s = D.wait_state(); time.sleep(0.15); s = D.wait_state()
        if not s or s["driving"]: return s
        a = math.atan2(s["fx"] * ty - s["fy"] * tx, s["fx"] * tx + s["fy"] * ty)
        if abs(a) < tol:
            say(f"faced {tag}: face={s['fx']:.3f},{s['fy']:.3f} want {tx:.3f},{ty:.3f} err {a:.2f}"); return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, max(0.04, min(0.25, abs(a) / max(D.rate, 0.5) * 0.7))); time.sleep(0.35)
    s = D.wait_state(); say(f"face {tag}: gave up at face={s['fx']:.3f},{s['fy']:.3f}"); return s

def returns(tag, holds):
    for i, h in enumerate(holds):
        D.tap("Return", h); time.sleep(0.45)
    time.sleep(2.5)
    return st(f"after Return {tag}")

def wait_driving(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and s["driving"]: return s
        time.sleep(0.3)
    return D.wait_state()

def wait_foot(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and not s["driving"] and s["state"] == 7: return s
        time.sleep(0.3)
    return D.wait_state()

Q.start("ent1")
Q.set_view("third", settle=1.0)
# A: the operator's spot
s = T.warp(172.94, 125.74, why="operator spot")
Q.set_view("third", settle=1.0)
time.sleep(3.0)
s = face(0.0, -1.0, "north (the operator's face=0,-1)")
time.sleep(1.0); st("A before"); snap("A_before")
mark("A Return single 0.10"); s = returns("A single", [0.10]); snap("A_after1")
mark("A Return x5"); s = returns("A x5", [0.07, 0.09, 0.12, 0.10, 0.08]); snap("A_after5")
if s and s["driving"]:
    mark("A boarded (a jack: the car ahead was a passing driven one)"); time.sleep(1.0); D.tap("Return", 0.1); wait_foot(10)
# settle on foot before F9 (a jacked car's driver may knock him down)
wait_foot(15)
# B: beside a parked car, facing along it
D.tap("F9", 0.3); time.sleep(3.0)
Q.set_view("third", settle=1.0)
s = st("B at the door")
s = face(s["phx"], s["phy"], "along the parked car")
time.sleep(0.8); st("B before"); snap("B_before")
mark("B Return along the car x2"); s = returns("B along", [0.10, 0.10]); snap("B_after")
if s and s["driving"]:
    mark("B boarded (unexpected)"); D.tap("Return", 0.1); wait_foot(6)
# C: face the car, Return
s = st("C")
s = face(s["px"] - s["x"], s["py"] - s["y"], "the parked car's centre")
time.sleep(0.8); st("C before"); snap("C_before")
mark("C Return facing the car"); D.tap("Return", 0.10)
s = wait_driving(8); st("C after"); snap("C_seated"); time.sleep(1.5); snap("C_seated2")
if s and s["driving"]:
    mark("C Return to exit"); D.tap("Return", 0.10); s = wait_foot(8); time.sleep(1.0); st("C exited"); snap("C_exited")
# D: along the car again, enter_key
s = st("D")
s = face(s["phx"], s["phy"], "along the parked car (again)")
time.sleep(0.8); st("D before"); snap("D_before")
mark("D Return along the car (control)"); s = returns("D along", [0.10])
if not (s and s["driving"]):
    mark("D enter_key F8"); D.tap("b", 0.15)
    for i in range(6):
        time.sleep(0.5); snap(f"D_walk{i}")
    s = wait_driving(10); st("D after F8"); snap("D_seated"); time.sleep(1.5); snap("D_seated2")
    if s and s["driving"]:
        mark("D Return to exit"); D.tap("Return", 0.10); s = wait_foot(8); time.sleep(1.0); st("D exited"); snap("D_exited")
# E: the F9 + Return path
mark("E F9 + Return"); D.tap("F9", 0.3); time.sleep(3.0); st("E at door"); D.tap("Return", 0.3)
s = wait_driving(8); st("E after"); snap("E_after")
say("done")
