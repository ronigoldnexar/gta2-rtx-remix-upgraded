#!/usr/bin/env python3
"""ANIM-COMBAT probe, Downtown (wil): fist fights in the third-person view.
COMBAT_MODE=cops (default): wanted level 2, the police punch him, he punches back.
COMBAT_MODE=walk: the player walks up to the nearest person and punches (the key held
for a combo), x11grab bursts at 15 fps around each attempt. Phase 2: wanted
level 3 (force_wanted), the police come and punch him; bursts while he stands.
Log: GTA2DX9_LOG_COMBAT=1 'cb:' lines and 'fig: hit' lines. Burst start times in
/out/combat_marks.txt (wall clock, the log's [hh:mm:ss])."""
import os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

OUT = "/out"
marks = open(f"{OUT}/combat_marks.txt", "a")
VIEW = os.environ.get("COMBAT_VIEW", "third")


def burst(label, secs, fps=15):
    marks.write(f"{label} {time.time():.3f} {fps}\n"); marks.flush()
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps), "-video_size", "1280x720",
                             "-i", ":99", "-t", str(secs), f"{OUT}/cb_{label}_%03d.png"])


def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK {key}={val}")


NEAR = re.compile(r"qb16: near ped d=([\d.]+) bearing=(-?[\d.]+)")


def nearest():
    m = None
    for m in NEAR.finditer(Q.log_text(8000)): pass
    return (float(m.group(1)), float(m.group(2))) if m else None


SIGN = [1.0]


def face_nearest(tries=5):
    for _ in range(tries):
        time.sleep(0.35)
        p = nearest()
        if not p: return None
        d, a = p
        if abs(a) < 0.15: return p
        key = "Right" if a * SIGN[0] > 0 else "Left"
        hold(key, max(0.04, min(0.5, abs(a) / 3.0))); time.sleep(0.35)
        q = nearest()
        if q and abs(q[1]) > abs(a) + 0.3 and abs(abs(q[0]) - d) < 0.3:
            SIGN[0] = -SIGN[0]; say("MARK turn sign flipped")
    return nearest()


HIT = re.compile(r"fig: contact (\w+) by (\w+) side (\d+)")


def contacts():
    return len(HIT.findall(Q.log_text(400000)))


s = Q.start("combat")
T.warp(164.5, 149.5, 2, why="plaza")
Q.set_view(VIEW, settle=0.5)
MODE = os.environ.get("COMBAT_MODE", "cops")
if MODE == "cops":
    # The police come to arrest him and punch him down (POLICE-3D: health 100 -> 90 ->
    # 50 -> 20, then the knock-down): a melee contact in the middle of the chase view.
    # Whoever stands within reach gets punched back with the key held (a cross, a jab,
    # then a kick if he stands). Counted bursts, not a wall-clock budget.
    set_ini("force_wanted", int(os.environ.get("COMBAT_WANTED", "2")))
    for n in range(int(os.environ.get("COMBAT_BURSTS", "30"))):
        if Q.current_view() != VIEW: Q.set_view(VIEW, settle=0.3)
        b = burst(f"cop_{n}", 6.0)
        p = nearest()
        if p and p[0] < 1.0:
            p = face_nearest(tries=1) or p
            say("MARK punch back", f"d={p[0]:.2f} bearing={p[1]:.2f}")
            D.xdo("keydown", "Control_L"); time.sleep(4.0); D.xdo("keyup", "Control_L")
        b.wait()
        if n % 3 == 2:
            A.save_log(); say("MARK contacts", contacts())
    set_ini("force_wanted", -1)
    A.finish()
    open(f"{OUT}/.keys_done", "w").close()
    sys.exit(0)

# Counted, not timed: the governor pauses containers and a loaded host runs the game
# slow, so wall-clock budgets ran out after one attempt (combat_m1).
r = 0; tries = 0
while r < int(os.environ.get("COMBAT_PUNCHES", "12")) and tries < 40:
    tries += 1
    if Q.current_view() != VIEW: Q.set_view(VIEW, settle=0.3)
    p = face_nearest()
    if not p or p[0] > 6.0:
        hold("Up", 0.8); hold("Left", 0.3); continue
    say("MARK target", f"d={p[0]:.2f} bearing={p[1]:.2f}")
    b = burst(f"punch_{r}", 7.0)
    time.sleep(0.2)
    # Walk into him with the fist going (the game's punch reaches about an arm), then
    # stand and keep swinging: the third swing standing is drawn as a kick.
    D.xdo("keydown", "Control_L")
    hold("Up", max(0.1, min(2.5, (p[0] - 0.25) / 0.8)))
    time.sleep(3.5)
    D.xdo("keyup", "Control_L")
    b.wait(); r += 1
    if r % 3 == 0: A.save_log()
A.finish()
open(f"{OUT}/.keys_done", "w").close()
