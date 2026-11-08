#!/usr/bin/env python3
"""POLICE-3D probe, Downtown: the special vehicles in frame. The renderer's
'vehicles:' line (GTA2DX9_LOG_VEHICLES=1) gives where the tank (54), fire truck
(17), trains (59-61), buses (11, 86), ambulance (34), SWAT van (52) and cop cars
(12) are. POL_VEH picks the items in order (default "tank firetruck train bus"):
  tank / firetruck  warp to the parked vehicle's nose (on its level), frames from
                    classic/third/first, get in (Return), drive a little and fire
                    (the turret / the water cannon), frames in third person
  train             stand on the elevated line's level beside the track ahead of a
                    train, frames while it passes
  bus               warp ahead of a driving bus, to its side, frames while it passes
  army              wanted level 6 ([devtools] force_wanted=6): the army comes with
                    tanks (model 54 driven); stand on a street, and once a tank is
                    listed, stand ahead of it and to its side; frames while it comes
                    and aims (its turret)
Run with GTA2DX9_SCENE_NO_CAR=1 and scene_key=F10 (INI_SED), nav_map=0."""
import os, re, sys, time, math
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
def vehicles():
    last = None
    for line in Q.log_text(80000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]

def find(models, driven=None, near=None):
    vs = [v for v in vehicles() if v[0] in models and (driven is None or v[6] == driven)]
    if near: vs.sort(key=lambda v: (v[1] - near[0]) ** 2 + (v[2] - near[1]) ** 2)
    return vs

def frames(label, n=4, every=0.35):
    for k in range(n): shot(f"{label}_{k}"); time.sleep(every)

def parked(label, models, dist=1.6):
    vs = find(models, driven=0) or find(models)
    if not vs: say("no", label, "in the vehicle list"); return
    m, x, y, z, fx, fy, d = vs[0]
    wx, wy = x + fx * dist, y + fy * dist
    say(f"MARK {label} m{m} at {x:.2f},{y:.2f},{z:.2f} heading {fx:.2f},{fy:.2f}; warp to its nose {wx:.2f},{wy:.2f}")
    s = T.warp(round(wx, 2), round(wy, 2), int(round(z)), why=label)
    say(f"MARK {label}: player at {s['x']:.2f},{s['y']:.2f} z={s['z']:.2f}, {math.hypot(s['x'] - x, s['y'] - y):.2f} from it")
    shot(f"{label}_c")
    A.face(x, y)
    Q.set_view("third", settle=0.6); frames(f"{label}_t", 3)
    hold("Left", 0.3); shot(f"{label}_t_side")
    Q.set_view("first", settle=0.5); A.face(x, y); frames(f"{label}_f", 2)
    Q.set_view("third", settle=0.5)
    # in: Return walks him to the nearest car and in
    tap("Return", 0.3)
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < 10 and not s["driving"]:
        time.sleep(0.5); s = D.wait_state()
    say(f"MARK {label}: driving={s['driving']} carmodel {A.mission()}")
    if not s["driving"]: frames(f"{label}_noentry", 2); return
    time.sleep(1.0); frames(f"{label}_in", 3)
    for k in range(4):
        D.xdo("keydown", "Up"); time.sleep(0.6); D.xdo("keyup", "Up")
        hold("Left" if k % 2 == 0 else "Right", 0.5)
        A.fire(f"{label}_fire{k}", secs=0.8, every=0.2)
        shot(f"{label}_drive{k}")
    Q.set_view("first", settle=0.5); A.fire(f"{label}_fp_fire", secs=0.8, every=0.25)
    Q.set_view("classic", settle=0.5); A.fire(f"{label}_c_fire", secs=0.6, every=0.3)
    Q.set_view("third", settle=0.5)
    T.leave_car(); A.save_log()

def train():
    """an elevated train (z about 3) from the street: three and a half blocks to the side of
    its line, eight blocks ahead of it, facing the line; frames while it passes overhead"""
    k = 0; t0 = time.time()
    while k < 3 and time.time() - t0 < 200:
        # away from the map's edges (the harbour water at the west end drowned him)
        tr = [v for v in find((59, 60, 61)) if abs(v[3] - 3.0) < 0.2 and 50 < v[1] < 220 and 30 < v[2] < 220]
        if not tr: time.sleep(3.0); continue
        k += 1
        m, x, y, z, fx, fy, d = tr[0]
        ahead = float(os.environ.get("POL_TRAIN_AHEAD", "22"))   # trains cover ~3 blocks/s; the warp takes ~4 s
        px, py = x + fx * ahead, y + fy * ahead                  # the line ahead of it
        wx, wy = px - fy * 4.5, py + fx * 4.5
        say(f"MARK train {k} m{m} at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}; warp {wx:.1f},{wy:.1f},2 facing {px:.1f},{py:.1f}")
        s = T.warp(round(wx, 1), round(wy, 1), 2, why="street beside the elevated line")
        A.face(px + fx * -6.0, py + fy * -6.0)               # towards the line, a little up it
        Q.set_view("first", settle=0.2); D.xdo("mousemove_relative", "--", "0", "-80")
        for i in range(24):
            shot(f"tr{k}_{i:02d}"); time.sleep(0.2)
            if i == 14:
                D.xdo("mousemove_relative", "--", "0", "80"); Q.set_view("third", settle=0.2)
        Q.set_view("classic", settle=0.3); shot(f"tr{k}_c")
        A.save_log()

def bus():
    for k in range(3):
        bs = find((11, 86), driven=1)
        if not bs:
            T.warp(174.5, 119.0, 2, why="bus route"); time.sleep(4.0); continue
        m, x, y, z, fx, fy, d = bs[0]
        wx, wy = x + fx * 5.0 - fy * 1.6, y + fy * 5.0 + fx * 1.6
        say(f"MARK bus {k} m{m} at {x:.1f},{y:.1f} heading {fx:.2f},{fy:.2f}; warp {wx:.1f},{wy:.1f}")
        T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="ahead of a bus")
        A.face(x, y)
        Q.set_view("third", settle=0.2)
        for i in range(14):
            shot(f"bus{k}_{i:02d}"); time.sleep(0.3)
            b2 = find((m,), near=(x, y))
            if b2 and i % 3 == 0: A.face(b2[0][1], b2[0][2], tries=1)
        A.save_log()
        return

def set_wanted(n):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^force_wanted=.*$", f"force_wanted={n}", t)
    open(T.INI, "w", encoding="latin-1").write(t)
    say(f"MARK force_wanted={n}")

def army():
    T.warp(164.5, 147.6, 2, why="street for the army")
    Q.set_view("third", settle=0.5)
    set_wanted(6)
    t0 = time.time(); k = 0
    while time.time() - t0 < float(os.environ.get("POL_ARMY_SECS", "150")):
        tk = find((54,), driven=1)
        if not tk:
            shot(f"army_wait_{k:02d}"); k += 1; time.sleep(2.0); continue
        m, x, y, z, fx, fy, d = tk[0]
        wx, wy = x + fx * 4.0 - fy * 1.5, y + fy * 4.0 + fx * 1.5
        say(f"MARK army tank at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}: warp {wx:.1f},{wy:.1f}")
        T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="ahead of an army tank")
        A.face(x, y); Q.set_view("third", settle=0.3)
        for i in range(16):
            shot(f"tank{k:02d}_{i:02d}"); time.sleep(0.3)
            t2 = find((54,), near=(x, y))
            if t2 and i % 4 == 0: A.face(t2[0][1], t2[0][2], tries=1)
            if i == 10: Q.set_view("first", settle=0.2)
        Q.set_view("classic", settle=0.3); shot(f"tank{k:02d}_c")
        k += 1; A.save_log()
    set_wanted(-1)

def rescue():
    """the ambulance (34) and fire truck (17) come to the carnage the army leaves: wanted 6
    for the mayhem, then stand ahead of a driven one and to its side, frames as it comes
    (its roof beacons, the fire truck's cannon)"""
    T.warp(164.5, 147.6, 2, why="street for the army")
    Q.set_view("third", settle=0.5)
    set_wanted(6)
    t0 = time.time(); k = 0; seen = set()
    while time.time() - t0 < float(os.environ.get("POL_RESCUE_SECS", "170")):
        rv = [v for v in find((34, 17), driven=1) if (v[0], round(v[1]), round(v[2])) not in seen]
        if not rv:
            time.sleep(2.0); continue
        m, x, y, z, fx, fy, d = rv[0]
        if k >= 2: set_wanted(-1)   # enough carnage; let the player live
        wx, wy = x + fx * 3.5 - fy * 1.3, y + fy * 3.5 + fx * 1.3
        say(f"MARK rescue m{m} at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}: warp {wx:.1f},{wy:.1f}")
        T.warp(round(wx, 1), round(wy, 1), int(round(z)), why=f"ahead of model {m}")
        A.face(x, y); Q.set_view("third", settle=0.3)
        for i in range(14):
            shot(f"r{m}_{k:02d}_{i:02d}"); time.sleep(0.25)
            r2 = find((m,), near=(x, y))
            if r2 and i % 4 == 0: A.face(r2[0][1], r2[0][2], tries=1)
        seen.add((m, round(x), round(y))); k += 1; A.save_log()
    set_wanted(-1)

s = Q.start("pol_vehicles")
time.sleep(3.0)
for item in os.environ.get("POL_VEH", "tank firetruck train bus").split():
    say("MARK item", item, "vehicles", sorted(set(v[0] for v in vehicles())))
    if item == "tank": parked("tank", (54,))
    elif item == "firetruck": parked("firetruck", (17,))
    elif item == "ambulance": parked("ambulance", (34,))
    elif item == "train": train()
    elif item == "bus": bus()
    elif item == "army": army()
    elif item == "rescue": rescue()
A.finish()
