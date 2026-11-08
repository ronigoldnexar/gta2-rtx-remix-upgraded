#!/usr/bin/env python3
"""CAMERA-POLISH-2 probe: chase framing of long/tall vehicles, the first-person
eye per vehicle, and camera robustness (walls, entering/leaving, explosions,
WASTED). Frames are named by the item and the seconds since its event, so a run
on the old stage and one on the new give pairs at the same timestamps.

CP_ITEMS (in order, default "firetruck car wall reverse explode explode_fp leave"):
  firetruck  the Downtown kill-frenzy fire truck (5.5,26.5): parked, Return, frames
             every 0.4 s for the first 3.2 s at the wheel while it drives, then first person
  car        the F10 scene car (scene_xy): the same frames on a sedan
  model      the F10 scene vehicle when the run sets GTA2DX9_SCENE_MODELS (bus, truck...)
  wall       on foot in the spawn plaza: walk backward into the building behind him
  reverse    at the wheel of the scene car: a quarter turn, then reverse across the
             road into the buildings
  explode    third person at the wheel: [devtools] set_car_damage=31995, reverse into a wall (the
             knock blows it up), frames to WASTED
  explode_fp the same in first person
  leave      third person: set it alight, leave at once, stand beside it (needs a knock: unused)
  busted     on foot, health 3 and three stars ([devtools] set_player_health, force_wanted):
             frames until the police put him down, then WASTED/BUSTED; busted_fp in first person
Run with GTA2DX9_SCENE_NO_CAR=1 (warps go to the point; F9 then takes the nearest parked
car's door; the model item needs GTA2DX9_SCENE_NO_CAR=0 and GTA2DX9_SCENE_MODELS),
GTA2DX9_LOG_CAMERA=1, GTA2DX9_LOG_VEHICLES=1 and the INI_SED setting
scene_key=F10, warp_key=F9, nav_map=0 (tank controls: Down walks backward)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

LOG = D.LOG
VIEW = re.compile(r"\] view: (Classic \(top down\)|Third person|First person)\s*$")


def current_view():
    try:
        t = open(LOG, "rb").read().decode("latin-1")
    except OSError:
        return "classic"
    found = "classic"
    for line in t.splitlines():
        m = VIEW.search(line)
        if not m: continue
        found = {"Classic (top down)": "classic", "Third person": "third", "First person": "first"}[m.group(1)]
    return found


def set_view(target, settle=1.0):
    for _ in range(4):
        if current_view() == target:
            time.sleep(settle); return True
        tap("v", 0.25); time.sleep(0.7)
    say("set_view: could not reach", target); return False


Q.current_view = current_view   # tour_lib's warp uses Q.set_view
Q.set_view = set_view

VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")


def vehicles():
    last = None
    for line in Q.log_text(400000).splitlines():
        if "] vehicles:" in line: last = line
    return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]


LAST = [None]


def settle(minimum=3.0):
    """after a warp the game's own camera travels to the player at about ten blocks a second,
    and the game draws no car sprites at all until it is there (runs cp2_new7/8: no car body
    for 14-21 s after a 150-190 block warp, the driven truck included); wait for it"""
    s = D.wait_state()
    d = 0.0
    if LAST[0] is not None:
        d = ((s["x"] - LAST[0][0]) ** 2 + (s["y"] - LAST[0][1]) ** 2) ** 0.5
    LAST[0] = (s["x"], s["y"])
    secs = max(minimum, min(32.0, d / 8.0 + 3.0))
    say(f"MARK settle {secs:.1f} s after a {d:.0f}-block move")
    time.sleep(secs)


def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK {key}={val}")


def timed(label, secs, every=0.4, key=None):
    """frames named label_<tenths of a second since now>, holding `key` meanwhile"""
    t0 = time.time()
    if key: D.xdo("keydown", key)
    while time.time() - t0 < secs:
        shot(f"{label}_{int(round((time.time() - t0) * 10)):03d}")
        dt = every - ((time.time() - t0) % every)
        time.sleep(max(0.02, dt))
    if key: D.xdo("keyup", key)


def wait_driving(want=True, secs=10):
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < secs and bool(s["driving"]) != want:
        time.sleep(0.25); s = D.wait_state()
    return s


def enter_and_frame(tag):
    """third person beside the vehicle, Return, frames from the moment he is at the wheel"""
    set_view("third", settle=1.0); shot(f"{tag}_parked")
    tap("Return", 0.3)
    s = wait_driving(True, 10)
    say(f"MARK {tag} driving={s['driving']} model={s.get('cmodel')}")
    if not s["driving"]: return False
    timed(f"{tag}_enter_t", 1.6, 0.4)            # standing, the first frames at the wheel
    timed(f"{tag}_drive_t", 3.2, 0.4, key="Up")  # the first seconds driving
    D.xdo("keydown", "Down"); time.sleep(0.6); D.xdo("keyup", "Down"); time.sleep(0.6)
    set_view("first", settle=0.6)
    timed(f"{tag}_fp", 1.2, 0.4)
    timed(f"{tag}_fp_drive", 1.6, 0.4, key="Up")
    hold("Left", 0.5); shot(f"{tag}_fp_turn")
    set_view("classic", settle=0.5); set_view("third", settle=0.8)
    shot(f"{tag}_end_t")
    # out and back in: no jump
    tap("Return", 0.3); timed(f"{tag}_exit_t", 2.0, 0.25)
    wait_driving(False, 6)
    tap("Return", 0.3); timed(f"{tag}_reenter_t", 2.0, 0.25)
    return True


def firetruck():
    vs = [v for v in vehicles() if v[0] == 17]
    if not vs: say("MARK no fire truck listed"); return
    m, x, y, z, fx, fy, d = vs[0]
    wx, wy = x + fx * 1.8 + fy * 1.2, y + fy * 1.8 - fx * 1.2
    T.warp(round(wx, 2), round(wy, 2), int(round(z)), why="fire truck")
    settle()
    A.face(x, y)
    enter_and_frame("ft")
    T.ensure_on_foot()


def to_car(why):
    """to the scene point (GTA2DX9_SCENE_NO_CAR=1), then F9: the nearest parked car's driver's door"""
    T.warp(164.5, 149.5, 2, why=why)
    tap("F9", 0.3); time.sleep(1.5)
    settle()
    s = D.wait_state(); say(f"MARK F9 -> {Q.words(s)} parked d={s['pd']:.2f}")


def get_car(why):
    to_car(why)
    set_view("third", settle=0.5)
    for attempt in range(3):
        tap("Return", 0.3)
        s = wait_driving(True, 8)
        if s["driving"]: return True
        tap("F9", 0.3); time.sleep(1.5)
    say(f"MARK {why}: not in a car"); return False


def busted(view="third", tag="bust"):
    """on foot in the street, his health at 3 and three stars: the police come, a shot or a
    punch puts him down (WASTED or BUSTED); frames every second"""
    T.warp(164.5, 147.6, 2, why=f"street for the police ({view})")
    settle()
    set_view(view, settle=0.6)
    set_ini("set_player_health", 3); set_ini("force_wanted", 3)
    t0 = time.time(); k = 0; down_at = None
    while time.time() - t0 < 50:
        shot(f"{tag}_{k:02d}"); k += 1
        s = D.wait_state()
        if s and s["state"] in (8, 9) and down_at is None:
            down_at = time.time(); say(f"MARK {tag} down: {Q.words(s)}")
            timed(f"{tag}_down", 8.0, 0.4)
            break
        time.sleep(0.6)
    set_ini("force_wanted", -1); set_ini("set_player_health", -1)
    timed(f"{tag}_after", 6.0, 0.6)


def car():
    to_car("scene car")
    enter_and_frame("car")
    T.ensure_on_foot()


def model():
    T.warp(164.5, 149.5, 2, why="scene model")
    settle()
    enter_and_frame("mdl")
    T.ensure_on_foot()


def wall():
    T.warp(159.5, 139.5, 2, why="plaza")
    settle()
    set_view("third", settle=0.5)
    s = D.wait_state()
    # face south (away from the building north of the spawn), so the camera stands between him and it
    A.face(s["x"], s["y"] + 6.0)
    set_view("classic", settle=0.4); set_view("third", settle=1.2)
    shot("wall_t_start")
    timed("wall_t_back", 3.2, 0.4, key="Down")
    timed("wall_t_held", 1.2, 0.4, key="Down")
    set_view("first", settle=0.8); shot("wall_f_against")
    set_view("classic", settle=0.4)


def reverse():
    if not get_car("scene car for reversing"): return
    D.xdo("keydown", "Up"); hold("Left", 0.9); D.xdo("keyup", "Up"); time.sleep(0.8)
    shot("rev_t_start")
    timed("rev_t", 4.0, 0.4, key="Down")
    timed("rev_t_held", 1.6, 0.4, key="Down")
    set_view("first", settle=0.6); shot("rev_f_held")
    set_view("classic", settle=0.4); set_view("third", settle=0.6)
    T.ensure_on_foot()


def explode(view="third", tag="exp"):
    if not get_car(f"scene car to blow up ({view})"): return
    set_view(view, settle=0.6)
    # The word alone does not set the car alight (the game's damage routine does that when a
    # hit crosses 16000); one point short of 32000, the next knock blows it up: reverse into
    # whatever is behind.
    set_ini("set_car_damage", 31995)
    time.sleep(0.8)
    timed(f"{tag}", 5.0, 0.5, key="Down")
    timed(f"{tag}_post", 9.0, 0.5)
    set_ini("set_car_damage", -1)
    s = D.wait_state(); say(f"MARK {tag} after: {Q.words(s)}")
    time.sleep(4.0); shot(f"{tag}_after")


def leave():
    to_car("scene car to leave burning")
    set_view("third", settle=0.5); tap("Return", 0.3)
    s = wait_driving(True, 10)
    if not s["driving"]: say("MARK leave: not in the car"); return
    set_ini("set_car_damage", 31750)
    time.sleep(0.6); tap("Return", 0.3)
    timed("leave_t", 12.0, 0.5)
    set_ini("set_car_damage", -1)


ITEMS = {"firetruck": firetruck, "car": car, "model": model, "wall": wall, "reverse": reverse,
         "explode": lambda: explode("third", "exp_t"), "explode_fp": lambda: explode("first", "exp_f"), "leave": leave,
         "busted": lambda: busted("third", "bust_t"), "busted_fp": lambda: busted("first", "bust_f")}
D.wait_state(40); D.calibrate_turn()
s0 = D.wait_state(); LAST[0] = (s0["x"], s0["y"])
for item in os.environ.get("CP_ITEMS", "firetruck car wall reverse explode explode_fp leave").split():
    say(f"MARK item {item}")
    try:
        ITEMS[item]()
    except Exception as e:
        say(f"MARK item {item} failed: {e!r}")
    A.save_log()
A.finish()
