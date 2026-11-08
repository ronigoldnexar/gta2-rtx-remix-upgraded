#!/usr/bin/env python3
"""ACTIONS-3D probes: shared helpers over qa_lib/tour_lib. The mission line's
weapon and wanted fields, a fire burst with frames, the side view trick (the
chase camera holds its yaw for a moment while the player turns, so a quick turn
shows the figure from the side), and a log copy at the end."""
import os, re, shutil, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
import tour_lib as T
import drive_lib as D
from qa_lib import say, tap, hold, shot

WEAPON = re.compile(r"view: mission .*wanted=(-?\d+) health=(-?\d+).* weapon=(\w+)\((-?\d+)\) ammo=(-?\d+)")


def mission():
    """(wanted, health, weapon name, weapon number, ammo) from the newest mission line."""
    m = None
    for m in WEAPON.finditer(Q.log_text(30000)): pass
    if not m: return (-1, -1, "?", -1, 0)
    return int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)), int(m.group(5))


def weapon_name():
    return mission()[2]


def fire(label, secs=0.6, every=0.2, turn=None):
    """Hold the fire key for secs, a frame every `every`; turn=('Left', 0.25) turns mid-burst."""
    D.xdo("keydown", "Control_L")
    t0 = time.time(); n = 0
    while time.time() - t0 < secs:
        time.sleep(every)
        if turn and n == 1:
            D.xdo("keydown", turn[0]); time.sleep(turn[1]); D.xdo("keyup", turn[0])
        shot(f"{label}_{n:02d}"); n += 1
    D.xdo("keyup", "Control_L")


def side(label, key="Left", secs=0.28):
    """A quick turn, then a frame while the chase camera still looks along the old line."""
    hold(key, secs); shot(label)


def walk_frame(label, secs=0.7, key="Up"):
    D.xdo("keydown", key); time.sleep(secs); shot(label); D.xdo("keyup", key)


def collect(x, y, lvl, name):
    s = T.warp(x, y, lvl, why=name)
    hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
    s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
    time.sleep(0.6)
    say("MARK collected", name, "weapon now", weapon_name())
    return s


def save_log():
    try:
        shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
    except OSError:
        pass


def face(tx, ty, tries=8):
    """Turn on the spot (tank controls, nav_map=0) until he faces (tx, ty)."""
    import math
    for _ in range(tries):
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < 0.25: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.35)
    return D.wait_state()


def finish():
    say("CHECK", Q.counts())
    try:
        shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
    except OSError as e:
        say("log copy failed", e)
    say("done")
