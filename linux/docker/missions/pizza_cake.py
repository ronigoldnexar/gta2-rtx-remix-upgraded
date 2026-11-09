#!/usr/bin/env python3
"""PIZZA CAKE! (Downtown, Loonies green phone 75.5,41.5, wil_le2), played with the Wave M
'destroy a vehicle' skill (gamerun/skills/destroy_vehicle.py) for the van.

    python3 /work/missions/pizza_cake.py          (inside the container, after to_level.sh)

The script (assets-src/missions/wil_m/wil_le2.mis):
  1. title 1955, brief 1531; the explosives (a briefcase object) at 28.5,106.5 z 3:
     LOCATE_CHARACTER_ON_FOOT 1 x 1;
  2. brief 1533: deliver them by hand to Pizza Cake, LOCATE_CHARACTER_ON_FOOT 13.5,105.5 z 3, 1 x 1;
  3. brief 1536, a five-second fuse (149 frames), EXPLODE_SMALL at the box: run;
  4. brief 1538: a VAN (CREATE_CAR 125.5,149.5, locked to the player) with a criminal driver, an
     arrow on it; IS_CAR_WRECKED -> JOB COMPLETE 1124, +$20,000. Death or arrest fails (1125).
The machine gun beside the Loonies' phones (pickup 76.5,39.5) is taken on foot right after the phone
(pt7_le2b: a pickup 60 blocks off after the fuse, run over waiting at a kerb; before the phone its search
circle answered RADIO ZA-ZA next door, dv_pc1/dv_pc3); the walk is on foot
all the way (the Loonies refuse a job after a drive through their turf: 1107 in pt4, 1103 in pt7).
Step 4 is destroy_vehicle.destroy. Milestone frames /out/m_pc_*.png (chase view), marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import destroy_vehicle as DV

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

MISSION = "wil_le2"
EXPLOSIVES = (28.5, 106.5, 1.0, 1.0, 2)     # x, y, w, h, level (z 3)
PIZZA = (13.5, 105.5, 1.0, 1.0, 2)
TITLE, BRIEF0 = "1955", "1531"
VAN_BRIEF = "1538"
REFUSALS = ("1097", "1096", "1098", "1102", "1104", "1107")
BUSY = ("1093", "1103", "1113")              # "already on a <gang> job"
# dv_pc1: the walk from the gun pickup (76.5,39.5) to the phone was straightened into a diagonal
# across RADIO ZA-ZA's phone (75.5,40.5) and that job started (1954). The phone is approached
# from the south-east instead: straight down x = 76.5, then a nudge onto it
APPROACH = (76.5, 42.5)

VIEW = ["classic"]
VIEW_SLEEP = [1.7]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(VIEW_SLEEP[0])
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

def chase_shot(name):
    if VIEW[0] != "third": set_view("third")
    M.shot(f"pc_{name}")

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

def job_arrow():
    o = M.objective()
    return bool(o and math.hypot(o[0] - EXPLOSIVES[0], o[1] - EXPLOSIVES[1]) < 3.0)

def answer(world, entry):
    before = M.mission_state(); m0 = before["msg"] if before else ""
    M.arrows_baseline()
    s = M.walk3(world, APPROACH[0], APPROACH[1], None, tol=0.4, budget=600)
    s = nudge_to(entry["x"], entry["y"], tol=0.25, tries=20)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        lvl = M.top_level(world, entry["x"], entry["y"])
        say(f"phone not reached on foot (level {lvl}); developer warp (reported)")
        M.scene_warp(entry["x"], entry["y"], lvl, "the walker did not reach the phone")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=60)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone") and not (ms["msg"].isdigit() and 1600 <= int(ms["msg"]) <= 1615):
            if ms["msg"] not in seen: seen.append(ms["msg"])
            if ms["msg"] in (TITLE, BRIEF0): return "answered", seen
            if ms["msg"] in BUSY and job_arrow(): return "answered", seen
            if ms["msg"].startswith("19"): return "neighbour", seen      # RADIO ZA-ZA (1954) next door
            if ms["msg"] in REFUSALS: return "refused", seen
        if time.time() - t0 > 6 and not seen:
            s = D.wait_state()
            if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.5:
                ox, oy = M.step_off_phone(world, entry, dist=1.2)
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=6)
        time.sleep(0.25)
    if job_arrow(): return "answered", seen
    return "no answer", seen

# ------------------------------------------------------------------ the job

def box_on_foot(world, box, label):
    """walk into a LOCATE_CHARACTER_ON_FOOT box; True when the job's arrow moved on"""
    x, y, w, h, lvl = box
    key0 = M.objective_key()
    M.mark(f"on foot to {label} at {x},{y}")
    s = D.wait_state()
    if s["driving"]: s = M.leave_car()
    s = M.walk3(world, x, y, lvl, tol=0.4, budget=480)
    ok = M.settle_box(x, y, w, h, money0=MONEY0[0], secs=45, nudge=nudge_to, key0=key0)
    if not ok:
        s = M.walk3(world, x, y, lvl, tol=0.3, budget=60)
        ok = M.settle_box(x, y, w, h, money0=MONEY0[0], secs=40, nudge=nudge_to, key0=key0)
    return ok

def run(world):
    if not box_on_foot(world, EXPLOSIVES, "the explosives"): return "stuck: explosives box"
    chase_shot("explosives")
    check()
    if not box_on_foot(world, PIZZA, "Pizza Cake"): return "stuck: Pizza Cake box"
    # the fuse: five seconds, run back the way he came
    M.mark("fuse: running clear")
    s = D.wait_state(); legs = M.escape_route(world, s)
    if not legs:
        legs = [M.escape_point(world, PIZZA[0], PIZZA[1], PIZZA[4])]
    t_e = time.time()
    for k, (ex, ey) in enumerate(legs[:4]):
        if time.time() - t_e > 10: break
        M.cruise_to(ex, ey, tol=0.8, secs=max(2.0, 10 - (time.time() - t_e)), stop=(k == len(legs[:4]) - 1))
    xdo("keyup", "Up")
    t1 = time.time()
    while time.time() - t1 < 40:
        check()
        ms = M.mission_state() or {}
        if ms.get("msg") == VAN_BRIEF or DV.car_arrows(): break
        time.sleep(0.5)
    ms = check()
    M.mark(f"the van: brief {ms.get('msg')}, {len(DV.car_arrows())} vehicle arrows, health {ms.get('health')}")
    chase_shot("fuse_survived")
    if not M.gun_ready(ms) and not M.select_gun():
        M.fetch_gun(world, budget=300)
    M.mark("destroy the van (skill destroy_vehicle)")
    r = DV.destroy(world, count=1, check=check, secs=900, shot_prefix="pc_van", money0=MONEY0[0])
    say("destroy:", r)
    o, ms = wait_outcome(20)
    return o if o != "running" else r

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
    M.mark(f"mission {MISSION}: PIZZA CAKE! (skill destroy_vehicle)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = answer(world, entry)
    if r == "no answer": r, seen = answer(world, entry)
    say("phone:", r, seen); M.shot("pc_phone")
    if r != "answered":
        M.mark(f"mission {MISSION}: phone {r} {seen}"); say("RESULTS", {MISSION: f"phone {r}"}); return
    M.arm_lives()
    MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    if not M.gun_ready():
        # the machine gun at the pickup beside the phones (76.5,39.5) AFTER the phone: fetch_gun's
        # search circle round the pickup stepped onto RADIO ZA-ZA's phone (75.5,40.5) before the
        # job in dv_pc1 and dv_pc3 (title 1954); with PIZZA CAKE running that phone only says 1103
        M.mark("the machine gun beside the phones (after the phone)")
        M.fetch_gun(world, budget=300, near=(entry["x"], entry["y"]), count=2, walk_only=True)
        say("gun:", (M.mission_state() or {}).get("weapon"))
    try:
        r = run(world)
    except (Over, DV.JobOver) as e:
        r = str(e)
    if r == "running":
        o, ms = wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission {MISSION}: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    chase_shot("end")
    time.sleep(2.0); chase_shot("end2")
    for t, e in DV.EVENTS: say(f"skill event +{t - t_m:.0f}s: {e}")
    say("RESULTS", {MISSION: r})
    M.mark(f"done {MISSION}={r}")

if __name__ == "__main__":
    main()
