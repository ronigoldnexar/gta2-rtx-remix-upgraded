#!/usr/bin/env python3
"""ACTIONS-3D-3 probe, Downtown. A33_ITEMS picks, in order (default "types"):
  types      every special pedestrian type in one frame each: the renderer is told which
             remap to draw everyone as, the player's own figure included
             (GTA2DX9_PED_REMAP_FILE, re-read twice a second); his figure in third person
             from behind and the side at the plaza (A33_TYPES_AT, default 159.5,139.5).
             A showcase of the 3D figure per type; the game's own types come from 'army'
             and the other items
  army       wanted level 6 ([devtools] force_wanted=6): soldiers and tanks come; stand
             ahead of a tank, frames in classic, third and first person (the soldiers'
             3D figures, their rifles, their shots)
  gunfire    A33_STARS (default 5) held; the player at the wheel of a car driving away
             through traffic (Up held, a turn now and then), frames of the pursuers;
             then on foot with the machine gun (COLLECT_02) holding position, a burst
             at the nearest cop car every few seconds
  train      the elevated line's station at 99.5,97.7 (level 3): train 2 stops there about
             50 s after the level starts heading +y; stand on the platform beside the
             track facing down the line, frames as it comes in, stops and leaves
  firetruck  the Downtown kill-frenzy fire truck (5.5,26.5): in, drive, water cannon (fire),
             frames from the chase camera (beacons), first person
  ambulance  watch the vehicle list for model 34 after the frenzy's deaths; stand ahead
             of it, frames as it comes
Run with GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_VEHICLES=1 and the INI_SED setting
scene_key=F10, warp_key=F9, nav_map=0."""
import os, re, sys, time, math
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
def vehicles():
    last = None
    for line in Q.log_text(120000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]

def find(models, driven=None, near=None):
    vs = [v for v in vehicles() if v[0] in models and (driven is None or v[6] == driven)]
    if near: vs.sort(key=lambda v: (v[1] - near[0]) ** 2 + (v[2] - near[1]) ** 2)
    return vs

def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK {key}={val}")

def frames(label, n=4, every=0.35):
    for k in range(n): shot(f"{label}_{k:02d}"); time.sleep(every)

REMAP_FILE = "/tmp/wp/drive_c/Games/GTA2/a33_remap.txt"   # GTA2DX9_PED_REMAP_FILE=a33_remap.txt (the game folder)
TYPES = [(0, "police_blue"), (1, "police_green"), (4, "army"), (5, "redneck"), (7, "scientist"), (8, "zaibatsu"),
         (9, "krishna"), (10, "russian"), (11, "loony"), (12, "elvis"), (13, "yakuza"), (14, "fireman"), (16, "medic"),
         (17, "mugger"), (22, "prisoner"), (23, "hulk"), (15, "civ_green_shorts"), (27, "civ_blue_shirt"), (52, "civ_pink_shirt")]

def types():
    """the override draws the player's figure (and everyone else) as the remap: his figure
    from behind and, after a quick turn, from the side, in third person; then first person
    looking at the crowd"""
    T.warp(*[float(v) for v in os.environ.get("A33_TYPES_AT", "159.5,139.5").split(",")], 2, why="plaza")
    Q.set_view("third", settle=0.8)
    for remap, name in TYPES:
        open(REMAP_FILE, "w").write(f"{remap}\n"); time.sleep(1.0)
        shot(f"type_{remap:02d}_{name}_t")
        A.side(f"type_{remap:02d}_{name}_side", "Left", 0.30)
        A.side(f"type_{remap:02d}_{name}_side2", "Left", 0.30)
    open(REMAP_FILE, "w").write("-1\n")
    A.save_log()

def army():
    T.warp(164.5, 147.6, 2, why="street for the army")
    Q.set_view("third", settle=0.5)
    set_ini("force_wanted", 6)
    t0 = time.time(); k = 0
    while time.time() - t0 < float(os.environ.get("A33_ARMY_SECS", "150")) and k < 4:
        tk = find((54,), driven=1)
        if not tk:
            if int(time.time() - t0) % 6 < 2: shot(f"army_wait_{int(time.time() - t0):03d}")
            time.sleep(2.0); continue
        m, x, y, z, fx, fy, d = tk[0]
        wx, wy = x + fx * 4.0 - fy * 1.5, y + fy * 4.0 + fx * 1.5
        say(f"MARK army tank at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f}: warp {wx:.1f},{wy:.1f}")
        T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="ahead of an army tank")
        A.face(x, y); Q.set_view("third", settle=0.3)
        for i in range(24):
            v = "third" if (i // 6) % 2 == 0 else "first"
            if i % 6 == 0: Q.set_view(v, settle=0.2)
            shot(f"army{k}_{v[0]}x_{i:02d}"); time.sleep(0.3)
            if i % 5 == 4: hold("Left", 0.3)
        Q.set_view("third", settle=0.2)
        Q.set_view("first", settle=0.3)
        for i in range(10):
            shot(f"army{k}_f_{i:02d}"); time.sleep(0.3)
            if i % 4 == 3: hold("Right", 0.3)
        Q.set_view("classic", settle=0.3); shot(f"army{k}_c")
        Q.set_view("third", settle=0.3)
        k += 1; A.save_log()
    set_ini("force_wanted", -1)

def drive_away(label, secs):
    """Up held the whole time; stuck (under a block in 1.5 s) -> back off and turn; a frame
    every 0.4 s, a look back (the chase camera swings round) now and then"""
    t0 = time.time(); n = 0; last = D.wait_state(); lt = time.time(); turn = 0
    D.xdo("keydown", "Up")
    while time.time() - t0 < secs:
        time.sleep(0.4); shot(f"{label}_{n:03d}"); n += 1
        if time.time() - lt > 1.5:
            s = D.wait_state()
            if s and last and math.hypot(s["x"] - last["x"], s["y"] - last["y"]) < 1.0:
                D.xdo("keyup", "Up"); D.xdo("keydown", "Down"); time.sleep(0.8)
                hold("Left" if turn % 2 else "Right", 0.5); D.xdo("keyup", "Down"); D.xdo("keydown", "Up"); turn += 1
            last, lt = s, time.time()
        if n % 15 == 0:
            w = A.mission(); st = D.wait_state()
            say(f"MARK {label} t={time.time() - t0:.0f} wanted {w[0]} health {w[1]} driving {st['driving']} at {st['x']:.1f},{st['y']:.1f}")
            A.save_log()
            if not st["driving"]: break
    D.xdo("keyup", "Up")

def gunfire():
    stars = int(os.environ.get("A33_STARS", "5"))
    T.warp(164.5, 147.6, 2, why="street")
    time.sleep(2.0)
    for attempt in range(3):
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(4.0)
        if D.wait_state()["driving"]: break
    say("MARK in a car:", D.wait_state()["driving"])
    Q.set_view("third", settle=1.0)
    set_ini("force_wanted", stars)
    time.sleep(8.0)
    drive_away("g_drive", float(os.environ.get("A33_DRIVE_SECS", "70")))
    # hold position on foot with the machine gun, shooting at the pursuers
    T.leave_car() if D.wait_state()["driving"] else None
    A.collect(166.5, 140.5, 2, "machine_gun")
    T.warp(159.5, 139.5, 2, why="plaza, holding position"); Q.set_view("third", settle=0.6)
    t0 = time.time(); n = 0
    while time.time() - t0 < float(os.environ.get("A33_HOLD_SECS", "70")):
        if A.mission()[2] == "none":
            A.collect(166.5, 140.5, 2, "machine_gun"); Q.set_view("third", settle=0.5)
        cs = find((12, 52, 13, 54))   # cop car, SWAT van, FBI car, tank
        if cs:
            s0 = D.wait_state()
            c = min(cs, key=lambda c: (c[1] - s0["x"]) ** 2 + (c[2] - s0["y"]) ** 2)
            A.face(c[1], c[2], tries=3)
        A.fire(f"g_fire_{n:03d}", secs=0.8, every=0.2)
        hold("Left", 0.6); shot(f"g_look_{n:03d}"); hold("Right", 0.6)
        for i in range(4): shot(f"g_hold_{n:03d}_{i}"); time.sleep(0.25)
        n += 1
        if n % 3 == 0:
            w = A.mission(); say(f"MARK hold t={time.time() - t0:.0f} wanted {w[0]} health {w[1]} weapon {w[2]}"); A.save_log()
        if n == 8: Q.set_view("first", settle=0.4)
        if n == 12: Q.set_view("third", settle=0.4)
    set_ini("force_wanted", -1)

def train():
    """the station at 99.5,97.7, level 3: train 2 (heading +y) stops there; the platform is
    beside the track. Wait for it, frames as it comes in, stands and leaves."""
    px, py = float(os.environ.get("A33_TRAIN_X", "98.5")), float(os.environ.get("A33_TRAIN_Y", "93.0"))
    s = T.warp(px, py, 3, why="station platform of the elevated line")
    say(f"MARK on the platform at {s['x']:.2f},{s['y']:.2f} z={s['z']:.2f}")
    fx_, fy_ = (float(v) for v in os.environ.get("A33_TRAIN_FACE", "99.5,80.0").split(","))
    A.face(fx_, fy_)   # default down the line, the way the train comes from (west platform, pavement x=98 y 90-97)
    Q.set_view("third", settle=0.5); shot("tr_platform_t"); Q.set_view("first", settle=0.4); shot("tr_platform_f")
    t0 = time.time(); k = 0; last = None; seen_near = 0
    while time.time() - t0 < float(os.environ.get("A33_TRAIN_SECS", "240")):
        tr = sorted(find((59, 60, 61)), key=lambda v: (v[1] - 99.5) ** 2 + (v[2] - 97.7) ** 2)
        near = tr and math.hypot(tr[0][1] - 99.5, tr[0][2] - 97.7) < 30 and abs(tr[0][3] - 3.0) < 1.6
        if near:
            if not seen_near: say(f"MARK train near: {tr[0]}")
            seen_near += 1
            view = "third" if (seen_near // 10) % 2 == 0 else "first"
            Q.set_view(view, settle=0.0)
            shot(f"tr_{view[0]}_{k:03d}"); k += 1; time.sleep(0.25)
            if seen_near % 12 == 0: Q.set_view("classic", settle=0.2); shot(f"tr_c_{k:03d}"); k += 1
        else:
            if seen_near > 30: break
            time.sleep(1.0)
            if int(time.time() - t0) % 20 == 0:
                s = D.wait_state(); say(f"MARK waiting t={time.time() - t0:.0f} at {s['x']:.1f},{s['y']:.1f} z={s['z']:.2f} trains {[(v[1], v[2], v[3]) for v in tr[:2]]}")
                A.save_log()
    A.save_log()

def firetruck():
    vs = find((17,), driven=0) or find((17,))
    if not vs: say("MARK no fire truck listed"); return
    m, x, y, z, fx, fy, d = vs[0]
    wx, wy = x + fx * 1.8 + fy * 1.2, y + fy * 1.8 - fx * 1.2
    s = T.warp(round(wx, 2), round(wy, 2), int(round(z)), why="fire truck")
    say(f"MARK fire truck at {x:.2f},{y:.2f},{z:.2f}; player {s['x']:.2f},{s['y']:.2f}")
    A.face(x, y); Q.set_view("third", settle=0.5); frames("ft_parked_t", 2)
    tap("Return", 0.3)
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < 10 and not s["driving"]:
        time.sleep(0.5); s = D.wait_state()
    say(f"MARK fire truck driving={s['driving']} {A.mission()}")
    if not s["driving"]: return
    time.sleep(1.0); frames("ft_in_t", 2)
    tap("Tab", 0.2); time.sleep(0.5)   # the special key: the siren on an emergency vehicle
    for k in range(10):
        D.xdo("keydown", "Up"); time.sleep(1.4); shot(f"ft_drive_{k:02d}"); D.xdo("keyup", "Up")
        if k % 3 == 2: hold("Left", 0.4)
        A.fire(f"ft_cannon_{k:02d}", secs=0.9, every=0.3)
        if k == 6: Q.set_view("first", settle=0.4)
        if k == 8: Q.set_view("classic", settle=0.4)
    Q.set_view("third", settle=0.4); frames("ft_end_t", 3)
    A.save_log()

def ambulance():
    """an ambulance comes to the dead: wanted 6 for the carnage (A33_AMB_STARS), released once
    one is listed; when it stands still (two vehicle lines within 0.3 block: it stopped at the
    bodies) warp two blocks to its side and frame it (beacons); otherwise frame it ahead of it"""
    T.warp(164.5, 147.6, 2, why="street for the carnage"); Q.set_view("third", settle=0.5)
    set_ini("force_wanted", int(os.environ.get("A33_AMB_STARS", "6")))
    t0 = time.time(); k = 0; last = {}; released = False
    while time.time() - t0 < float(os.environ.get("A33_AMB_SECS", "200")) and k < 4:
        rv = find((34,))
        if not rv: time.sleep(1.5); continue
        if not released and time.time() - t0 > 25: set_ini("force_wanted", -1); released = True
        m, x, y, z, fx, fy, d = rv[0]
        stopped = any(math.hypot(px - x, py - y) < 0.3 for (px, py) in last.values())
        last = {0: (x, y)}
        if not stopped and k > 0: time.sleep(1.0); continue
        if stopped: wx, wy = x - fy * 2.2 + fx * 0.8, y + fx * 2.2 + fy * 0.8
        else: wx, wy = x + fx * 3.5 - fy * 1.3, y + fy * 3.5 + fx * 1.3
        say(f"MARK ambulance at {x:.1f},{y:.1f},{z:.1f} heading {fx:.2f},{fy:.2f} driven {d} stopped {stopped}: warp {wx:.1f},{wy:.1f}")
        if D.wait_state()["driving"]: T.leave_car()
        T.warp(round(wx, 1), round(wy, 1), int(round(z)), why="beside the ambulance")
        A.face(x, y); Q.set_view("third", settle=0.3)
        for i in range(12):
            shot(f"amb{k}_{i:02d}"); time.sleep(0.3)
            r2 = find((34,), near=(x, y))
            if r2 and i % 4 == 0: A.face(r2[0][1], r2[0][2], tries=1)
            if i == 8: Q.set_view("first", settle=0.2)
        Q.set_view("third", settle=0.2)
        k += 1; A.save_log(); time.sleep(1.0)
    set_ini("force_wanted", -1)

s = Q.start("a33_probe")
time.sleep(2.0)
for item in os.environ.get("A33_ITEMS", "types").split():
    say("MARK item", item, "vehicles", sorted(set(v[0] for v in vehicles())))
    {"types": types, "army": army, "gunfire": gunfire, "train": train, "firetruck": firetruck, "ambulance": ambulance}[item]()
A.finish()
