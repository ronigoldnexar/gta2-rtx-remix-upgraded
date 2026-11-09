#!/usr/bin/env python3
"""GET GAMA REI! (Downtown, Yakuza yellow phone 86.5,185.5, wil_ym2) with the Wave M escort skill
(gamerun/skills/escort.py), SKILL-ESCORT.

    python3 /work/missions/get_gama_rei.py        (inside the container, after to_level.sh)

The yellow phone opens at Yakuza respect 2 (`DO_PHONE_TEMPLATE (..., yakuzagang, 2)` in wil.mis); each
green Yakuza job passed is +1 and each failed -1 (`CHANGE_GANG_CHAR_RESPECT_AND_UPDATE`). So a session
first plays the two green jobs with their own runners, imported unchanged (missions/bank_robbery.py,
PLAYTHROUGH-10; missions/get_zitzaki.py, SKILL-DELIVER), sharing one view state, then GET GAMA REI:

  1. any MEDICAR (model 34): skills/steal_car (IS_CHARACTER_IN_MODEL; brief 1372, arrow at 88.5,84.5);
  2. IS_CAR_IN_BLOCK (car, 88.5,84.5, 3 x 2): deliver_intact into the box (the arrow is removed there);
  3. Gama Rei (CREATE_CHAR 92.5,83.5 remap 13) walks to 92.5,84.5, then ENTER_CAR_AS_PASSENGER: the
     escort skill's wait_board (keys off, the car brought to him if he stalls); his death or the
     Medicar wrecked fails (1375/1376 + 1125);
  4. two Loony Isettas (machine gun, pistol, KILL_CHAR_ANY_MEANS Gama Rei) come after him; the drive to
     IS_CAR_IN_BLOCK (35.5,187.5, 4 x 2) is the escort skill's drive (deliver_intact with Gama Rei
     watched aboard and the pace raised while an Isetta or an armed Loony is near); PARK (door7) and
     JOB COMPLETE 1124 (+$40,000) follow, with both of them in the car.

Env: GR_SKIP_GREEN=1 goes straight to the yellow phone (a session that already has the respect),
one attempt per green job (a failure ends the session). Frames /out/m_gr_*.png (chase view), marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import deliver_intact as DI
from skills import escort as ES
from skills import steal_car as SC
from missions import bank_robbery as BR
from missions import get_zitzaki as GZ

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

MISSION = "wil_ym2"
TITLE = "1978"
REFUSALS = ("1097", "1096", "1103", "1098", "1102", "1104", "1113", "1093")
MEDICAR = 34
SCRIPT_OCC = 18     # a CREATE_CHAR ... CRIMINAL character: occupation 18 in `view: peds` (gr4: Dr ZitZaki, ped 337, crim/yakuza then gang/yakuza, remap 13)
HOSP_BOX = (88.5, 84.5, 3.0, 2.0)
GAMA_AT = (92.5, 84.0)
SAFE_BOX = (35.5, 187.5, 4.0, 2.0)
# where a Medicar is likely: round the two hospitals (GET ZITZAKI's at 50.5,178.5 and this job's)
SEARCH_SEEDS = [(52.5, 182.5), (60.5, 170.5), (88.5, 88.5), (96.5, 84.5), (80.5, 84.5), (88.5, 96.5), (70.5, 140.5)]

# ------------------------------------------------------------------ one view state for every runner

VIEW = ["classic"]
VIEW_SLEEP = [1.7]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(VIEW_SLEEP[0])
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

for mod in (BR, GZ):
    mod.VIEW = VIEW; mod.set_view = set_view

FP = {"until": 0.0}
def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 15; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

def chase_shot(name):
    if VIEW[0] != "third": set_view("third"); FP["until"] = -1
    M.shot(f"gr_{name}")

# ------------------------------------------------------------------ outcome

MONEY0 = [0]
def outcome():
    ms = M.mission_state()
    if not ms: return "unknown", ms
    if ms["msg"] in M.COMPLETE_KEYS: return "complete", ms
    if ms["msg"] in M.FAILED_KEYS: return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if M.LIVES0[0] is not None and ms["lives"] < M.LIVES0[0]: return "dead", ms
    if ms["money"] >= MONEY0[0] + 35000: return "complete", ms
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

# ------------------------------------------------------------------ phones

def off_the_dais(world, entry):
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and s["z"] > 3.5 and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on the phone dais (z {s['z']:.1f}); developer warp to the street at {cell[0]},{cell[1]} (reported)")
            set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone dais"); set_view("third")

def zitzaki_escort(world):
    """GET ZITZAKI with Dr ZitZaki handed to the escort skill: the Miura and the hospital box by
    get_zitzaki's own legs (deliver_intact), then the horn in the 3 x 1 box until the doctor is
    created (CREATE_CHAR 47.5,178.5 remap 13), escort.wait_board for his walk and
    ENTER_CAR_AS_PASSENGER, and escort.drive (deliver_intact with him watched aboard) to the J-Lab
    garage. Raises GZ.Over at the job's end like GZ.run"""
    CAR0, HOSPITAL, GARAGE = GZ.CAR0, GZ.HOSPITAL, GZ.GARAGE
    M.mark(f"to the MIURA at {CAR0[0]},{CAR0[1]}")
    s = M.enter_car3(world, CAR0[0], CAR0[1], budget=200)
    if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
        say("the walk to the mission car failed; developer warp to its door (reported)")
        set_view("classic"); M.scene_warp(CAR0[0], CAR0[1] + 1.0, M.top_level(world, CAR0[0], CAR0[1]) or 1, "to the mission car's door"); set_view("third")
        s = M.enter_car3(world, CAR0[0], CAR0[1], budget=90)
    if not (s and s["driving"]): return "stuck: could not enter the Miura"
    GZ.check()
    t1 = time.time()
    while time.time() - t1 < 20 and DI.box_arrow(HOSPITAL) != "up": time.sleep(0.5)
    GZ.FP["until"] = 0.0
    in_box = lambda: DI.box_arrow(HOSPITAL) == "cleared" or GZ.doctor_aboard()
    r = DI.deliver(world, HOSPITAL, car=CAR0, check=GZ.check, view_switch=GZ.view_switch, budget=420,
                   done=in_box, label="the hospital box")
    say("hospital:", r)
    if r in ("complete", "failed", "dead"): return r
    chase_shot("zz_hospital")
    doc = ES.Escort("Dr ZitZaki", pick=lambda p: p["remap"] == 13 and p["occ"] == SCRIPT_OCC and p["car"] is None, near=(47.8, 178.5), radius=3.0)
    # the horn in the box until the script creates him (it removes the box arrow while the car is in it)
    t0 = time.time(); k = 0
    while time.time() - t0 < 150 and not doc.ids and not GZ.doctor_aboard():
        GZ.check()
        s = D.wait_state()
        if not s["driving"]: DI.board(world, CAR0, check=GZ.check); continue
        if DI.box_arrow(HOSPITAL) == "up":
            say("horn: outside the 3 x 1 box: back in")
            DI.deliver(world, HOSPITAL, car=CAR0, check=GZ.check, view_switch=None, budget=120, tries=2,
                       done=lambda: DI.box_arrow(HOSPITAL) == "cleared" or GZ.doctor_aboard(), label="the hospital box")
        DI.keys_off(); M.horn(1); k += 1
        doc.acquire(secs=2.0, check=GZ.check)
    if not doc.ids and not GZ.doctor_aboard(): return "stuck: the doctor never came out"
    r = ES.wait_board(world, doc, car=CAR0, budget=150, horn=False, move=True, done=GZ.doctor_aboard, check=GZ.check)
    if r != "aboard": return f"escort: {r}"
    ms = GZ.check()
    M.mark(f"Dr ZitZaki aboard (msg {ms.get('msg')}, carhp {ms.get('carhp')}, ids {doc.ids})"); chase_shot("zz_doctor")
    GZ.FP["until"] = 0.0
    if doc.ids:
        r = ES.drive(world, GARAGE, doc, car=CAR0, check=GZ.check, view_switch=GZ.view_switch, budget=420,
                     park_wait=45, label="the J-Lab garage")
    else:
        r = DI.deliver(world, GARAGE, car=CAR0, check=GZ.check, view_switch=GZ.view_switch, budget=420, park_wait=45, label="the J-Lab garage")
    say("garage:", r)
    chase_shot("zz_garage")
    if r in ("complete", "failed", "dead"): return r
    o, ms = GZ.wait_outcome(45)
    return o

def green(world, mod, mission, runs_entry):
    """one green Yakuza job with its own runner module; returns its result string"""
    entry = next(m for m in world.db["missions"] if m.get("mission") == mission)
    M.mark(f"mission {mission} (respect for the yellow phone)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = mod.answer(world, entry)
    if r == "no answer": r, seen = mod.answer(world, entry)
    say(f"{mission} phone:", r, seen)
    if r != "answered":
        M.mark(f"mission {mission}: phone {r} {seen}"); return f"phone {r}"
    M.arm_lives()
    mod.MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    mod.FP["until"] = 0.0
    off_the_dais(world, entry)
    try:
        r = runs_entry(world) if callable(runs_entry) else (mod.run(world, entry) if runs_entry else mod.run(world))
    except mod.Over as e:
        r = str(e)
    if r == "running":
        o, ms = mod.wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission {mission}: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    M.shot(f"gr_{mission}_end")
    if r == "complete": M.DONE_PHONES.add((entry["x"], entry["y"]))
    if r == "dead": time.sleep(14)          # the hospital; the next walk starts from there
    time.sleep(4)
    return r

def answer_yellow(world, entry):
    before = M.mission_state(); m0 = before["msg"] if before else ""
    s = D.wait_state()
    M.arrows_baseline()
    if s and not s["driving"] and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 60:
        M.mark("a long way to the yellow phone: by car"); s = M.any_car2(world, budget=100)
    if s and s["driving"]:
        FP["until"] = 0.0
        s = M.drive3(world, entry["x"], entry["y"], tol=4.0, budget=360, view_switch=view_switch, slow=True)
        s = M.leave_car(); set_view("third")
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
            if ms["msg"] in (TITLE, "1371"): return "answered", seen
            if ms["msg"] in REFUSALS: return "refused", seen
        if time.time() - t0 > 6 and not seen:
            s = D.wait_state()
            if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.5:
                ox, oy = M.step_off_phone(world, entry, dist=1.2)
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            GZ.nudge_to(entry["x"], entry["y"], tol=0.1, tries=6)
        time.sleep(0.25)
    return "no answer", seen

# ------------------------------------------------------------------ the job

def in_medicar():
    ms = M.mission_state() or {}
    s = D.state()
    return bool(s and s["driving"] and ms.get("carmodel") == MEDICAR)

def medicar_xy():
    """the nearest Medicar in `view: cars` (where ours is when he is out of it)"""
    s = D.state()
    cs = [c for c in M.cars() if c["model"] == MEDICAR and c["fire"] < 1]
    if not cs or not s: return None
    c = min(cs, key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
    return (c["x"], c["y"])

def seeds(world):
    out = []
    for x, y in SEARCH_SEEDS:
        c = M.street_cell_near(world, x, y)
        if c: out.append((c[0], c[1]))
    return out

def gama_aboard_brief():
    ms = M.mission_state() or {}
    if ms.get("msg") in ("1377", "1378"): return True
    o = M.objective()
    return bool(o and o[3] == 1 and math.hypot(o[0] - SAFE_BOX[0], o[1] - SAFE_BOX[1]) < 3)

def is_killer_car(c):
    return c["model"] == 29 or "loon" in c["driver"]

def is_killer(p):
    return p["gang"].startswith("loon") and p["occ"] in ES.ARMED_OCC

def summon_medicar(world, secs=150):
    """gr1: no Medicar drove past in 10 minutes of touring; the game sends one to a casualty. On foot,
    shoot the nearest civilian on foot (not a cop, not near a cop), then stand off and watch the cars
    line for model 34. True when one is in sight"""
    s = D.wait_state()
    if s["driving"]: hold("Down", 0.8); DI.keys_off(); s = M.leave_car()
    set_view("third")
    if not M.gun_ready() and not M.select_gun(): M.fetch_gun(world, budget=200)
    t0 = time.time(); victim = None
    while time.time() - t0 < 60:
        check()
        s = D.wait_state()
        cops = [p for p in M.peds() if p["type"] in ("cop", "swat", "fbi") and M.ped_alive(p)]
        civs = [p for p in M.peds() if p["type"] == "civ" and p["car"] is None and M.ped_alive(p) and p["id"] != 1
                and all(math.hypot(p["x"] - c["x"], p["y"] - c["y"]) > 14 for c in cops)]
        if victim is not None:
            q = next((p for p in M.peds() if p["id"] == victim["id"]), None)
            if q is None or not M.ped_alive(q):
                M.mark(f"medicar: casualty at {victim['x']:.1f},{victim['y']:.1f}"); break
            victim = q
        elif civs:
            victim = min(civs, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
            M.mark(f"medicar: a casualty to bring an ambulance: ped {victim['id']} at {victim['x']:.1f},{victim['y']:.1f}")
        if victim is None:
            M.walk3(world, s["x"] + 4, s["y"], None, tol=1.0, budget=15); continue
        d = math.hypot(victim["x"] - s["x"], victim["y"] - s["y"])
        M._aim_walk(victim["x"], victim["y"], fire=True, walk=d > 4.0, secs=0.5)
    xdo("keyup", "Control_L"); xdo("keyup", "Up")
    t1 = time.time()
    while time.time() - t1 < secs:
        check()
        if medicar_xy(): M.mark(f"medicar: one in sight at {medicar_xy()}"); return True
        time.sleep(1.0)
    return False

def run(world):
    # 1. a Medicar
    M.mark("steal a MEDICAR")
    tries = 0
    while not in_medicar():
        check(); tries += 1
        if tries > 4: return "stuck: no Medicar"
        if tries > 1 and not medicar_xy(): summon_medicar(world)
        s = SC.steal_car(world, "MEDICAR", search=seeds(world), budget=1200 if tries == 1 else 300,
                         check=lambda: outcome()[0] not in ("running", "unknown"), view_switch=view_switch)
        if s is None: check(); continue
        # gr1: steal_car was in the Medicar and this loop gave up the same second: the mission
        # line's carmodel lags the jack by a few frames; wait for it (or brief 1372)
        t1 = time.time()
        while time.time() - t1 < 8 and not in_medicar() and (M.mission_state() or {}).get("msg") != "1372":
            time.sleep(0.5)
        if (M.mission_state() or {}).get("msg") == "1372": break
    ms = check()
    M.mark(f"in a MEDICAR (carhp {ms.get('carhp')})"); chase_shot("medicar")
    t1 = time.time()
    while time.time() - t1 < 15 and DI.box_arrow(HOSP_BOX) != "up": time.sleep(0.5)

    # 2. into the hospital box
    FP["until"] = 0.0
    gama = ES.Escort("Gama Rei", pick=lambda p: p["remap"] == 13 and p["occ"] == SCRIPT_OCC and p["car"] is None, near=GAMA_AT, radius=3.5)
    r = DI.deliver(world, HOSP_BOX, car=None, check=check, view_switch=view_switch, budget=600,
                   done=lambda: DI.box_arrow(HOSP_BOX) in ("cleared", "moved") or (M.mission_state() or {}).get("msg") == "1374",
                   label="the hospital box")
    say("hospital box:", r)
    if r in ("complete", "failed", "dead"): return r
    if r.startswith("stuck"): return r
    chase_shot("hospital")

    # 3. Gama Rei boards
    r = ES.wait_board(world, gama, car=medicar_xy(), budget=180, move=True, done=gama_aboard_brief, check=check)
    if r != "aboard": return f"escort: {r}"
    if not gama.ids: gama.adopt_aboard()
    ms = check()
    M.mark(f"Gama Rei aboard (msg {ms.get('msg')}, carhp {ms.get('carhp')}, ids {gama.ids})"); chase_shot("aboard")

    # 4. to the safehouse with the Loony killers after him
    FP["until"] = 0.0
    if gama.ids:
        r = ES.drive(world, SAFE_BOX, gama, car=None, check=check, view_switch=view_switch,
                     threat_pick=is_killer, car_threat_pick=is_killer_car, budget=900, park_wait=45, label="the safehouse")
    else:
        say("Gama Rei not identified in the peds log: plain deliver")
        r = DI.deliver(world, SAFE_BOX, car=None, check=check, view_switch=view_switch, budget=900, park_wait=45, label="the safehouse")
    say("safehouse:", r)
    chase_shot("safehouse")
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
    results = {}
    if os.environ.get("GR_SKIP_GREEN", "0") != "1":
        # one try each: a failed green job is -1 respect, and with only two green Yakuza jobs the
        # yellow phone can then not open in this session (gr2: BANK ROBBERY failed at the respray)
        for mission, mod, runs_entry in (("wil_ye1", GZ, zitzaki_escort), ("wil_ye2", BR, True)):
            r = green(world, mod, mission, runs_entry)
            results[mission] = r
            if r != "complete":
                say("green jobs:", results); M.mark(f"session over: {mission} {r}, Yakuza respect cannot reach 2")
                say("RESULTS", results); return
        say("green jobs:", results)
    entry = next(m for m in world.db["missions"] if m.get("mission") == MISSION)
    M.mark(f"mission {MISSION}: GET GAMA REI! (skill escort)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = answer_yellow(world, entry)
    if r == "no answer": r, seen = answer_yellow(world, entry)
    say("yellow phone:", r, seen); M.shot("gr_phone")
    if r != "answered":
        results[MISSION] = f"phone {r} {seen}"
        M.mark(f"mission {MISSION}: phone {r} {seen}"); say("RESULTS", results); return
    M.arm_lives()
    MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    off_the_dais(world, entry)
    try:
        r = run(world)
    except Over as e:
        r = str(e)
    if r == "running":
        o, ms = wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission {MISSION}: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')} carhp {ms.get('carhp')}")
    M.shot("gr_end")
    set_view("third"); time.sleep(1.0); M.shot("gr_end_third")
    for t, e in ES.EVENTS: say(f"escort event +{t - t_m:.0f}s: {e}")
    results[MISSION] = r
    say("RESULTS", results)
    M.mark(f"done {MISSION}={r}")

if __name__ == "__main__":
    main()
