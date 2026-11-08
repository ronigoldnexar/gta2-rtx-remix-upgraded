#!/usr/bin/env python3
"""POLICE-3D probe, Downtown: the police on the player through the game's own
wanted field. [devtools] force_wanted (the player's cop points, ped+0x20A) is set
in the running game's ini (re-read once a second), so the police manager picks him
up as after a crime. POL_MODE:
  arrest  1 star, held POL_HOLD s (default 25) then released; bare hands, standing
          still at the plaza so an officer walks up and busts him; frames every 0.3 s
          and the player's frame/state words (GTA2DX9_LOG_PED_FRAMES=1).
  fight   POL_STARS (default 3) held; the machine gun pickup, standing at the plaza
          and turning so the officers shooting at him come into the frame.
  car     POL_STARS (default 3) held while the player sits in a car on a street (warp_key F9
          to the nearest parked car's door, Return): the police fire at a wanted driver; the
          car crawls and turns now and then so the officers come into the chase view.
POL_SECS (default 150) is the watch time, POL_X/POL_Y the spot. POL_COPCAR=1 (needs
GTA2DX9_LOG_VEHICLES=1): instead of the plaza, stand three blocks ahead of the
nearest driven cop car (model 12) once the wanted level is set, so an officer sees
him; repeated every POL_REWARP s (default 45) while nothing happens."""
import os, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

MODE = os.environ.get("POL_MODE", "arrest")
STARS = int(os.environ.get("POL_STARS", "1" if MODE == "arrest" else "3"))
HOLD = float(os.environ.get("POL_HOLD", "25"))
SECS = float(os.environ.get("POL_SECS", "150"))
X, Y = float(os.environ.get("POL_X", "159.5")), float(os.environ.get("POL_Y", "139.5"))


def set_wanted(n):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(r"(?m)^force_wanted=.*$", f"force_wanted={n}", t)
    if t2 == t and "force_wanted=" not in t:
        t2 = t.replace("[devtools]", f"[devtools]\nforce_wanted={n}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK force_wanted={n}")


VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
def cop_cars():
    last = None
    for line in Q.log_text(80000).splitlines():
        if "] vehicles:" in line: last = line
    return [(float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "") if m[0] == "12"]


def to_cop_car():
    cs = sorted(cop_cars(), key=lambda c: -c[5])
    if not cs: say("MARK no cop car listed"); return False
    x, y, z, fx, fy, d = cs[0]
    wx, wy = x + fx * 3.0 - fy * 0.8, y + fy * 3.0 + fx * 0.8
    say(f"MARK cop car at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f} driven {d}: warp {wx:.1f},{wy:.1f}")
    T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="ahead of a cop car")
    A.face(x, y)
    Q.set_view("third", settle=0.5)
    return True


def player_state():
    m = None
    for m in re.finditer(r"ped anim: player frame (\d+) \((\d+)\) state (\d+) sub (0x[0-9a-f]+)", Q.log_text(20000)): pass
    return m.group(0) if m else "?"


s = Q.start("pol_" + MODE)
if MODE == "car":
    T.warp(164.5, 147.6, 2, why="street")
    time.sleep(3.0)   # on foot a moment: the renderer takes his ped from his own sprite
    for attempt in range(3):
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(4.0)
        if D.wait_state()["driving"]: break
    say("MARK in a car:", D.wait_state()["driving"])
    Q.set_view("third", settle=1.0)
    set_wanted(STARS)
    t0 = time.time(); n = 0
    while time.time() - t0 < SECS:
        shot(f"c_{n:03d}"); n += 1; time.sleep(0.2)
        if n % 10 == 0:
            w = A.mission(); say(f"MARK car t={time.time() - t0:.0f} wanted {w[0]} health {w[1]} driving {D.wait_state()['driving']}")
            A.save_log()
        if n % 15 == 0:
            D.xdo("keydown", "Up"); time.sleep(0.3); D.xdo("keyup", "Up")
            hold("Left", 0.5)
    set_wanted(-1)
    A.finish(); sys.exit(0)
if MODE == "fight":
    A.collect(166.5, 140.5, 2, "machine_gun")
T.warp(X, Y, 2, why="plaza")
Q.set_view("third", settle=1.0)
set_wanted(STARS)
COPCAR = os.environ.get("POL_COPCAR", "0") == "1"
REWARP = float(os.environ.get("POL_REWARP", "45"))
last_warp = time.time()
if COPCAR:
    time.sleep(1.0); to_cop_car(); last_warp = time.time()
t0 = time.time(); n = 0; released = False; busted = None
while time.time() - t0 < SECS:
    el = time.time() - t0
    if MODE == "arrest" and not released and el > HOLD:
        set_wanted(-1); released = True
    shot(f"{MODE[0]}_{n:03d}"); n += 1
    time.sleep(0.1 if busted else (0.3 if MODE == "arrest" else 0.2))
    if n % 10 == 0:
        w = A.mission()
        say(f"MARK {MODE} t={el:.0f} wanted {w[0]} health {w[1]} weapon {w[2]} {player_state()}")
        A.save_log()
    if COPCAR and busted is None and time.time() - last_warp > REWARP:
        to_cop_car(); last_warp = time.time()
    if MODE == "arrest":
        if n % 25 == 0 and busted is None: hold("Left", 0.3)
        txt = Q.log_text(6000)
        if busted is None and "wanted: busted" in txt:
            busted = time.time(); say("MARK busted", player_state()); set_wanted(-1); released = True
        if busted and time.time() - busted > 12: break
    elif COPCAR:
        # shoot at the police so they shoot back: face the nearest cop car, a burst every ~2 s;
        # after a bust (weapons taken) fetch the machine gun again
        if n % 8 == 0:
            if A.mission()[2] == "none":
                A.collect(166.5, 140.5, 2, "machine_gun"); to_cop_car(); last_warp = time.time()
            cs = cop_cars()
            if cs:
                s0 = D.wait_state()
                c = min(cs, key=lambda c: (c[0] - s0["x"]) ** 2 + (c[1] - s0["y"]) ** 2)
                A.face(c[0], c[1], tries=3)
            A.fire(f"f_fire_{n:03d}", secs=0.8, every=0.2)
            hold("Left", 0.6); shot(f"f_look_{n:03d}"); hold("Right", 0.6)
    else:
        if n % 10 == 0: hold("Left", 0.45)
        if n % 60 == 0: A.fire(f"f_fire_{n:03d}", secs=0.4, every=0.2)
        if n == 400: Q.set_view("first", settle=0.5)
set_wanted(-1)
A.finish()
