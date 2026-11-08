#!/usr/bin/env python3
"""Remix look-development take, run after remix_keys_lib.sh has the level up:
classic, the chase view and first person at the spawn; then (CAR_MODELS) a
parked car brought to SCENE_XY with the player at its door, dressed by
[devtools] force_car_model as each listed model in turn and orbited by the
chase camera, with a first-person look at each; then (DRIVE_XY) that car
driven through the chase view and the driver's seat (exposure while moving);
out, and a first-person look round. Every step is a line in /out/marks.txt;
frames are cut from game.mp4 (single x11grab frames of the Remix window are black).
Env: DISTRICT (wil|ste|bil, the map the run loaded), SCENE_XY (x,y[,level]),
CAR_MODELS (comma list), DRIVE_XY (x,y), SCENE_KEY (F11).

With PART set, the REMIX-3 take instead (same key script, keys_remix_showcase.sh;
runs remix3_a..i, docs/remix-materials.md):
REMIX-3 take, run after remix_keys_lib.sh has the level up (Downtown, clock
paused): one session that shows the cars, the driver's seat and the lights by
day, at dusk and at night, using [devtools] set_hour_tenths to move the clock.
Every step is a line in /out/marks.txt; frames are cut from game.mp4.
  PART=cars    the scene car dressed by force_car_model as each of CAR_MODELS,
               orbited by the chase camera, at 14:00, at dusk (DUSK) and at night
               (sirens on), then the plaza at night (GTA2DX9_LOG_REMIX_LIGHTS=1
               names the strongest lights), the driver's seat by night and day
  PART=lights  the booth and the traffic lights at night, the machine gun's
               muzzle flash, a rocket into a parked car (explosion, fire),
               then three stars (police light bars)
  PART=fb      the runtime's fallback light against ours, toggled live at night
               and by day ([devtools] remix_config, remix_lights_off); FB_KEEP
               is left set for the rest of the take
  PART=nightcars  the car sweep at night (sirens on) and at dusk, the plaza
  PART=sedan   the parked Schmidt at 187.5,196.9 (warp key F9): the driver's seat
               at night and by day
  PART=exposure  the auto-exposure cap, the moonlight and the atmosphere's light
               pushed live at the night plaza, then two night sweeps
  PART=debuglights  the runtime's light debug view over the night plaza
  PART=lights3 the booth and traffic lights walked up to (props_check's walk), the
               machine gun's muzzle flash, three stars
  PART=truck3  (GTA2DX9_SCENE_MODELS=17) the fire truck by day, at dusk, its
               beacons at night, the driver's seat
  PART=ab2     what lights the street at night: our lights, the atmosphere's
               sun/moon light, the game's D3D9 lights, the auto exposure, in turn
  PART=truck2  with GTA2DX9_SCENE_MODELS=17 (every scene warp then goes to the
               nearest fire truck): the driver's seat by day and at night
  PART=lights2 the booth and traffic lights at night (orbited), the machine
               gun's muzzle flash, three stars (police light bars)
PART may list several, comma separated."""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, view, warp, drive

if os.environ.get("PART"):
    import a3_lib as A

    def ini_set(key, val):
        t = open(T.INI, encoding="latin-1").read()
        if re.search(rf"(?m)^{key}=", t):
            t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
        else:
            t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
        open(T.INI, "w", encoding="latin-1").write(t)

    def hour(h, settle=4.0):
        ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.1f}")

    def look(tag, key="Left", steps=2, secs=0.5):
        mark(f"{tag}_0"); time.sleep(1.0)
        for i in range(steps):
            hold(key, secs); time.sleep(1.3); mark(f"{tag}_{i + 1}")

    def scene_car():
        v = [float(c) for c in os.environ.get("SCENE_XY", "164.5,149.5").split(",")]
        s = warp(v[0], v[1], int(v[2]) if len(v) > 2 else None, why="the scene car")
        for attempt in range(3):
            last = (T.devtools_lines() or [""])[-1]
            if "no parked car" not in last: break
            s = D.wait_state()
            if not s or not s.get("parked"): break
            s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
        return s

    def sweep(tag, models):
        view("third"); time.sleep(1.0)
        for n in models:
            ini_set("force_car_model", n); time.sleep(2.6)
            look(f"{tag}_car_{n:03d}", steps=3, secs=0.45)
        ini_set("force_car_model", -1); time.sleep(1.2)

    def driver_seat(tag):
        s = T.get_in_scene_car()
        if not (s and s["driving"]):
            mark(f"{tag}: could not get in"); return False
        Q.set_view("first", settle=2.0); mark(f"{tag}_fp_0")
        hold("Left", 0.3); time.sleep(1.2); mark(f"{tag}_fp_1")
        hold("Right", 0.6); time.sleep(1.2); mark(f"{tag}_fp_2")
        D.xdo("keydown", "Up"); time.sleep(1.2); mark(f"{tag}_fp_move"); time.sleep(0.6); D.xdo("keyup", "Up")
        time.sleep(1.5); mark(f"{tag}_fp_3")
        Q.set_view("third", settle=1.5); mark(f"{tag}_chase")
        return True

    VEH = re.compile(r"\[m(\d+) (-?[\d.]+),(-?[\d.]+),(-?[\d.]+) f(-?[\d.]+),(-?[\d.]+) d(\d) ([0-9A-Fa-fx]+)\]")
    def vehicles():
        last = None
        for line in Q.log_text(400000).splitlines():
            if "] vehicles:" in line: last = line
        return [(int(m[0]), float(m[1]), float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[6])) for m in VEH.findall(last or "")]

    def cfg(text):
        ini_set("remix_config", text); time.sleep(3.0)

    def in_car(secs=10):
        t0 = time.time(); s = D.wait_state()
        while time.time() - t0 < secs and not s["driving"]:
            time.sleep(0.3); s = D.wait_state()
        return s

    parts = [p.strip() for p in os.environ.get("PART", "cars").split(",")]
    mark("script start")
    s = D.wait_state(); say("start:", T.words(s))
    time.sleep(2); mark("classic_spawn")
    models = [int(m) for m in os.environ.get("CAR_MODELS", "12,56,34,11,18,31").split(",") if m.strip()]
    dusk = float(os.environ.get("DUSK", "19.2")); night = float(os.environ.get("NIGHT", "22.5"))

    if "cars" in parts:
        hour(14.0)
        scene_car()
        sweep("day", models)
        hour(dusk); sweep("dusk", models[:3])
        hour(night); ini_set("force_sirens", 1); sweep("night", models); ini_set("force_sirens", 0)
        view("third"); look("night_plaza_third", steps=3, secs=0.6)
        view("first"); look("night_plaza_first", steps=3, secs=0.6)
        Q.set_view("third", settle=1.0)
        s = scene_car(); driver_seat("night_seat")
        hour(14.0); driver_seat("day_seat") if not (D.wait_state() or {}).get("driving") else None
        if (D.wait_state() or {}).get("driving"):
            Q.set_view("first", settle=2.0); mark("day_seat_fp_0"); hold("Left", 0.3); time.sleep(1.2); mark("day_seat_fp_1")
            Q.set_view("third", settle=1.0)
        T.leave_car()

    if "lights" in parts:
        hour(night)
        # the booth (PROPS-2: 158.5,137.5, looked at from 158.5,141.5) and the traffic lights (171,117)
        warp(158.5, 141.5, 2, why="near the booth"); A.face(158.5, 137.5)
        view("third"); look("booth_third", steps=1); view("first"); look("booth_first", steps=1)
        warp(171.0, 121.5, 2, why="near the traffic lights"); A.face(171.0, 117.1)
        view("third"); look("traffic_third", steps=1); view("first"); look("traffic_first", steps=1)
        hour(dusk); view("third"); look("traffic_dusk_third", steps=1)
        hour(night)
        # the machine gun (166.5,140.5) and the rocket launcher (154.5,129.5)
        A.collect(166.5, 140.5, 2, "machine_gun"); A.collect(154.5, 129.5, 2, "rocket_launcher")
        s = scene_car()
        cx, cy = s.get("cx", s["x"]), s.get("cy", s["y"])
        # back off from the car, face it
        D.goto(s["x"] + (s["x"] - cx) * 3.0, s["y"] + (s["y"] - cy) * 3.0, tol=0.5, limit=6)
        A.face(cx, cy); view("third")
        for i in range(6):
            if A.weapon_name().startswith("machine") or A.weapon_name() == "smg": break
            tap("z", 0.2); time.sleep(0.6)
        mark(f"weapon {A.weapon_name()}")
        D.xdo("keydown", "Control_L")
        for i in range(5): time.sleep(0.25); mark(f"muzzle_third_{i}")
        D.xdo("keyup", "Control_L")
        Q.set_view("first", settle=1.0)
        D.xdo("keydown", "Control_L")
        for i in range(4): time.sleep(0.25); mark(f"muzzle_first_{i}")
        D.xdo("keyup", "Control_L")
        Q.set_view("third", settle=1.0)
        for i in range(8):
            if A.weapon_name().startswith("rocket"): break
            tap("z", 0.2); time.sleep(0.6)
        mark(f"weapon {A.weapon_name()}")
        A.face(cx, cy)
        tap("Control_L", 0.2); mark("rocket fired")
        for i in range(12): time.sleep(0.4); mark(f"explosion_{i:02d}")
        hold("Down", 0.6)
        for i in range(6): time.sleep(1.0); mark(f"fire_{i}")
        # the police: three stars kept
        ini_set("force_wanted", 3); mark("wanted 3")
        for i in range(14): time.sleep(3.0); mark(f"police_{i:02d}")
        ini_set("force_wanted", -1)

    if "fb" in parts:
        # the runtime's fallback light (rtx.fallbackLightMode 1: a distant light whenever a
        # frame has no lights of its own) against our lights, at night and by day
        hour(night); s = scene_car(); view("third"); time.sleep(2.0); mark("fb_night_base")
        ini_set("remix_config", "rtx.fallbackLightMode=0"); time.sleep(4.5); mark("fb_night_mode0")
        ini_set("remix_lights_off", 1); time.sleep(4.5); mark("fb_night_mode0_lightsoff")
        ini_set("remix_config", "rtx.fallbackLightMode=1"); time.sleep(4.5); mark("fb_night_mode1_lightsoff")
        ini_set("remix_lights_off", 0); time.sleep(4.5); mark("fb_night_mode1_back")
        view("first"); time.sleep(1.5); mark("fb_night_mode1_first")
        ini_set("remix_config", "rtx.fallbackLightMode=0"); time.sleep(4.5); mark("fb_night_mode0_first")
        view("third")
        hour(14.0); time.sleep(1.0); mark("fb_day_mode0")
        ini_set("remix_config", "rtx.fallbackLightMode=1"); time.sleep(4.5); mark("fb_day_mode1")
        ini_set("remix_config", os.environ.get("FB_KEEP", "rtx.fallbackLightMode=0")); time.sleep(4.5); mark("fb_keep")

    if "nightcars" in parts:
        hour(night); scene_car(); ini_set("force_sirens", 1)
        view("third"); time.sleep(1.0)
        for n in models:
            ini_set("force_car_model", n); time.sleep(2.6)
            look(f"night_car_{n:03d}", steps=3, secs=0.3)
        ini_set("force_sirens", 0)
        hour(dusk)
        for n in models[:4]:
            ini_set("force_car_model", n); time.sleep(2.6)
            look(f"dusk_car_{n:03d}", steps=2, secs=0.3)
        ini_set("force_car_model", -1); time.sleep(1.2)
        hour(night); view("third"); look("night_plaza_third", steps=3, secs=0.6)
        view("first"); look("night_plaza_first", steps=3, secs=0.6); view("third")

    if "sedan" in parts:
        # the Schmidt run remix3_b found parked by 187.5,196.9: there, then the warp key (the
        # nearest parked car's door)
        hour(night); warp(187.5, 194.5, 2, why="toward the parked Schmidt")
        tap("F9", 0.3); time.sleep(2.0); s = D.wait_state(); mark(f"F9 -> {T.words(s)}")
        view("third"); time.sleep(1.0); mark("sedan_outside")
        for attempt in range(3):
            tap("Return", 0.3); s = in_car(8)
            if s["driving"]: break
            tap("F9", 0.3); time.sleep(1.5)
        mark(f"sedan driving={s['driving']} model={s.get('cmodel')}")
        if s["driving"]:
            Q.set_view("first", settle=2.0); mark("sedan_night_fp_0")
            hold("Left", 0.3); time.sleep(1.2); mark("sedan_night_fp_1")
            D.xdo("keydown", "Up"); time.sleep(1.2); mark("sedan_night_fp_move"); time.sleep(0.5); D.xdo("keyup", "Up")
            time.sleep(1.5); mark("sedan_night_fp_2")
            hour(14.0); time.sleep(1.0); mark("sedan_day_fp_0")
            hold("Right", 0.3); time.sleep(1.2); mark("sedan_day_fp_1")
            D.xdo("keydown", "Up"); time.sleep(1.2); mark("sedan_day_fp_move"); time.sleep(0.5); D.xdo("keyup", "Up")
            time.sleep(1.5); mark("sedan_day_fp_2")
            Q.set_view("third", settle=1.5); mark("sedan_day_chase")
            T.leave_car()

    if "exposure" in parts:
        # the night plaza is lifted to daylight by the auto exposure (run remix3_c: with the
        # exposure off the same street is dark with lamp pools; remix3_d: neither the
        # runtime's fallback light nor our lights make the difference): the exposure cap,
        # the moonlight and the atmosphere's sun/moon light in turn
        hour(night); scene_car(); view("third"); time.sleep(2.0); mark("exp_base")
        for name, conf in [("max1.5", "rtx.autoExposure.maxExposure=1.5"), ("max1.0", "rtx.autoExposure.maxExposure=1.0"),
                           ("max0.6", "rtx.autoExposure.maxExposure=0.6"),
                           ("max2.5_moon0.5", "rtx.autoExposure.maxExposure=2.5|rtx.atmosphere.surfaceMoonBrightness=0.5"),
                           ("max2.5_dir0", "rtx.atmosphere.surfaceMoonBrightness=3|rtx.atmosphere.directionalLightRadianceScale=0"),
                           ("back", "rtx.atmosphere.directionalLightRadianceScale=1")]:
            ini_set("remix_config", conf); time.sleep(5.0); mark(f"exp_{name}")
            view("first"); time.sleep(2.0); mark(f"exp_{name}_first"); view("third")
        for tag, conf in [("A", os.environ.get("NIGHT_CFG_A", "rtx.autoExposure.maxExposure=1.0")),
                          ("B", os.environ.get("NIGHT_CFG_B", "rtx.autoExposure.maxExposure=0.6"))]:
            ini_set("remix_config", conf); ini_set("force_sirens", 1); time.sleep(4.0); mark(f"cfg {tag} {conf}")
            for n in models:
                ini_set("force_car_model", n); time.sleep(2.6)
                look(f"n{tag}_car_{n:03d}", steps=2, secs=0.3)
            ini_set("force_car_model", -1); ini_set("force_sirens", 0); time.sleep(1.5)
            view("third"); look(f"n{tag}_plaza_third", steps=2, secs=0.6)
            view("first"); look(f"n{tag}_plaza_first", steps=2, secs=0.6); view("third")

    if "lights2" in parts:
        hour(night)
        warp(159.5, 140.5, 2, why="the booth (158.5,137.5)")
        view("third"); look("booth_third", steps=4, secs=0.5); view("first"); look("booth_first", steps=4, secs=0.5)
        warp(171.0, 123.0, 2, why="the traffic lights (171,117)")
        view("third"); look("traffic_third", steps=4, secs=0.5); view("first"); look("traffic_first", steps=4, secs=0.5)
        hour(dusk); view("third"); look("traffic_dusk_third", steps=2, secs=0.5)
        hour(night)
        A.collect(166.5, 140.5, 2, "machine_gun")
        warp(159.5, 139.5, 2, why="the plaza (shots)")
        view("third"); mark(f"weapon {A.weapon_name()}")
        D.xdo("keydown", "Control_L")
        for i in range(6): time.sleep(0.2); mark(f"muzzle_third_{i}")
        D.xdo("keyup", "Control_L")
        Q.set_view("first", settle=1.0)
        D.xdo("keydown", "Control_L")
        for i in range(5): time.sleep(0.2); mark(f"muzzle_first_{i}")
        D.xdo("keyup", "Control_L")
        Q.set_view("third", settle=1.0)
        warp(164.5, 147.6, 2, why="the street for the police")
        ini_set("force_wanted", 3); mark("wanted 3")
        for i in range(16):
            time.sleep(2.5); mark(f"police_{i:02d}")
            if i == 7: hold("Left", 0.6)
        ini_set("force_wanted", -1)

    def approach(tx, ty, tol, tries=16):
        """props_check.py's walk: in the classic view (the game's tank keys) turn toward
        (tx,ty) in short pieces and step until within tol, so he ends facing it"""
        s = D.wait_state()
        for _ in range(tries):
            d = math.hypot(tx - s["x"], ty - s["y"]); a = D.angle_to(s, tx, ty)
            if abs(a) > 0.25:
                key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.35)
                if d > tol + 0.3: D.hold("Up", 0.15); time.sleep(0.4)
            elif d > tol:
                D.hold("Up", min(1.5, max(0.15, (d - tol) / 1.9))); time.sleep(0.5)
            else:
                break
            s = D.wait_state()
        return s

    if "lights3" in parts:
        hour(night)
        Q.set_view("classic", settle=1.0); D.calibrate_turn()
        for name, (tx, ty, fx, fy, tol) in [("booth", (158.5, 137.5, 158.5, 141.5, 1.6)), ("traffic", (171.0, 117.1, 171.0, 123.0, 2.5))]:
            warp(fx, fy, 2, why=f"near the {name}"); s = approach(tx, ty, tol)
            mark(f"{name}: at {s['x']:.2f},{s['y']:.2f} facing {s['fx']:.2f},{s['fy']:.2f}")
            view("third"); time.sleep(1.0); mark(f"{name}3_third_0")
            hold("Left", 0.3); time.sleep(1.2); mark(f"{name}3_third_1")
            view("first"); time.sleep(1.0); mark(f"{name}3_first_0")
            hold("Right", 0.4); time.sleep(1.2); mark(f"{name}3_first_1")
            if name == "traffic":
                hour(dusk); time.sleep(1.0); mark("traffic3_dusk_first"); view("third"); time.sleep(1.0); mark("traffic3_dusk_third"); hour(night)
        A.collect(166.5, 140.5, 2, "machine_gun")
        warp(159.5, 139.5, 2, why="the plaza (shots)"); view("third"); time.sleep(1.0); mark(f"weapon {A.weapon_name()}")
        D.xdo("keydown", "Control_L")
        for i in range(10): time.sleep(0.25); mark(f"muzzle3_third_{i}")
        D.xdo("keyup", "Control_L"); Q.set_view("first", settle=1.0)
        D.xdo("keydown", "Control_L")
        for i in range(10): time.sleep(0.25); mark(f"muzzle3_first_{i}")
        D.xdo("keyup", "Control_L"); Q.set_view("third", settle=1.0)
        warp(164.5, 147.6, 2, why="the street for the police"); view("third")
        ini_set("force_wanted", 3); mark("wanted 3")
        for i in range(18):
            time.sleep(2.5); mark(f"police3_{i:02d}")
            if i in (6, 12): hold("Left", 0.6)
        ini_set("force_wanted", -1)

    if "debuglights" in parts:
        # the runtime's own light debug view over the night plaza: every light it has, ours
        # and any it made itself, drawn where it is
        hour(night); scene_car(); view("third"); time.sleep(2.0); mark("dbg_base")
        ini_set("remix_config", "rtx.lights.enableDebugMode=True"); time.sleep(4.0); mark("dbg_on")
        view("first"); time.sleep(2.0); mark("dbg_on_first"); view("third")
        ini_set("remix_config", "rtx.lights.enableDebugMode=True|rtx.lights.debugDrawLightHashes=True"); time.sleep(4.0); mark("dbg_hashes")
        ini_set("remix_config", "rtx.lights.enableDebugMode=False|rtx.lights.debugDrawLightHashes=False"); time.sleep(4.0); mark("dbg_off")

    if "truck3" in parts:
        # with GTA2DX9_SCENE_MODELS=17: the fire truck by day (the look without the game's
        # directional light), its siren beacons at night, and the driver's seat both ways
        hour(14.0); s = scene_car(); mark(f"truck3 at {s['x']:.1f},{s['y']:.1f}")
        view("third"); look("truck3_day_outside", steps=3, secs=0.4)
        hour(dusk); time.sleep(1.0); mark("truck3_dusk_outside")
        hour(night); ini_set("force_sirens", 1); time.sleep(1.0)
        look("truck3_night_sirens", steps=4, secs=0.4)
        for attempt in range(3):
            tap("Return", 0.3); s = in_car(8)
            if s["driving"]: break
        mark(f"truck3 driving={s['driving']} model={s.get('cmodel')}")
        if s["driving"]:
            Q.set_view("first", settle=2.0); mark("truck3_night_fp_0")
            hold("Left", 0.3); time.sleep(1.2); mark("truck3_night_fp_1")
            hour(14.0); time.sleep(1.0); mark("truck3_day_fp_0")
            D.xdo("keydown", "Up"); time.sleep(1.2); mark("truck3_day_fp_move"); time.sleep(0.5); D.xdo("keyup", "Up")
            time.sleep(1.5); mark("truck3_day_fp_1")
            Q.set_view("third", settle=1.5); mark("truck3_day_chase")
            T.leave_car()
        ini_set("force_sirens", 0)

    if "ab2" in parts:
        # what lights the street at night: each candidate off in turn, the view held still
        hour(night); s = scene_car(); mark(f"ab2 at {s['x']:.1f},{s['y']:.1f}")
        view("third"); time.sleep(2.0); mark("ab2_base")
        steps = [("lightsoff", None, 1), ("base2", None, 0),
                 ("dirscale0", "rtx.atmosphere.directionalLightRadianceScale=0", 0),
                 ("ignoredir", "rtx.atmosphere.directionalLightRadianceScale=1|rtx.ignoreGameDirectionalLights=True", 0),
                 ("ignoreall", "rtx.ignoreGameDirectionalLights=True|rtx.ignoreGamePointLights=True|rtx.ignoreGameSpotLights=True", 0),
                 ("noexposure", "rtx.ignoreGameDirectionalLights=False|rtx.ignoreGamePointLights=False|rtx.ignoreGameSpotLights=False|rtx.autoExposure.enabled=False", 0),
                 ("back", "rtx.autoExposure.enabled=True", 0)]
        for name, conf, off in steps:
            if conf: ini_set("remix_config", conf)
            ini_set("remix_lights_off", off); time.sleep(4.5); mark(f"ab2_{name}")
            view("first"); time.sleep(1.5); mark(f"ab2_{name}_first"); view("third")

    if "truck2" in parts:
        hour(14.0); s = scene_car(); mark(f"truck2 scene at {s['x']:.1f},{s['y']:.1f}")
        view("third"); look("truck_outside", steps=2)
        if driver_seat("truck_day"):
            hour(night); Q.set_view("first", settle=2.5); mark("truck_night_fp_0")
            hold("Left", 0.3); time.sleep(1.2); mark("truck_night_fp_1")
            Q.set_view("third", settle=1.5); mark("truck_night_chase")
            T.leave_car()

    T.finish("remix3 take")
    sys.exit(0)


def force(n):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^force_car_model=.*$", f"force_car_model={n}", t)
    open(T.INI, "w", encoding="latin-1").write(t)

def look(tag, key="Left", steps=3, secs=0.55):
    mark(f"{tag}_0"); time.sleep(1.2)
    for i in range(steps):
        hold(key, secs); time.sleep(1.4); mark(f"{tag}_{i + 1}")
    time.sleep(0.6)

district = os.environ.get("DISTRICT", "wil")
world = M.World(district)
mark("script start")
s = D.wait_state(); say("start:", T.words(s))
time.sleep(2); mark("classic_spawn"); hold("Up", 1.5); time.sleep(2)
view("third"); look("third_spawn")
view("first"); look("first_spawn", steps=4)
scene = os.environ.get("SCENE_XY", "")
if scene:
    v = [float(c) for c in scene.split(",")]
    s = warp(v[0], v[1], int(v[2]) if len(v) > 2 else None, why="the showcase car")
    # No parked car near the point: go to the nearest parked car the renderer
    # reports and bring that one instead (up to three tries).
    for attempt in range(3):
        last = (T.devtools_lines() or [""])[-1]
        if "no parked car" not in last: break
        s = D.wait_state()
        if not s or not s.get("parked"): break
        s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
    view("third"); time.sleep(1.5)
    for n in [int(m) for m in os.environ.get("CAR_MODELS", "").split(",") if m.strip()]:
        force(n); time.sleep(2.6)
        look(f"car_{n:03d}_third", steps=4, secs=0.45)
        Q.set_view("first", settle=1.0); mark(f"car_{n:03d}_first"); time.sleep(1.2)
        Q.set_view("third", settle=1.0)
    if os.environ.get("CAR_MODELS"):
        force(-1); time.sleep(1.5)
    drive_xy = os.environ.get("DRIVE_XY", "")
    if drive_xy:
        s = T.get_in_scene_car()
        if s and s["driving"]:
            dx, dy = [float(c) for c in drive_xy.split(",")[:2]]
            s = drive(world, dx, dy, "the showcase drive", budget=int(os.environ.get("DRIVE_BUDGET", "80")), fp_after=25.0)
            mark("drive_end"); time.sleep(2)
            T.leave_car()
view("first"); look("first_end", steps=4)
view("third"); look("third_end")
T.finish("remix showcase")
