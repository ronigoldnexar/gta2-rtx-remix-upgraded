#!/usr/bin/env python3
"""FIX-FX-4: a deterministic car blast for QA, filmed in a street view, the player alive.
F10 seats him in the scene car, he gets out and faces along the street, the view goes to VIEW (third|first), and [devtools] force_blast=1 (force_blast_car=own)
blows up the car nearest the point DIST blocks ahead along the view (normally that car) through the game's own damage routine. Shots every ~0.1 s through the blast
(qa_d_blast_*), then the burning wreck (qa_e_after_*). BURN=1 writes force_burn instead (alight only).
Env: VIEW (third), DIST (4.0 blocks), N (40 burst shots), BURN (0), MODE (own|near)."""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
import drive_lib as D
from qa_lib import say, tap, hold, shot
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
VIEW = os.environ.get("VIEW", "third"); DIST = float(os.environ.get("DIST", "4.0"))
N = int(os.environ.get("N", "40")); BURN = os.environ.get("BURN", "0") == "1"; MODE = os.environ.get("MODE", "near")

def setdev(key, val):
    # newline='' keeps the ini's CRLF (a text-mode rewrite to LF breaks the scripted keys)
    t = open(INI, encoding="latin-1", newline="").read()
    if re.search(rf"(?m)^{key}=", t): t = re.sub(rf"(?m)^{key}=[^\r\n]*", f"{key}={val}", t)
    else: t = re.sub(r"(?m)^\[devtools\]\r?\n", lambda m: m.group(0) + f"{key}={val}\r\n", t, count=1)
    open(INI, "w", encoding="latin-1", newline="").write(t)

def lives():
    m = re.findall(r"view: mission money=\S+ mult=\S+ lives=(\d+)", Q.log_text(400000))
    return int(m[-1]) if m else -1

Q.start("fx4_blast")
setdev("force_blast_car", MODE); setdev("force_blast_dist", int(DIST * 10))
s = Q.get_in_car()
if not s: say("RESULT no car"); sys.exit(1)
cx, cy = s["x"], s["y"]; fx, fy = s["fx"], s["fy"]
say(f"car at {cx:.2f},{cy:.2f} facing {fx:.2f},{fy:.2f}")
s = Q.leave_car(); time.sleep(1.5)
# face along the street, the way the car's tail points (the lane he came in by): the blast picks the car
# nearest the point DIST blocks ahead along the view, within 40 degrees of it ([devtools] force_blast_car=near)
n = math.hypot(fx, fy) or 1.0
tx, ty = cx - fx / n * 12.0, cy - fy / n * 12.0
for i in range(8):
    s = D.wait_state(); a = D.angle_to(s, tx, ty)
    if abs(a) < 0.15: break
    key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
    hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.45)
time.sleep(0.6); s = D.wait_state()
say(f"facing along the street: angle {D.angle_to(s, tx, ty):+.2f} rad, {Q.words(s)}")
Q.set_view(VIEW, settle=3.0)
l0 = lives(); b0 = Q.log_text().count("explosions: blast at")
setdev("set_player_health", 100); time.sleep(0.8)   # full health: the splash at 2.5 blocks takes about a third
shot("a_before")
setdev("force_burn" if BURN else "force_blast", 1)
t0 = time.time()
for i in range(N):
    shot(f"d_blast_{int((time.time()-t0)*10):03d}"); time.sleep(0.05)
for i in range(int(os.environ.get("NAFTER", "12"))):
    shot(f"e_after_{i:02d}"); time.sleep(0.5)
t = Q.log_text()
trig = re.findall(r"devtools: force_(?:blast|burn) \d+:[^\n]*", t)
say("TRIGGER", trig[-1] if trig else "none")
after = re.findall(r"devtools: force_blast/force_burn: 2 s on, player health -?\d+", t)
say("AFTER", after[-1] if after else "none")
say(f"RESULT blasts {b0}->{t.count('explosions: blast at')} blewup={len(re.findall('blew up', t))} lives {l0}->{lives()} view={Q.current_view()}")
Q.report("fx4_blast")
