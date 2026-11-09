#!/usr/bin/env python3
"""QB-16 probe, Downtown (wil): hit reactions in a real gunfight. Pistol then
machine gun into the plaza crowd (third person), then wanted level 3 so the
police shoot the player. Frames: ffmpeg x11grab bursts at 10 fps, their start
times in /out/qb16_marks.txt (wall clock, the same as the log's [hh:mm:ss]).
Log: 'fig: shot' lines (GTA2DX9_LOG_PED_FRAMES=1)."""
import os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

OUT = "/out"
marks = open(f"{OUT}/qb16_marks.txt", "a")


def burst(label, secs, fps=10):
    marks.write(f"{label} {time.time():.3f} {fps}\n"); marks.flush()
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps), "-video_size", "1280x720",
                             "-i", ":99", "-t", str(secs), f"{OUT}/qb_{label}_%03d.png"])


def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK {key}={val}")


def pick(want):
    for _ in range(6):
        if A.weapon_name() == want: return True
        tap("z", 0.2); time.sleep(0.8)
    return A.weapon_name() == want


NEAR = re.compile(r"qb16: near ped d=([\d.]+) bearing=(-?[\d.]+)")


def nearest():
    m = None
    for m in NEAR.finditer(Q.log_text(8000)): pass
    return (float(m.group(1)), float(m.group(2))) if m else None


SIGN = [1.0]   # +bearing (his right) is turned onto with "Right"; flipped if a turn makes it worse


def face_nearest(tries=5):
    for _ in range(tries):
        time.sleep(0.4)
        p = nearest()
        if not p: return None
        d, a = p
        if abs(a) < 0.12: return p
        key = "Right" if a * SIGN[0] > 0 else "Left"
        hold(key, max(0.04, min(0.5, abs(a) / 3.0))); time.sleep(0.4)
        q = nearest()
        if q and abs(q[1]) > abs(a) + 0.3 and abs(abs(q[0]) - d) < 0.3:
            SIGN[0] = -SIGN[0]; say("MARK turn sign flipped")
    return nearest()


s = Q.start("qb16_hits")
A.collect(227.5, 210.5, 2, "pistol")
A.collect(166.5, 140.5, 2, "machine_gun")
# Busy pavements (QB-6's aim probe): face the nearest person (the renderer's
# GTA2DX9_LOG_NEAR_PED line), fire a short burst, again; pistol on the first,
# machine gun on the second.
for (x, y, lvl, tag, want, secs, tap_secs) in ((164.5, 149.5, 2, "st2", "machine_gun", 100, 0.10),
                                              (150.5, 133.5, 3, "st1", "machine_gun", 80, 0.10)):
    T.warp(x, y, lvl, why=tag)
    say("MARK weapon", want, pick(want))
    VIEW = os.environ.get("QB16_VIEW", "first")   # first person: a man shot point blank fills the frame
    Q.set_view(VIEW, settle=0.5)
    t0 = time.time(); r = 0
    while time.time() - t0 < secs:
        if A.weapon_name() == "none":
            A.collect(166.5, 140.5, 2, "machine_gun"); T.warp(x, y, lvl, why=tag); Q.set_view(VIEW, settle=0.5)
        p = face_nearest()
        if Q.current_view() != VIEW: Q.set_view(VIEW, settle=0.3)
        if not p or p[0] > 7.0:
            hold("Up", 0.8); hold("Left", 0.3); continue
        if p[0] > 1.2 and abs(p[1]) < 0.5:   # close in: the machine gun's bullets leave a man standing up close
            hold("Up", min(1.2, (p[0] - 0.7) / 3.0)); p = face_nearest(tries=2) or p
        say("MARK target", f"d={p[0]:.2f} bearing={p[1]:.2f}")
        b = burst(f"{tag}_{want}_{r}", 4.0, fps=12)
        time.sleep(0.9)
        for _ in range(2):
            D.xdo("keydown", "Control_L"); time.sleep(tap_secs); D.xdo("keyup", "Control_L"); time.sleep(0.6)
        b.wait(); r += 1
    A.save_log()

# The police shoot back (QA3's police item): 4 stars, armed, beside the nearest
# driven police vehicle; the officers shoot at an armed wanted man from 4 stars.
VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")


def find(models, near):
    last = None
    for line in Q.log_text(120000).splitlines():
        if "] vehicles:" in line: last = line
    vs = [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]
    vs = [v for v in vs if v[0] in models]
    vs.sort(key=lambda v: (v[1] - near[0]) ** 2 + (v[2] - near[1]) ** 2)
    return vs


# 6 stars: the army; soldiers fire rifles at him. Stand armed, face the nearest
# figure now and then, frames throughout.
set_ini("force_wanted", 6)
t0 = time.time(); n = 0
while time.time() - t0 < float(os.environ.get("QB16_ARMY_SECS", "150")):
    if Q.current_view() == "classic": Q.set_view("third", settle=0.3)
    b = burst(f"army_{n}", 4.0)
    face_nearest(tries=2)
    b.wait(); n += 1
    if n % 3 == 0:
        w = A.mission(); say("MARK army", f"t={time.time() - t0:.0f} wanted {w[0]} health {w[1]}"); A.save_log()
set_ini("force_wanted", -1)
A.finish()
open(f"{OUT}/.keys_done", "w").close()
