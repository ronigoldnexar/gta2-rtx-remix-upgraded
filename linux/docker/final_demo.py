#!/usr/bin/env python3
"""The final demonstration, one continuous take: the opening, area 1 in the
classic view, a walk to the Downtown carriageway, V to third person (walk, turn,
look), V to first person (walk the street, look at traffic and people), then
into a car - a car that stops beside him at the kerb if one does, else the
developer scene warp (F10) - and a drive through all three views, out of the
car, and a few steps in third person. Events go to /out/marks.txt."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import gmp

say, tap, hold = D.say, D.tap, D.hold
T0 = time.time()

def mark(what):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {what}\n")
    say("MARK", what)

def words(s):
    return (f"state={s['state']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} face={s['fx']:.2f},{s['fy']:.2f} "
            f"{'DRIVING' if s['driving'] else 'on foot'} car d={s['cd']:.2f} head={s['chx']:.2f},{s['chy']:.2f}")

def face(tx, ty, tol=0.25):
    """turn until facing (tx,ty); a standing ped's logged facing comes from the
    sprite and can be a half turn off, so a short step first makes it the real one"""
    for i in range(6):
        if i == 0 or i == 3: hold("Up", 0.2); time.sleep(0.6)
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < tol: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, min(abs(a) / D.rate, 0.7)); time.sleep(0.3)
    return D.wait_state()

def walking_v(what):
    """V while already walking, so the camera move is seen over a moving player"""
    D.xdo("keydown", "Up"); time.sleep(0.4)
    tap("v"); mark(what); time.sleep(1.8)
    D.xdo("keyup", "Up")

# ---------------------------------------------------------------- to the street
D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
mark("level")
D.calibrate_turn()
level = int(s["z"]) - 1
blocks, columns = gmp.load("/tmp/wp/drive_c/Games/GTA2/data/wil.gmp")
s = D.wait_state()
sx, sy = int(s["x"]), int(s["y"])
path = gmp.route_to(blocks, columns, sx, sy, 156, 147, level)
if not path:
    path = [(159, 139), (158, 139), (157, 139), (157, 140), (156, 140), (156, 141), (156, 142), (156, 143),
            (156, 144), (156, 145), (156, 146), (156, 147)]
say("route:", path)
for cx, cy in D.straighten(path)[1:]:
    s = D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=20)
for attempt in range(3):
    if not (s["z"] > 2.5 or s["y"] < 146.0): break   # the carriageway is at z=2
    say("not down at the street yet; walking the known route")
    for cx, cy in [(157, 139), (157, 140), (156, 140), (156, 143), (156, 146), (156, 147)]:
        s = D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=12)
KERB_Y = 147.5                  # the middle of the north pavement: wall at y=147, railing at the kerb y=148
EAST, WEST = 167.2, 156.8       # the walkable run beside the carriageway
s = D.goto(WEST, KERB_Y, tol=0.3, limit=12)
mark("on_pavement")

# ---------------------------------------------------------------- classic
s = D.goto(WEST + 3.0, KERB_Y, tol=0.3, limit=8)
hold("Up", 1.0); time.sleep(0.6)

# ---------------------------------------------------------------- third person
face(EAST, KERB_Y)
walking_v("to_third")
face(EAST, KERB_Y); hold("Up", 0.6)
s = D.goto(WEST + 7.5, KERB_Y, tol=0.35, limit=10)
hold("Left", 0.8); time.sleep(0.8); hold("Right", 1.6); time.sleep(0.8); hold("Left", 0.8); time.sleep(0.5)
s = D.goto(WEST + 10.0, KERB_Y, tol=0.35, limit=8)
time.sleep(0.5)

# ---------------------------------------------------------------- first person
face(EAST, KERB_Y)
walking_v("to_first")
face(EAST, KERB_Y); hold("Up", 0.6)
s = D.goto(EAST - 1.0, KERB_Y, tol=0.35, limit=10)
# look at the traffic and the people across the street, then back along the pavement
face(s["x"] + 2.5, 150.5); time.sleep(1.2)   # over the railing, down the street at the traffic
face(WEST, KERB_Y); time.sleep(0.4)
s = D.goto(WEST + 6.0, KERB_Y, tol=0.35, limit=10)
face(EAST, KERB_Y)
s = D.goto(EAST - 1.5, KERB_Y, tol=0.35, limit=8)
mark("fp_done")

# ---------------------------------------------------------------- into a car
# Low cars whose hood frames the road from the driver's seat (catalog classes
# sedan, coupe, sports, muscle, taxi, police, compact); vans, trucks and buses
# fill the first-person frame with their cab, so they are let go while there
# is time to wait for another.
LOW_CARS = {0, 5, 10, 14, 18, 35, 42, 49, 50, 70, 1, 13, 57, 2, 19, 31, 37, 39, 44, 45, 46, 47, 48, 53, 82, 83,
            62, 71, 51, 56, 12, 52, 84, 8, 16, 40}
PICKY_UNTIL = [0.0]   # wall-clock until which only LOW_CARS are taken

def stopped_car(samples=3, gap=0.5, within=2.4):
    """a car that has not moved over the samples, close by; None otherwise"""
    pts = []
    for _ in range(samples):
        s = D.wait_state()
        if not s["car"] or s["cd"] > within: return None
        if time.time() < PICKY_UNTIL[0] and s.get("cmodel", -1) >= 0 and s["cmodel"] not in LOW_CARS:
            say(f"letting a model {s['cmodel']} go (not a low car)"); return None
        pts.append((s["cx"], s["cy"])); time.sleep(gap)
    if max(math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) for p in pts) > 0.3: return None
    return D.wait_state()

def watch_entry(seconds, label):
    """after Return: the game walks him to the car (state 2), opens the door
    (3/6) and he drives (10); gives up when he is back to standing (0) for a while"""
    t0 = time.time(); last = ""; idle_since = None
    while time.time() - t0 < seconds:
        s = D.wait_state(); w = words(s)
        if w != last: say(f"{label} +{time.time()-t0:4.1f}s {w}"); last = w
        if s["driving"]: return s
        if s["state"] in (2, 3, 6): idle_since = None
        elif time.time() - t0 > 3.0:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 2.5: return None
        time.sleep(0.4)
    return None

got = None
natural = False
WAIT_X, WAIT_Y = 165.5, 147.65     # on the pavement (standing in the lane got him run over), where take 1 saw cars stop
mark("wait_for_car")
# stand at the kerb short of the lights and watch the lane beside him; Return
# the moment a car has stopped near: the game itself walks him to its door.
s = D.goto(WAIT_X, WAIT_Y, tol=0.25, limit=6)
face(EAST, KERB_Y + 0.2)
def alive_and_here(s):
    """dead/arrested, he reappears at the plaza (z=3, y~140); walk back to the road"""
    if s and s["z"] < 2.5 and abs(s["y"] - WAIT_Y) < 4.0: return True
    mark("respawned_walk_back")
    for cx, cy in [(157, 139), (157, 140), (156, 140), (156, 143), (156, 146), (156, 147)]:
        D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=12)
    D.goto(WAIT_X, WAIT_Y, tol=0.3, limit=10); face(EAST, WAIT_Y)
    return False

def wake():
    """a ped that has stood still ignores Enter (state 7): a step first"""
    hold("Up", 0.3); time.sleep(0.3)
    for _ in range(6):
        s = D.wait_state()
        if s["state"] != 7: return s
        hold("Left", 0.2); hold("Up", 0.3); time.sleep(0.5)
    return D.wait_state()

t0 = time.time(); tries = 0
PICKY_UNTIL[0] = t0 + 75
while time.time() - t0 < 110 and not got:
    s = D.wait_state()
    if not alive_and_here(s): continue
    c = stopped_car()
    if c:
        tries += 1
        mark(f"car_stopped_{tries}")
        say(f"natural {tries}: car at {c['cx']:.2f},{c['cy']:.2f} d={c['cd']:.2f} head {c['chx']:.2f},{c['chy']:.2f}")
        wake()
        tap("Return", 0.3)
        got = watch_entry(14, f"natural {tries}")
        natural = bool(got)
        if not got:
            s = D.wait_state()
            if math.hypot(s["x"] - (EAST - 1.5), s["y"] - (KERB_Y + 0.2)) > 0.6:
                s = D.goto(WAIT_X, WAIT_Y, tol=0.25, limit=6); face(EAST, KERB_Y + 0.2)
    else:
        time.sleep(0.3)
if not got:
    mark("warp_fallback")
    for attempt in range(1, 5):
        alive_and_here(D.wait_state())
        wake()
        tap("F10", 0.3); time.sleep(1.2)
        s = D.wait_state(); say(f"after F10 ({attempt}): {words(s)}")
        tap("Return", 0.3)
        got = watch_entry(14, f"warp {attempt}")
        if got: break
mark("driving" if got else "no_car")
say("ENTRY:", "natural" if natural else ("warp" if got else "none"))

# ---------------------------------------------------------------- the drive
def cruise(seconds, weave=True, turn=None):
    t0 = time.time(); n = 0
    while time.time() - t0 < seconds:
        hold("Up", 2.0); n += 1
        if turn and n == 2: hold(turn, 0.9)
        elif weave: hold("Left" if n % 2 else "Right", 0.3)
    say("cruise:", words(D.wait_state()))

if got:
    time.sleep(1.5)                                   # the eye settles in the cabin
    cruise(10, weave=False)                          # first person at the wheel
    tap("v"); mark("drive_classic"); time.sleep(1.5)
    cruise(10)
    tap("v"); mark("drive_third"); time.sleep(1.5)
    cruise(22, turn="Left")
    tap("v"); mark("drive_first"); time.sleep(1.5)
    cruise(22, turn="Right")
    tap("v"); mark("drive_classic_2"); time.sleep(1.5)
    cruise(8, weave=False)
    hold("Down", 1.5); time.sleep(0.8)
    tap("Return", 0.3); mark("leave_car"); time.sleep(2.5)
    s = D.wait_state(); say("after leaving:", words(s))
    tap("v"); mark("foot_third"); time.sleep(1.5)
    hold("Up", 2.5); hold("Left", 0.6); hold("Up", 2.0); time.sleep(1.0)
mark("end")
say("done")
