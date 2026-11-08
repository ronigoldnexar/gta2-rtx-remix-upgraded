#!/usr/bin/env python3
"""QA3 probe, Downtown: the three things earlier passes could not frame.
QA3_ITEMS picks, in order (default "amb"):
  amb      an ambulance with its beacons: the machine gun (COLLECT_02), bursts at the
           crowd on the carriageway until bodies lie there, then the vehicle list
           (GTA2DX9_LOG_VEHICLES=1) is watched for model 34; while it drives the player
           stands ahead of it on its line, when it stops at the bodies he steps to its
           side; frames every 0.25 s in third person, a few in first
  police   QA3_STARS (default 4) held with [devtools] force_wanted (QA3_ARMED, default 1 from 4
           stars: the machine gun first and a burst at them now and then), beside the
           nearest driven police vehicle (cop car 12, SWAT van 52, FBI car 13): the officers
           shoot at a wanted man at 4 stars and up; frames every 0.15 s facing the nearest
           of them, rewarp every 40 s while nobody comes (QA3_POLICE_SECS, default 150)
The video (FPS=15) is the evidence for a muzzle flash: /out/marks.txt holds the
recording's start (ffmpeg's start time inside the container), so a log line's
time maps to a video second. Run with GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_VEHICLES=1,
GTA2DX9_LOG_PED_FRAMES=1, GTA2_DIRECT_KEYS=1 and the INI_SED setting scene_key=F10."""
import math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")


def mark(what):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {what}\n")
    say("MARK", what)


def vehicles():
    last = None
    for line in Q.log_text(120000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]


def find(models, near=None):
    vs = [v for v in vehicles() if v[0] in models]
    if near: vs.sort(key=lambda v: (v[1] - near[0]) ** 2 + (v[2] - near[1]) ** 2)
    return vs


def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    mark(f"{key}={val}")


def amb():
    A.collect(166.5, 140.5, 2, "machine_gun")
    # on the south pavement of the carriageway (the railing is at y=148), where people walk:
    # bursts along the pavement east and west and across the road at the traffic
    px, py = (float(v) for v in os.environ.get("QA3_CARNAGE_AT", "164.5,148.7").split(","))
    T.warp(px, py, 2, why="pavement"); Q.set_view("third", settle=0.6)
    t0 = time.time(); n = 0
    while time.time() - t0 < float(os.environ.get("QA3_CARNAGE_SECS", "45")):
        tx, ty = [(px + 8, py), (px - 8, py), (px, py + 4)][n % 3]
        A.face(tx, ty, tries=3)
        A.fire(f"amb_fire_{n:02d}", secs=1.6, every=0.4); n += 1
        if A.mission()[2] == "none":
            A.collect(166.5, 140.5, 2, "machine_gun"); T.warp(px, py, 2, why="pavement"); Q.set_view("third", settle=0.4)
    mark("carnage done")
    t0 = time.time(); k = 0; last = None; still = 0
    while time.time() - t0 < float(os.environ.get("QA3_AMB_SECS", "240")) and k < 40:
        s = D.wait_state()
        rv = find((34,), near=(s["x"], s["y"]))
        if not rv: time.sleep(1.5); continue
        m, x, y, z, fx, fy, d = rv[0]
        moved = last is None or math.hypot(last[0] - x, last[1] - y) > 0.3
        still = 0 if moved else still + 1
        last = (x, y)
        dist = math.hypot(s["x"] - x, s["y"] - y)
        if still >= 1:      # stopped at the bodies: two blocks to its side
            wx, wy = x - fy * 2.2 + fx * 0.8, y + fx * 2.2 + fy * 0.8
        else:               # driving: on its line, ahead of it
            wx, wy = x + fx * 5.0 - fy * 1.4, y + fy * 5.0 + fx * 1.4
        if dist > 6.0 or (still == 1 and k > 0):
            mark(f"ambulance at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f} driven {d} still {still} dist {dist:.1f}: warp {wx:.1f},{wy:.1f}")
            if s["driving"]: T.leave_car()
            T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="ambulance")
        A.face(x, y, tries=2)
        view = "first" if k % 4 == 3 else "third"
        Q.set_view(view, settle=0.2)
        for i in range(6): shot(f"amb{k:02d}_{view[0]}_{i}"); time.sleep(0.25)
        k += 1
        if k % 5 == 0: A.save_log()
    Q.set_view("third", settle=0.2)


def police():
    stars = int(os.environ.get("QA3_STARS", "4"))
    armed = os.environ.get("QA3_ARMED", "1" if stars >= 4 else "0") == "1"   # bare hands get punched and busted, a gun gets shot at
    if armed: A.collect(166.5, 140.5, 2, "machine_gun")
    T.warp(164.5, 147.6, 2, why="street"); Q.set_view("third", settle=0.6)
    set_ini("force_wanted", stars); lw = 0
    time.sleep(6.0)
    t0 = time.time(); n = 0
    while time.time() - t0 < float(os.environ.get("QA3_POLICE_SECS", "150")):
        s = D.wait_state()
        cs = find((12, 52, 13), near=(s["x"], s["y"]))
        if cs and time.time() - lw > 40 and math.hypot(cs[0][1] - s["x"], cs[0][2] - s["y"]) > 8:
            m, x, y, z, fx, fy, d = cs[0]
            wx, wy = x + fx * 3.0 - fy * 0.8, y + fy * 3.0 + fx * 0.8
            mark(f"police m{m} at {x:.1f},{y:.1f} driven {d}: warp {wx:.1f},{wy:.1f}")
            T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="police"); lw = time.time()
            Q.set_view("first" if 30 <= n < 40 else "third", settle=0.3)   # the warp cuts to classic
        if cs: A.face(cs[0][1], cs[0][2], tries=2)
        if Q.current_view() == "classic": Q.set_view("third", settle=0.3)   # after a bust or a respawn
        if n == 30: Q.set_view("first", settle=0.3)
        if n == 40: Q.set_view("third", settle=0.3)
        if armed and cs and n % 3 == 0:
            if A.mission()[2] == "none": A.collect(166.5, 140.5, 2, "machine_gun"); lw = 0
            else: A.fire(f"pol{stars}_{n:03d}_fire", secs=0.6, every=0.3)
        for i in range(8): shot(f"pol{stars}_{n:03d}_{i}"); time.sleep(0.15)
        n += 1
        if n % 4 == 0:
            w = A.mission(); mark(f"police t={time.time() - t0:.0f} wanted {w[0]} health {w[1]}"); A.save_log()
    set_ini("force_wanted", -1)


try:
    st = subprocess.run(["ps", "-o", "lstart=", "-C", "ffmpeg"], capture_output=True, text=True).stdout.strip().splitlines()
    mark(f"ffmpeg started {st[0] if st else '?'}")
except Exception as e:
    mark(f"ffmpeg start unknown {e}")
s = Q.start("qa3_probe")
mark("level")
time.sleep(2.0)
for item in os.environ.get("QA3_ITEMS", "amb").split():
    mark(f"item {item}")
    {"amb": amb, "police": police}[item]()
A.finish()
