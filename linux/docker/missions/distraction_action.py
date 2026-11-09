#!/usr/bin/env python3
"""DISTRACTION ACTION! (Residential file ste, the Zaibatsu red phone 208.5,25.5 L4, ste_zh2.mis): the
proof job of the truck-and-trailer skill (gamerun/skills/truck_trailer.py, SKILL-BUS, Wave M).

The red phone runs DO_PHONE_TEMPLATE (2818, ste_zh1.mis, ste_zh2.mis, ..., zaibgang, 4): it wants
Zaibatsu respect >= 4 bars and offers MURDER IN THE MALL! (zh1, title 2469: 100 scientists by a
foot weapon) first; DISTRACTION ACTION! (title 2470) is the phone's second job. A fresh session has
respect 0. Developer aids, both marked in /out/marks.txt and the run log:
  * skills/gang_respect.exe sets the Zaibatsu respect (100 = 5 bars) through the game's gang table;
  * DA_SKIP_ZH1=1: when the phone starts zh1, the runner is arrested on purpose ([devtools]
    force_wanted=1, standing still) so zh1 ends failed, then answers the phone again for zh2.
  * DA_WARP_PHONE=1: the developer scene warp to the street by the phone (the 140-block trip from
    the district start is not the job), and after the phone a warp is NOT used: the drive to the
    cop station is the runner's.

What the script wants (assets-src/missions/ste_m/ste_zh2.mis):
  2470 title, 2960 brief, the arrow at 67.5,117.5 (a COLLECT_04 weapon there): LOCATE_CHARACTER_ANY_MEANS
  4 x 3 -> 2962, the arrow on the POWERGEN at 82.5,116.5 z 6 (the cop station's roof);
  CHECK_OBJ_MODEL (POWERGEN_DEAD) -> 2969, alarms, door4 (101,124, the yard's south door) opens, the
  arrow on the truck (TRUKCAB1 + TRUKTRNS with the FBI car on it, 96.5,117.5);
  IS_CHARACTER_IN_CAR (truck) -> 2970, DISPLAY_TIMER 60 s (1800 frames), wanted level 3;
  the truck wrecked (2971) or the trailer off (2973) -> 2998; 1800 frames later 2975, 2999, $70,000.

Run (speed 2, no video):
  GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 SWAP_LEVEL=ste INI_SED='s/^scene_key=.*/scene_key=F11/' \\
    gamerun/grun.sh da1 1500 missions/keys_distraction_action.sh -e GTA2DX9_STATE_EVERY=5 -e DISTRICT=ste \\
    -e WARP_OK=0 -e DA_WARP_PHONE=1 -e DA_SKIP_ZH1=1 -e GTA2DX9_SCENE_NO_CAR=1
Summary /out/da_result.json; milestone frames /out/m_da_*.png, /out/m_truck_*.png.
"""
import json, math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
from skills import truck_trailer as T

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world

PHONE_JOB = "ste_zh1"            # the db lists the phone under its first job
PHONE = (208.5, 25.5)
ARROW1 = (67.5, 117.5)           # LOCATE_CHARACTER_ANY_MEANS 4 x 3, a COLLECT_04 there
GEN = (82.5, 116.5, 5)           # POWERGEN, z 6 = lid level 5
TRUCK = (96.5, 117.5)
DOOR = (101.5, 124.5)            # door4, the yard's south door (DOUBLE, bottom)
OUT_ST = (101.5, 128.5)          # the road south of it
ZH1_TITLE, ZH2_TITLE = "2469", "2470"
FAIL = {"2998", "2963", "2971", "2973"}
DONE = {"2999", "2975"}
BUST_KEYS = {"6155", "6159"}
RESULT = dict(stage="start", events=[])
MSGS = T.Msgs(start_at_end=False)
LIVES0 = [None]
ZH2 = [False]


class Over(Exception):
    pass


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); say(what)


def respect(gang="zaib", value=None):
    args = ["wine", "/work/skills/gang_respect.exe"] + ([gang, str(value)] if value is not None else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    for line in out.splitlines(): say(line)
    if value is not None: M.mark(f"DEV AID: gang_respect {gang} {value} ({out.splitlines()[-1] if out else ''})")
    return out


def set_ini(key, val):
    t = open(M.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(M.INI, "w", encoding="latin-1").write(t2)
    M.mark(f"DEV AID: [devtools] {key}={val}")


def over():
    if not ZH2[0]: return None
    MSGS.poll()
    i = max((j for j, k in enumerate(MSGS.seen) if k == ZH2_TITLE), default=0)
    seen = MSGS.seen[i:]
    if any(k in DONE for k in seen): return "complete"
    if any(k in FAIL for k in seen): return "failed"
    ms = M.mission_state() or {}
    if ms.get("msg") in BUST_KEYS: return "busted"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def warp_phone():
    s = D.wait_state()
    if math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) < 30: return
    near = M.street_cell_near(world, PHONE[0], PHONE[1] + 6, radius=10)
    if near:
        P.set_view("classic")
        M.scene_warp(near[0], near[1], near[2], "DA_WARP_PHONE: to the street by the Zaibatsu red phone; the job starts at the phone")
        P.set_view("third"); RESULT["events"].append(f"phone warp to {near}")


def answer_phone():
    entry = next(m for m in world.db["missions"] if m.get("mission") == PHONE_JOB)
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    k0 = MSGS.mark()
    ok, key = P.answer(entry)
    MSGS.poll()
    new = MSGS.seen[k0:]
    M.set_avoid_phones(world, keep=None)
    say(f"phone: ok={ok} key={key} new messages {new}")
    return entry, new


def bust_out_of_zh1():
    """zh1 (MURDER IN THE MALL) running: get arrested so it ends failed (a death or an arrest is the
    only way it ends short of 100 kills)"""
    # da1: on the phone's terrace at one star no cop came up in 3 minutes: down to the street first
    s = D.wait_state()
    st = M.street_cell_near(world, s["x"], s["y"] + 4, radius=10)
    if st:
        ev(f"zh1: down to the street at {st[0]:.1f},{st[1]:.1f} for the police")
        M.walk3(world, st[0], st[1], None, tol=1.0, budget=150)
    ev("DEV AID: DA_SKIP_ZH1 - zh1 started; force_wanted=4 (police shoot) and standing until zh1 ends")
    set_ini("force_wanted", 4)
    busted = False; p0 = None; ms0 = M.mission_state() or {}
    lives0 = ms0.get("lives"); f0 = ms0.get("frame", 0)
    while True:
        ms = M.mission_state() or {}
        if ms.get("frame", 0) - f0 > 30 * 420: break           # 7 game minutes (da3: paused runs ran out a wall clock)
        s = D.wait_state()
        if s and s["driving"]: M.leave_car()
        if ms.get("msg") in BUST_KEYS or ms.get("death", 0) != 0 or (lives0 is not None and ms.get("lives", lives0) < lives0):
            busted = True; break
        if s and p0 and math.hypot(s["x"] - p0[0], s["y"] - p0[1]) > 25:
            busted = True; ev(f"zh1: respawned at {s['x']:.1f},{s['y']:.1f} (arrested or killed)"); break
        if s and not p0: p0 = (s["x"], s["y"])
        time.sleep(1.0)
    set_ini("force_wanted", -1)
    M.shot("da_busted")
    ev(f"zh1: {'ended (arrest/death)' if busted else 'still running after 7 game min'} (msg {(M.mission_state() or {}).get('msg')})")
    # wait for the respawn (the death flag clears, the player stands again)
    t1 = time.time()
    while time.time() - t1 < 60:
        ms = M.mission_state() or {}
        if ms.get("death", 0) == 0 and time.time() - t1 > 6: break
        time.sleep(1.0)
    time.sleep(4.0)
    return busted


def get_to_phone_and_start():
    """respect, the phone, zh1 skipped if DA_SKIP_ZH1, until 2470 shows. Returns True when zh2 runs"""
    respect("zaib", 100)
    for attempt in range(7):
        if os.environ.get("DA_WARP_PHONE", "0") == "1": warp_phone()
        k0 = MSGS.mark()
        entry, new = answer_phone()
        t0 = time.time()
        while time.time() - t0 < 8 / D.SPEED and not ({ZH1_TITLE, ZH2_TITLE, "6173"} & set(MSGS.poll()[k0:])):
            time.sleep(0.3)
        new = MSGS.seen[k0:]
        M.shot(f"da_phone{attempt}")
        if ZH2_TITLE in new:
            ZH2[0] = True; ev(f"phone: DISTRACTION ACTION! (2470) started (attempt {attempt + 1})"); return True
        if ZH1_TITLE in new:
            ev("phone: MURDER IN THE MALL! (2469, zh1) started")
            if os.environ.get("DA_SKIP_ZH1", "0") != "1": return False
            bust_out_of_zh1()
            respect("zaib", 100)
            continue
        # 6173 "How do you expect to rise up the Zaibatsu ranks with such pitiful displays": the
        # phone's answer right after a failed job; step off, wait, answer again
        ev(f"phone: no title (messages {new}); off the phone, wait, again")
        respect("zaib", 100)
        ox, oy = M.step_off_phone(world, entry); M.cruise_to(ox, oy, tol=0.5, secs=8)
        ox2, oy2 = M.step_off_phone(world, entry, dist=3.0); M.cruise_to(ox2, oy2, tol=0.5, secs=8)
        time.sleep((10 + 10 * attempt) / D.SPEED)
    return False


def to_arrow1():
    """from the phone to 67.5,117.5: a car, a drive, the last blocks on foot"""
    s = D.wait_state()
    if math.hypot(ARROW1[0] - s["x"], ARROW1[1] - s["y"]) > 30:
        # down from the phone terrace first
        st = M.street_cell_near(world, s["x"], s["y"], radius=10)
        if st: M.walk3(world, st[0], st[1], None, tol=1.0, budget=120)
        s = M.any_car2(world, budget=150)
        if s["driving"]:
            cell = M.street_cell_near(world, ARROW1[0] - 2, ARROW1[1], radius=6) or (ARROW1[0], ARROW1[1], 1)
            for leg in range(3):
                P.FP["until"] = 0.0
                s = M.drive3(world, cell[0], cell[1], tol=3.0, budget=420, view_switch=P.view_switch)
                if not s["driving"] or math.hypot(cell[0] - s["x"], cell[1] - s["y"]) < 6: break
            if s["driving"]: M.leave_car()
    P.set_view("third")
    k0 = MSGS.mark()
    M.walk3(world, ARROW1[0], ARROW1[1], None, tol=0.4, budget=200)
    for k in range(6):
        if MSGS.since(["2962"], k0) or (M.objective() and abs(M.objective()[0] - GEN[0]) < 1.5): break
        M.cruise_to(ARROW1[0] + 0.4 * math.cos(k * 2.1), ARROW1[1] + 0.4 * math.sin(k * 2.1), tol=0.2, secs=4)
        time.sleep(0.5)
    ms = M.mission_state() or {}
    ev(f"at the video store point: weapon {ms.get('weapon')}({ms.get('wid')}) ammo {ms.get('ammo')}; 2962 {MSGS.since(['2962'], k0)}")
    M.shot("da_arrow1")


def gen_dead():
    MSGS.poll()
    return "2969" in MSGS.seen or bool((lambda o: o and abs(o[0] - TRUCK[0]) < 3 and abs(o[1] - TRUCK[1]) < 3)(M.objective()))


def stand_cells(x, y, L, rmin=1.5, rmax=4.5):
    out = []
    for dx in range(-5, 6):
        for dy in range(-5, 6):
            cx, cy = int(x) + dx, int(y) + dy
            d = math.hypot(cx + 0.5 - x, cy + 0.5 - y)
            if not (rmin <= d <= rmax): continue
            k = M.node_kind(world, cx, cy, L)
            if k and k[0] == "flat": out.append((d, cx + 0.5, cy + 0.5))
    return [(x_, y_) for _, x_, y_ in sorted(out)]


def destroy_gen(budget=420):
    """to a flat cell at the generator's level 2-4 blocks from it, face it, fire; other cells if
    nothing happens"""
    t0 = time.time()
    M.select_gun(8)
    cells = stand_cells(GEN[0], GEN[1], GEN[2])
    s = D.wait_state()
    route_ok = []
    for c in cells[:12]:
        path = M.route3(world, int(s["x"]), int(s["y"]), world.level(s), int(c[0]), int(c[1]), GEN[2])
        if path: route_ok.append((len(path), c))
    route_ok.sort()
    ev(f"generator: {len(cells)} stand cells at level {GEN[2]}, {len(route_ok)} routed")
    tried = 0
    for _, c in route_ok[:5]:
        if gen_dead() or time.time() - t0 > budget: break
        tried += 1
        ev(f"generator: to {c[0]:.1f},{c[1]:.1f} (level {GEN[2]})")
        s = M.walk3(world, c[0], c[1], GEN[2], tol=0.5, budget=150)
        M.shot(f"da_gen_stand{tried}")
        say(f"generator: at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f}")
        for k in range(10):
            if gen_dead(): break
            if not M.gun_ready(): M.select_gun(8)
            M._aim_walk(GEN[0], GEN[1], fire=True, walk=False, secs=1.2)
            xdo("keyup", "Control_L")
            time.sleep(0.3)
        xdo("keyup", "Control_L")
    ok = gen_dead()
    ev(f"generator: {'destroyed (2969)' if ok else 'still up'} after {time.time() - t0:.0f}s")
    M.shot("da_gen_after")
    return ok


def into_truck():
    s = D.wait_state()
    o = M.objective()
    tx, ty = (o[0], o[1]) if o and math.hypot(o[0] - TRUCK[0], o[1] - TRUCK[1]) < 5 else TRUCK
    ev(f"to the truck at {tx:.1f},{ty:.1f}")
    s = P.enter_parked(tx, ty, budget=200, why="the hitched truck")
    ms = M.mission_state() or {}
    ev(f"truck: driving={s['driving']} model {s.get('cmodel')} carhp {ms.get('carhp')}")
    return bool(s["driving"]) and T.in_cab(s)


def timer_done():
    MSGS.poll()
    return any(k in DONE for k in MSGS.seen) or "2975" in MSGS.seen


def lost():
    MSGS.poll()
    return "2973" in MSGS.seen


def play():
    s = D.wait_state()
    LIVES0[0] = None
    if not get_to_phone_and_start(): return "zh2 not started"
    RESULT["stage"] = "phone"
    LIVES0[0] = (M.mission_state() or {}).get("lives")
    to_arrow1(); RESULT["stage"] = "arrow1"; check()
    if not destroy_gen(): return "generator not destroyed"
    RESULT["stage"] = "generator"; check()
    if not into_truck():
        # one more try
        if not into_truck(): return "not in the truck"
    RESULT["stage"] = "truck"; M.shot("da_truck")
    P.set_view("third")
    cab, tr = T.rig()
    ev(f"rig: cab {cab and (cab['x'], cab['y'], cab['hx'], cab['hy'])} trailer {tr and (tr['model'], tr['x'], tr['y'])}")
    # out of the yard by the south door, then the loop
    r, s = T.tow(world, DOOR[0], DOOR[1] - 1.0, tol=1.5, budget=60, check=check, lost=lost)
    ev(f"to the yard door: {r} at {s['x']:.1f},{s['y']:.1f}")
    r, s = T.tow(world, OUT_ST[0], OUT_ST[1], tol=2.0, budget=60, check=check, lost=lost)
    ev(f"out of the yard: {r} at {s['x']:.1f},{s['y']:.1f}")
    M.shot("da_out")
    r = T.evade(world, timer_done, check=check, lost=lost, centre=(110.0, 140.0), budget=200, view_switch=None)
    ev(f"evade: {r}")
    return over() or r


def main():
    D.start(); D.wait_state(40)
    MSGS.poll()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o = over()
    if o and r not in ("complete", "failed", "dead", "busted"): r = f"{o} ({r})"
    ev(f"mission ste_zh2: {r}")
    time.sleep(2.5); M.shot("da_end"); time.sleep(2.0); M.shot("da_end2")
    RESULT["result"] = r; RESULT["messages"] = MSGS.seen[-60:]
    RESULT["truck_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in T.EVENTS]
    RESULT["truck_stats"] = T.STATS
    with open("/out/da_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r)
    return r


if __name__ == "__main__":
    main()
