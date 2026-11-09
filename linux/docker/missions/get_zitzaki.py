#!/usr/bin/env python3
"""GET ZITZAKI! (Downtown, Yakuza green phone 44.5,150.5, wil_ye1), played with the Wave M
'deliver intact' skill (gamerun/skills/deliver_intact.py) for both car legs.

    python3 /work/missions/get_zitzaki.py          (inside the container, after to_level.sh)

The script (assets-src/missions/wil_m/wil_ye1.mis):
  1. the MIURA (gang car) at 74.5,163.5: get in (IS_CHARACTER_IN_CAR); wrecked or sunk fails (1633/1635);
  2. the City Hospital: LOCATE_CHARACTER_BY_CAR 50.5,178.5 3 x 3, then horn inside the 3 x 1 box
     (IS_CHAR_PRESSING_HORN with the car in 50.5,178.5 3 x 1; outside it, brief 1648 "get back there");
     the arrow is removed while the car is in the 3 x 1 box;
  3. Dr ZitZaki walks out (47.5 -> 48.5,178.5) and boards (ENTER_CAR_AS_PASSENGER); brief 1639;
  4. the J-Lab garage: IS_CAR_IN_BLOCK (car, 44.5,203.5, 3 x 0.8), then PARK (car, door11) and
     JOB COMPLETE 1124 (+$20,000). The doctor dying fails (1637).
Leg 2 and leg 4 are deliver_intact.deliver (fragile drive, respray if the Miura burns, approach
from the open side, creep, hands off for the park). Milestone frames /out/m_zz_*.png (chase view),
marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import deliver_intact as DI

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

MISSION = "wil_ye1"
PHONE = (44.5, 150.5)
CAR0 = (74.5, 163.5)
HOSPITAL = (50.5, 178.5, 3.0, 1.0)       # the horn box (the 3 x 3 locate box is around it)
GARAGE = (44.5, 203.5, 3.0, 0.8)         # IS_CAR_IN_BLOCK, door11
TITLE = "1975"
REFUSALS = ("1097", "1096", "1103", "1098", "1102", "1104", "1113", "1093")

VIEW = ["classic"]
VIEW_SLEEP = [1.7]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(VIEW_SLEEP[0])
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

FP = {"until": 0.0}
def view_switch(s):
    """a first-person stretch at the wheel at the start of the first drive, then the chase view"""
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 15; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

def chase_shot(name):
    """a milestone frame in the chase view"""
    if VIEW[0] != "third": set_view("third"); FP["until"] = -1
    M.shot(f"zz_{name}")

MONEY0 = [0]
def outcome():
    ms = M.mission_state()
    if not ms: return "unknown", ms
    if ms["msg"] in M.COMPLETE_KEYS: return "complete", ms
    if ms["msg"] in M.FAILED_KEYS: return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if M.LIVES0[0] is not None and ms["lives"] < M.LIVES0[0]: return "dead", ms
    if ms["money"] >= MONEY0[0] + 15000: return "complete", ms
    return "running", ms

class Over(Exception):
    pass

def check():
    o, ms = outcome()
    if o not in ("running", "unknown"): raise Over(o)
    return ms or {}

def wait_outcome(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        o, ms = outcome()
        if o not in ("running", "unknown"): return o, ms
        time.sleep(1.0)
    return "running", M.mission_state()

# ------------------------------------------------------------------ the phone

def nudge_to(x, y, tol=0.1, tries=30):
    M.ensure_view("classic")
    for _ in range(tries):
        s = D.wait_state()
        if not s or s["driving"]: return s
        d = math.hypot(x - s["x"], y - s["y"])
        if d < tol: return s
        a = D.angle_to(s, x, y)
        if abs(a) > 0.35:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            hold(key, min(abs(a) / max(D.rate, 2.0), 0.3)); time.sleep(0.35)
            hold("Up", 0.12); time.sleep(0.45)
            continue
        hold("Up", max(0.08, min(0.4, (d - 0.05) / 1.9))); time.sleep(0.5)
    return D.wait_state()

def answer(world, entry):
    before = M.mission_state(); m0 = before["msg"] if before else ""
    M.arrows_baseline()
    s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=420)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        lvl = M.top_level(world, entry["x"], entry["y"])
        say(f"phone not reachable on foot (level {lvl}); developer warp (reported)")
        set_view("classic"); M.scene_warp(entry["x"], entry["y"], lvl, "phone on a dais the walker cannot climb"); set_view("third")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=60)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone") and not (ms["msg"].isdigit() and 1600 <= int(ms["msg"]) <= 1615):
            if ms["msg"] not in seen: seen.append(ms["msg"])
            if ms["msg"] in (TITLE, "1631"): return "answered", seen
            if ms["msg"] in REFUSALS: return "refused", seen
        if time.time() - t0 > 6 and not seen:
            s = D.wait_state()
            if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.5:
                ox, oy = M.step_off_phone(world, entry, dist=1.2)
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=6)
        time.sleep(0.25)
    o = M.objective()
    if o and math.hypot(o[0] - CAR0[0], o[1] - CAR0[1]) < 3.0: return "answered", seen
    return "no answer", seen

# ------------------------------------------------------------------ the job

def doctor_aboard():
    """brief 1639 (to the J-Lab) or the arrow on the garage"""
    ms = M.mission_state() or {}
    o = M.objective()
    return ms.get("msg") == "1639" or bool(o and o[3] == 1 and math.hypot(o[0] - GARAGE[0], o[1] - GARAGE[1]) < 3)

def horn_for_doctor(world, secs=150):
    """horn inside the 3 x 1 box until the doctor is aboard; back into the box when told (1648)"""
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        check()
        if doctor_aboard(): return True
        s = D.wait_state()
        if not s["driving"]:
            s = DI.board(world, CAR0, check=check)
            continue
        o = M.objective()
        if DI.box_arrow(HOSPITAL) == "up":
            # outside the 3 x 1 box (the script puts its arrow back and says 1648): in again
            say(f"horn: outside the 3 x 1 box at {s['x']:.2f},{s['y']:.2f} (arrow {o}): back in")
            DI.deliver(world, HOSPITAL, car=CAR0, check=check, view_switch=None, budget=120, tries=2,
                       done=lambda: DI.box_arrow(HOSPITAL) == "cleared" or doctor_aboard(), label="the hospital box")
        DI.keys_off()
        if k < 20: M.horn(2)
        k += 1
        time.sleep(2.0)
    return doctor_aboard()

def run(world):
    # 1. the Miura
    M.mark(f"to the MIURA at {CAR0[0]},{CAR0[1]}")
    s = M.enter_car3(world, CAR0[0], CAR0[1], budget=200)
    if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
        say("the walk to the mission car failed; developer warp to its door (reported)")
        set_view("classic"); M.scene_warp(CAR0[0], CAR0[1] + 1.0, M.top_level(world, CAR0[0], CAR0[1]) or 1, "to the mission car's door"); set_view("third")
        s = M.enter_car3(world, CAR0[0], CAR0[1], budget=90)
    if not (s and s["driving"]): return "stuck: could not enter the Miura"
    ms = check()
    M.mark(f"in the MIURA (carmodel {ms.get('carmodel')}, carhp {ms.get('carhp')})")
    t1 = time.time()
    while time.time() - t1 < 20:
        o = M.objective()
        if o and o[3] == 1 and math.hypot(o[0] - HOSPITAL[0], o[1] - HOSPITAL[1]) < 3: break
        time.sleep(0.5)
    FP["until"] = 0.0

    # 2. deliver intact to the hospital's 3 x 1 horn box (the arrow goes when the car is in it)
    r = DI.deliver(world, HOSPITAL, car=CAR0, check=check, view_switch=view_switch, budget=420,
                   done=lambda: DI.box_arrow(HOSPITAL) == "cleared" or doctor_aboard(), label="the hospital box")
    say("hospital:", r)
    if r in ("complete", "failed", "dead"): return r
    chase_shot("hospital")

    # 3. horn, the doctor walks out and boards
    M.mark("horn for Dr ZitZaki")
    if not horn_for_doctor(world): return "stuck: the doctor did not board"
    ms = check()
    M.mark(f"Dr ZitZaki aboard (msg {ms.get('msg')}, carhp {ms.get('carhp')})")
    chase_shot("doctor")

    # 4. deliver intact to the J-Lab garage; the game parks it and says JOB COMPLETE
    r = DI.deliver(world, GARAGE, car=CAR0, check=check, view_switch=view_switch, budget=420,
                   park_wait=45, label="the J-Lab garage")
    say("garage:", r)
    chase_shot("garage")
    if r in ("complete", "failed", "dead"): return r
    o, ms = wait_outcome(45)
    return o

def main():
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level")
    M.arrows_baseline()
    M.START[0] = (s["x"], s["y"])
    M.VIEW_HOOK[0] = set_view
    set_view("third")
    entry = next(m for m in world.db["missions"] if m.get("mission") == MISSION)
    M.mark(f"mission {MISSION}: GET ZITZAKI! (skill deliver_intact)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = answer(world, entry)
    if r == "no answer": r, seen = answer(world, entry)
    say("phone:", r, seen); M.shot("zz_phone")
    if r != "answered":
        M.mark(f"mission {MISSION}: phone {r} {seen}"); say("RESULTS", {MISSION: f"phone {r}"}); return
    M.arm_lives()
    MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and s["z"] > 3.5 and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on the phone dais (z {s['z']:.1f}); developer warp to the street at {cell[0]},{cell[1]} (reported)")
            set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone dais"); set_view("third")
    try:
        r = run(world)
    except Over as e:
        r = str(e)
    if r == "running":
        o, ms = wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission {MISSION}: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')} carhp {ms.get('carhp')}")
    M.shot("zz_end")
    set_view("third"); time.sleep(1.0); M.shot("zz_end_third")
    for t, e in DI.EVENTS: say(f"skill event +{t - t_m:.0f}s: {e}")
    say("RESULTS", {MISSION: r})
    M.mark(f"done {MISSION}={r}")

if __name__ == "__main__":
    main()
