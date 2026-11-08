#!/usr/bin/env python3
"""Plays GTA2 from the renderer's log: reads the player's position, facing and
the nearest car (the 'view: player' line the mod logs twice a second), walks to
the car, gets in, drives, and cycles the views on the way. Keys go through
xdotool to the focused game window."""
import math, os, re, subprocess, sys, time

# Game speed. GTA2 steps its simulation once per rendered frame, so a run with
# fps_cap=60 plays twice as fast (GTA2_SPEED=2, set by gamerun/grun.sh). Every
# sleep and key hold in the runners is written in game seconds; here they are
# scaled to wall time, for every module that imports this one.
SPEED = float(os.environ.get("GTA2_SPEED", "1") or 1)
_real_sleep = time.sleep
def gsleep(seconds): _real_sleep(seconds / SPEED)
if SPEED != 1.0: time.sleep = gsleep
def game_seconds(frame): return frame / 30.0   # the renderer's frame counter in GTA2 seconds

LOG = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.log"
OUT = "/out"
LINE = re.compile(r"view: player x=([-\d.]+) y=([-\d.]+) z=([-\d.]+) face=([-\d.]+),([-\d.]+) (on foot|driving) \| car (nearest|none) x=([-\d.]+) y=([-\d.]+) d=([-\d.]+)( \(driven\))? \| parked (nearest|none) x=([-\d.]+) y=([-\d.]+) d=([-\d.]+)")

CARMODEL = re.compile(r"carmodel=(-?\d+)")
FIRE = re.compile(r"fire=(\d+)")
EXTRA = re.compile(r" \| carhead=([-\d.]+),([-\d.]+) parkedhead=([-\d.]+),([-\d.]+) ped state=(-?\d+) sub=(-?\d+) pend=(-?\d+) veh=([0-9A-F]+)")

def xdo(*args): subprocess.run(["xdotool", *args], check=False)
def tap(key, t=0.25): xdo("keydown", key); time.sleep(t); xdo("keyup", key)
def hold(key, t): xdo("keydown", key); time.sleep(t); xdo("keyup", key)
def shot(name): subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99", "-frames:v", "1", f"{OUT}/drv_{name}.png"])
def say(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

_TAIL = [0.0, ""]
def log_tail(max_age=0.03):
    """the last 120 KB of the renderer's log, read at most once per `max_age` wall seconds
    (PLAYTHROUGH-9: the smooth driver reads the player, mission, peds and cars lines every
    step; four separate reads made a control step 0.3-0.5 s long)"""
    now = time.time()
    if now - _TAIL[0] > max_age:
        try:
            with open(LOG, "rb") as f:
                f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 120000)); _TAIL[1] = f.read().decode("latin-1")
        except OSError:
            _TAIL[1] = ""
        _TAIL[0] = now
    return _TAIL[1]

def state():
    tail = log_tail()
    if not tail: return None
    k = tail.rfind("view: player x=")
    if k < 0: return None
    k2 = tail.rfind("view: player x=", 0, k)      # the one before too: the last may be half written
    tail = tail[max(0, (k2 if k2 >= 0 else k) - 10):]
    m = None
    for m in LINE.finditer(tail): pass
    if not m: return None
    g = m.groups()
    s = dict(x=float(g[0]), y=float(g[1]), z=float(g[2]), fx=float(g[3]), fy=float(g[4]), driving=g[5] == "driving",
                car=g[6] == "nearest", cx=float(g[7]), cy=float(g[8]), cd=float(g[9]), driven=bool(g[10]),
                parked=g[11] == "nearest", px=float(g[12]), py=float(g[13]), pd=float(g[14]),
                chx=0.0, chy=0.0, phx=0.0, phy=0.0, state=-1, sub=-1, pend=-1, veh="")
    e = EXTRA.match(tail, m.end())
    if e:
        cm = CARMODEL.search(tail, e.end(), min(len(tail), e.end() + 400))
        s["cmodel"] = int(cm.group(1)) if cm else -1
        fm = FIRE.search(tail, e.end(), min(len(tail), e.end() + 400))
        s["fire"] = int(fm.group(1)) if fm else 0
        s.update(chx=float(e.group(1)), chy=float(e.group(2)), phx=float(e.group(3)), phy=float(e.group(4)),
                 state=int(e.group(5)), sub=int(e.group(6)), pend=int(e.group(7)), veh=e.group(8))
    return s

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


left_sign = 1; rate = 1.5
def start():
    os.environ["DISPLAY"] = ":99"
    win = ""
    for _ in range(60):
        time.sleep(1)
        out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if '"GTA2"' in line and ("648x514" in line or "640x480" in line): win = line.split()[0]
        if win: break
    say("game window", win)
    xdo("windowfocus", "--sync", win)
    # already in the level (a keys script ran to_level.sh first): nothing to press
    try:
        if "view: classic (player found" in open(LOG, "rb").read().decode("latin-1"): say("start: already in the level"); return
    except OSError: pass
    time.sleep(20)
    for i in range(5):
        tap("Return"); time.sleep(6)

def calibrate_turn():
    global left_sign, rate
    s = wait_state()
    f0 = (s["fx"], s["fy"]); hold("Left", 0.4); time.sleep(0.7); s1 = wait_state()
    turn = math.atan2(f0[0] * s1["fy"] - f0[1] * s1["fx"], f0[0] * s1["fx"] + f0[1] * s1["fy"])
    if abs(turn) > 1.6:
        # the facing flipped between the samples (the standing heading comes
        # from the sprite, the walking one from motion): measure again, slower
        time.sleep(0.8); s0 = wait_state(); f0 = (s0["fx"], s0["fy"]); hold("Left", 0.4); time.sleep(0.9); s1 = wait_state()
        turn = math.atan2(f0[0] * s1["fy"] - f0[1] * s1["fx"], f0[0] * s1["fx"] + f0[1] * s1["fy"])
    if abs(turn) < 0.08:
        say(f"turn calibration unreliable ({turn:+.2f} rad); using the defaults")
        left_sign, rate = -1, 1.5          # the sign every measured run has given
        return
    left_sign = 1 if turn > 0 else -1      # the sign is reliable even when the magnitude is not
    rate = min(8.0, max(0.8, abs(turn) / 0.4))   # peds turn about 6 rad/s; measured, not clamped low
    say(f"Left turns {turn:+.2f} rad in 0.4 s")

def goto(tx, ty, tol=0.6, limit=40):
    """walk to (tx,ty). A standing ped's logged facing comes from his sprite
    and can be a half turn off; the facing of a moving ped comes from his
    motion and is right, so every turn is preceded by a short step."""
    still = 0; last = None
    for _ in range(limit):
        s = wait_state()
        if not s or s["driving"]: return s
        d = math.hypot(tx - s["x"], ty - s["y"])
        if d < tol: return s
        # not moving at all across three tries: blocked; let the caller unstick
        here = (round(s["x"], 1), round(s["y"], 1))
        still = still + 1 if here == last else 0; last = here
        if still >= 3: return s
        a = angle_to(s, tx, ty)
        if abs(a) > 0.3:
            # turn in short pieces and re-read: the facing is logged twice a
            # second and the turn is fast, so a long hold overshoots
            key = "Left" if (a > 0) == (left_sign > 0) else "Right"
            hold(key, min(abs(a) / rate, 0.3)); time.sleep(0.35)
        else:
            # walking speed is about 1.9 blocks a second; go most of the way in one hold
            hold("Up", min(2.5, max(0.25, (d - 0.3) / 1.9)))
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

# ---------------------------------------------------------------- the smooth driver (PLAYTHROUGH-9)
# The wall-aware driver (mission_lib.drive3) aimed at straightened legs: a leg from cell
# centre to cell centre with 0.45 blocks of clearance, a crawl into every corner and a
# heading controller that pulsed the wheel toward the next corner. The Industrial legs
# showed what that costs a fragile car: the legs run along the walls (a straight line
# between two corners of a road is free to hug one side), the corner is entered with the
# nose already turned in, and every scrape is a few hundred carhp. Here the car follows
# the route's own cells (each road cell's centre is its lane centre: GTA2 roads are one
# cell per lane) with pure pursuit on a path resampled every 0.25 blocks, and its speed
# comes from the turns ahead: the sharpest heading change within the braking distance
# sets the speed it may carry into it.
STEP = 0.25           # resampling step, blocks
ACCEL_BRAKE = 2.2     # blocks/s^2 the speed profile assumes the car can shed (measured braking ~3)

def dense_path(points, step=STEP):
    """a polyline (cell centres) resampled every `step` blocks"""
    out = [points[0]]
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step + 0.5))
        for k in range(1, n + 1): out.append((ax + (bx - ax) * k / n, ay + (by - ay) * k / n))
    return out

def path_headings(P, span=4):
    """the path's heading at each sample (over `span` samples ahead)"""
    h = []
    for j in range(len(P)):
        a, b = P[min(j, len(P) - 2)], P[min(len(P) - 1, j + span)]
        h.append(math.atan2(b[1] - a[1], b[0] - a[0]) if (a != b) else (h[-1] if h else 0.0))
    return h

def wrap(a):
    while a > math.pi: a -= 2 * math.pi
    while a < -math.pi: a += 2 * math.pi
    return a

def nearest_index(P, j0, x, y, window=48):
    """the sample nearest (x,y) at or after j0 (searched a few blocks ahead), and its distance"""
    best, bj = 1e9, j0
    for j in range(max(0, j0 - 4), min(len(P), j0 + window)):
        d = (P[j][0] - x) ** 2 + (P[j][1] - y) ** 2
        if d < best: best, bj = d, j
    return bj, math.sqrt(best)

def turn_speed(angle, cap):
    """the speed a car may carry through a heading change of `angle` radians over 2 blocks:
    a right-angle street corner at 1.3 blocks/s (the GTA2 cars slide wide above ~2), a
    gentle bend nearly at the cap"""
    if angle < 0.12: return cap
    return max(1.1, min(cap, 1.3 + (cap - 1.3) * max(0.0, 1.0 - angle / 1.2) ** 1.5))

def speed_target(P, H, j, cap, end_tol=1.0, look=14.0, final=True):
    """the profile speed at sample j: every turn ahead within `look` blocks, and the goal
    (when `final`), limit it by v^2 = v_turn^2 + 2 a s"""
    vt = cap
    n = len(P); w = int(2.0 / STEP)
    for m in range(j, min(n - 1, j + int(look / STEP))):
        s = (m - j) * STEP
        ang = abs(wrap(H[min(n - 1, m + w)] - H[m]))
        if ang < 0.12: continue
        vt = min(vt, math.sqrt(turn_speed(ang, cap) ** 2 + 2 * ACCEL_BRAKE * max(0.0, s - 0.5)))
    if final:
        left = (n - 1 - j) * STEP - end_tol
        vt = min(vt, max(0.9, math.sqrt(2 * ACCEL_BRAKE * max(0.0, left)) * 0.8))
    return vt

def lookahead(P, j, v):
    """the pursuit point: 1.3 blocks ahead at a crawl, up to 3 at speed (the car rounds a
    corner inside the road's cells instead of cutting it)"""
    L = min(3.0, 1.3 + 0.32 * max(0.0, v))
    return P[min(len(P) - 1, j + int(L / STEP))]
