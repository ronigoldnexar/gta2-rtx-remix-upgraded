#!/usr/bin/env python3
"""Plays GTA2 from the renderer's log: reads the player's position, facing and
the nearest car (the 'view: player' line the mod logs twice a second), walks to
the car, gets in, drives, and cycles the views on the way. Keys go through
xdotool to the focused game window."""
import math, os, re, subprocess, sys, time

LOG = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.log"
OUT = "/out"
LINE = re.compile(r"view: player x=([-\d.]+) y=([-\d.]+) z=([-\d.]+) face=([-\d.]+),([-\d.]+) (on foot|driving) \| car (nearest|none) x=([-\d.]+) y=([-\d.]+) d=([-\d.]+)( \(driven\))? \| parked (nearest|none) x=([-\d.]+) y=([-\d.]+) d=([-\d.]+)")

def xdo(*args): subprocess.run(["xdotool", *args], check=False)
def tap(key, t=0.25): xdo("keydown", key); time.sleep(t); xdo("keyup", key)
def hold(key, t): xdo("keydown", key); time.sleep(t); xdo("keyup", key)
def shot(name): subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99", "-frames:v", "1", f"{OUT}/drv_{name}.png"])
def say(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

def state():
    try:
        with open(LOG, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 20000)); tail = f.read().decode("latin-1")
    except OSError:
        return None
    m = None
    for m in LINE.finditer(tail): pass
    if not m: return None
    g = m.groups()
    return dict(x=float(g[0]), y=float(g[1]), z=float(g[2]), fx=float(g[3]), fy=float(g[4]), driving=g[5] == "driving",
                car=g[6] == "nearest", cx=float(g[7]), cy=float(g[8]), cd=float(g[9]), driven=bool(g[10]),
                parked=g[11] == "nearest", px=float(g[12]), py=float(g[13]), pd=float(g[14]))

def wait_state(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = state()
        if s: return s
        time.sleep(0.5)
    return None

def angle_to(s, tx, ty):
    """Signed angle from the facing to the direction of (tx,ty), radians; positive = target is to the right (clockwise seen from above, y south)."""
    dx, dy = tx - s["x"], ty - s["y"]
    n = math.hypot(dx, dy)
    if n < 1e-3: return 0.0
    dx, dy = dx / n, dy / n
    dot = s["fx"] * dx + s["fy"] * dy
    cross = s["fx"] * dy - s["fy"] * dx
    return math.atan2(cross, dot)

os.environ["DISPLAY"] = ":99"
win = ""
for _ in range(60):
    time.sleep(1)
    out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if '"GTA2"' in line and ("648x514" in line or "640x480" in line):
            win = line.split()[0]
    if win: break
say("game window", win)
xdo("windowfocus", "--sync", win)
time.sleep(15)
for i in range(5):
    tap("Return"); time.sleep(6)
s = wait_state(40)
say("in level:", s)
if not s: sys.exit(1)
shot("00_start")

# Which way does Left turn? Hold it a moment and compare the facing.
f0 = (s["fx"], s["fy"]); hold("Left", 0.4); time.sleep(0.7); s1 = wait_state()
turn = math.atan2(f0[0] * s1["fy"] - f0[1] * s1["fx"], f0[0] * s1["fx"] + f0[1] * s1["fy"])
left_sign = 1 if turn > 0 else -1     # sign of the angle change Left produces
rate = abs(turn) / 0.4
say(f"Left turns {turn:+.2f} rad in 0.4 s ({rate:.2f} rad/s)")
if rate < 0.2: rate = 1.5

# Go to the road beside the start and take a car as it passes: walk to a
# point on the kerb, then whenever a car comes within reach press Enter (GTA2
# lets you pull the driver out of a slow or stopped car).
def goto(tx, ty, tol=0.6, limit=40):
    for _ in range(limit):
        s = wait_state()
        if not s or s["driving"]: return s
        d = math.hypot(tx - s["x"], ty - s["y"])
        if d < tol: return s
        a = angle_to(s, tx, ty)
        if abs(a) > 0.3:
            key = "Left" if (a > 0) == (left_sign > 0) else "Right"
            hold(key, min(abs(a) / rate, 0.6))
        else:
            # walking speed is about 1.5 blocks a second; go most of the way in one hold
            hold("Up", min(2.5, max(0.25, (d - 0.3) / 1.6)))
    return wait_state()

def straighten(path):
    """keeps only the corners of a cell path, so a straight street is one leg"""
    if len(path) < 3: return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]): out.append(b)
    out.append(path[-1])
    return out

# The route to the nearest road, from the map itself (gmp.py), followed cell
# centre by cell centre.
sys.path.insert(0, "/work"); import gmp
blocks, columns = gmp.load("/tmp/wp/drive_c/Games/GTA2/data/wil.gmp")
level = int(s["z"]) - 1
if s["parked"] and s["pd"] < 60:
    say(f"parked car at {s['px']:.1f},{s['py']:.1f} d={s['pd']:.1f}: walking to it")
    path = gmp.route_to(blocks, columns, int(s["x"]), int(s["y"]), int(s["px"]), int(s["py"]), level) or []
else:
    path = gmp.route(blocks, columns, int(s["x"]), int(s["y"]), level) or []
say("route:", path)
for cx, cy in straighten(path)[1:]:
    s = goto(cx + 0.5, cy + 0.5, tol=0.5, limit=20)
    if s and s["driving"]: break
say("at", s["x"], s["y"])
if s["parked"] and s["pd"] < 3:
    for _ in range(6):
        s = goto(s["px"], s["py"], tol=0.9, limit=6)
        hold("Return", 0.5); time.sleep(2.0)
        s = wait_state()
        if s["driving"]: say("got into the parked car"); break
shot("01_road")
# A parked car - nobody at the wheel, not the phantom beside the player - is
# the one to take: walk to it by the map, step up to its side, hold the enter
# key. Failing that, hold it at the kerb while traffic passes.
def take_parked():
    s = wait_state()
    if not s or not s["parked"] or s["pd"] > 60: return s
    tx, ty = s["px"], s["py"]       # remembered: the reading moves on once we stand beside it
    say(f"parked car at {tx:.1f},{ty:.1f} d={s['pd']:.1f}: walking to it")
    path = gmp.route_to(blocks, columns, int(s["x"]), int(s["y"]), int(tx), int(ty), level) or []
    for cx, cy in straighten(path)[1:]:
        s = goto(cx + 0.5, cy + 0.5, tol=0.5, limit=20)
        if s and s["driving"]: return s
        if s and math.hypot(tx - s["x"], ty - s["y"]) < 1.8: break
    # Up to the car from four sides, holding Enter each time.
    for side in ((0.75, 0.0), (-0.75, 0.0), (0.0, 0.75), (0.0, -0.75)):
        s = wait_state()
        if s["driving"]: return s
        s = goto(tx + side[0], ty + side[1], tol=0.3, limit=10)
        a = angle_to(s, tx, ty)
        if abs(a) > 0.3:
            hold("Left" if (a > 0) == (left_sign > 0) else "Right", min(abs(a) / rate, 0.6))
        s = wait_state()
        say(f"at the car's side {side}: player {s['x']:.2f},{s['y']:.2f}, car {tx:.2f},{ty:.2f}, holding Enter")
        hold("Return", 0.8); time.sleep(2.5)
        s = wait_state()
        if s["driving"]: say("got into the parked car"); return s
    return s

s = take_parked()
shot("01_road")
if not s["driving"]:
    keys = [("Return", 25)]
    for key, secs in keys:
        s = wait_state()
        if s["driving"]: break
        say(f"holding {key} for {secs} s at the kerb")
        xdo("keydown", key)
        t0 = time.time(); closest = 99.0
        while time.time() - t0 < secs:
            s = wait_state()
            if s["driving"]: break
            if s["car"]: closest = min(closest, s["cd"])
            time.sleep(0.3)
        xdo("keyup", key)
        say(f"  closest car while {key} was down: {closest:.2f}")
        if s["driving"]: say(f"driving! the key was {key}"); break
shot("01_at_car")
s = wait_state()
if not s or not s["driving"]:
    say("never got into a car; walking instead")

# Drive (or walk) and cycle the views.
hold("Up", 4); shot("02_classic_moving")
tap("v"); say("third person"); time.sleep(2); shot("03_third")
hold("Up", 4); shot("04_third_moving"); hold("Right", 0.6); hold("Up", 3); shot("05_third_turned")
tap("v"); say("first person"); time.sleep(2); shot("06_first")
hold("Up", 4); shot("07_first_moving"); hold("Left", 0.6); hold("Up", 4); shot("08_first_turned")
hold("Up", 5); shot("09_first_more")
tap("v"); say("classic"); time.sleep(2); shot("10_classic")
say("done")
