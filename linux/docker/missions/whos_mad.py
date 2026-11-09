#!/usr/bin/env python3
"""WHO'S MAD? (wil_lm1, Loonies, yellow phone 10.5,46.5) played with the on-foot gunfight skill
(SKILL-GUNFIGHT, Wave M).

    python3 /work/missions/whos_mad.py        (inside the container, after to_level.sh)

What the script wants (`assets-src/missions/wil_m/wil_lm1.mis`): title 1970, brief 1463, an arrow
to 128.5,195.5 (LOCATE_CHARACTER_ANY_MEANS, 2 x 2: "go and meet Cosmo Trouble"). There, brief 1464,
and three Zaibatsu hitmen (`CREATE_CHAR_INSIDE_CAR ... CRIMINAL`, gang zaibatsu, two machine guns
and a pistol, objective KILL_CHAR_ANY_MEANS on the player) come in three VTYPEs from 149.5,192.5,
168.5,212.5 and 126.5,213.5. An arrow is put on each while he is on screen; while the player is on
foot their cars' top speed is 0 when on screen. Each death: brief 1466, +$500; three dead: 1467,
JOB COMPLETE (1124), +$40,000. A death or an arrest fails it.

The yellow phone wants Loonies respect >= 2 bars; a fresh game has 0. skills/gang_respect.exe sets
it to 60 (3 bars) through the game's own gang table at the start of the session (a developer aid,
written to the marks). Nothing else in the job is helped: the car, the phone, the gun, the drive
and the fight are the runner's.

Steps: a car to the Loonies' yard; the machine gun from the generator at 11.5,47.5 (beside the
WHO'S MAD? phone; the DESTROY J-LAB! phone at 11.5,46.5 is kept off the router); the phone; back to
the car, another machine gun at 84.5,184.5 on the way; the car parked short of the meeting point,
the last blocks on foot; then the fight (`skills/gunfight.gunfight`) anchored on the meeting point
until the job ends. Frames /out/m_wm_*.png and /out/m_gf_*.png, marks /out/marks.txt."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import gunfight as G

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

JOB = "wil_lm1"
PHONE = (10.5, 46.5)
GUN = (41.5, 48.5)               # COLLECT_01 machine gun generator, 31 blocks east of the phone. Not the one
                                 # at 11.5,47.5: one block from the DESTROY J-LAB! phone, which answered (gf_wm1)
GUN_ROAD = (33.5, 40.5)
PHONE_WEST = (9.4, 46.6)         # the phone is entered from the west: 11.5,46.5 (J-Lab) is a block east of it
PHONE_ON = (10.35, 46.5)
GUN2 = (84.5, 184.5)             # another, 44 blocks short of the meeting point
GUN2_ROAD = (84.5, 182.8)
MEET = (128.5, 195.5)            # LOCATE_CHARACTER_ANY_MEANS (2 x 2)
PARK = (123.5, 190.5)            # the road cell nearest the meeting point (street_cell_near)
ANCHOR = (125.5, 204.5)          # where the fight is held: the open plaza south of the yard (rows 202-207,
                                 # columns 115-139). The meeting box is in a walled yard (x 126-132,
                                 # y 193-200, openings east and south): gf_wm5 fought through its west wall
SPAWNS = [(149.5, 192.5), (168.5, 212.5), (126.5, 213.5)]
TITLE = "1970"
REFUSALS = ("1097", "1096", "1103", "1098", "1102", "1104", "1113", "1093")
RESPECT = int(os.environ.get("GF_RESPECT", "60"))

VIEW = ["classic"]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

FP = {"until": 0.0}
def view_switch(s):
    """a first-person stretch at the wheel at the start of each drive, then the chase view"""
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 15; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1


class Over(Exception):
    pass

STARTED = [False]
def check():
    if not STARTED[0]: return M.mission_state() or {}
    o, ms = G.job_state()
    if o not in ("running", "unknown"): raise Over(o)
    return ms or {}


def respect(gang="loon", value=None):
    args = ["wine", "/work/skills/gang_respect.exe"] + ([gang, str(value)] if value is not None else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    for line in out.splitlines(): say(line)
    return out


def drive(world, x, y, tol=2.0, budget=300):
    s = D.wait_state()
    if not s["driving"]: return s
    FP["until"] = 0.0
    return M.drive3(world, x, y, tol=tol, budget=budget, view_switch=view_switch, slow=False)


CAR = {"at": None}
def to_a_car(world):
    """the car left last (where it was), else any car"""
    s = D.wait_state()
    if s["driving"]: return s
    if CAR["at"] and math.hypot(CAR["at"][0] - s["x"], CAR["at"][1] - s["y"]) < 40:
        s = M.enter_car3(world, CAR["at"][0], CAR["at"][1], budget=50)
        if s and s["driving"]: return s
    return M.any_car2(world, budget=120)


def leave(world):
    s = D.wait_state()
    if s["driving"]:
        CAR["at"] = (s["x"], s["y"]); hold("space", 0.4); s = M.leave_car()
    set_view("third")
    return s


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


def answer(world):
    before = M.mission_state(); m0 = before["msg"] if before else ""
    M.mark("onto the WHO'S MAD? phone (from the west)")
    s = M.walk3(world, PHONE_WEST[0], PHONE_WEST[1], None, tol=0.4, budget=150)
    s = nudge_to(PHONE_ON[0], PHONE_ON[1], tol=0.15, tries=12)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone") and not (ms["msg"].isdigit() and 1600 <= int(ms["msg"]) <= 1615):
            if ms["msg"] not in seen: seen.append(ms["msg"])
            if ms["msg"] in (TITLE, "1463"): return "answered", seen
            if ms["msg"] in REFUSALS: return "refused", seen
        if M.objective() and math.hypot(M.objective()[0] - MEET[0], M.objective()[1] - MEET[1]) < 2: return "answered", seen
        if time.time() - t0 > 6 and not seen:
            s = D.wait_state()
            if s and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) < 0.5:
                ox, oy = PHONE[0] - 1.3, PHONE[1] + 0.6        # off to the west side, away from the J-Lab phone
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            nudge_to(PHONE_ON[0], PHONE_ON[1], tol=0.12, tries=6)
        time.sleep(0.25)
    return "no answer", seen


HITMEN = set()
VTYPE = 70           # the hitmen's cars (CREATE_GANG_CAR ... VTYPE): model 70 in `view: peds`
def hostile(p):
    """the hitmen: Zaibatsu men (CREATE_CHAR ... CRIMINAL, then ADD_CHAR_TO_GANG zaibatsu, which the
    peds line shows as gang/zaibatsu) in their VTYPEs, or any Zaibatsu the job has put an arrow on.
    gf_wm2: they never got an arrow (IS_ITEM_ONSCREEN) and circled the block at 6-20 blocks in
    their cars; once picked, the skill keeps a man a hostile when he leaves the car"""
    if p["gang"] != "zaibatsu": return False
    if p["car"] == VTYPE or p["type"] == "crim": HITMEN.add(p["id"])
    # gf_wm6: the third left his car at the yard's gate before the fight began; on foot, with no
    # arrow, he matched nothing: once seen in a VTYPE a man stays a hitman
    return p["id"] in HITMEN or p["mark"] is not None


def run(world, entry):
    # 1. a car to the Loonies' yard
    s = D.wait_state()
    M.mark(f"to the Loonies' yard ({math.hypot(PHONE[0] - s['x'], PHONE[1] - s['y']):.0f} blocks)")
    for k in range(3):
        s = to_a_car(world)
        if s and s["driving"]: break
    if s and s["driving"]:
        M.shot("wm_incar")
        s = drive(world, GUN_ROAD[0], GUN_ROAD[1], tol=2.0, budget=360)
        s = leave(world)
    M.mark("on foot near the gun")
    # 2. the gun
    if not M.gun_ready() and not M.select_gun(3):
        M.walk3(world, GUN[0], GUN[1], None, tol=0.35, budget=120)
        for k in range(8):
            if M.gun_ready(): break
            M.cruise_to(GUN[0] + 0.25 * math.cos(k * 2.1), GUN[1] + 0.25 * math.sin(k * 2.1), tol=0.15, secs=3)
            time.sleep(0.4)
    ms = M.mission_state() or {}
    M.mark(f"gun: {ms.get('weapon')} ammo {ms.get('ammo')}")
    # 3. the phone
    r, seen = answer(world)
    if r == "no answer": r, seen = answer(world)
    M.shot("wm_phone")
    M.mark(f"phone: {r} {seen}")
    if r != "answered": return f"phone {r} {seen}"
    STARTED[0] = True; M.arm_lives(); G.arm_job()
    M.set_avoid_phones(world, keep=None)
    ox, oy = PHONE[0] - 1.3, PHONE[1] + 0.6
    M.cruise_to(ox, oy, tol=0.5, secs=6)
    # 4. back to the car, a second gun on the way, to the meeting point
    for k in range(3):
        check(); s = to_a_car(world)
        if s and s["driving"]: break
    if not (s and s["driving"]): return "stuck: no car after the phone"
    ms = M.mission_state() or {}
    if ms.get("ammo", 0) < 400:
        M.mark(f"to the second gun at {GUN2} (ammo {ms.get('ammo')})")
        s = drive(world, GUN2_ROAD[0], GUN2_ROAD[1], tol=1.5, budget=300); check()
        if s["driving"] and math.hypot(GUN2[0] - s["x"], GUN2[1] - s["y"]) < 8:
            s = leave(world)
            M.walk3(world, GUN2[0], GUN2[1], None, tol=0.35, budget=40)
            for k in range(6):
                a0 = (M.mission_state() or {}).get("ammo", 0)
                M.cruise_to(GUN2[0] + 0.25 * math.cos(k * 2.1), GUN2[1] + 0.25 * math.sin(k * 2.1), tol=0.15, secs=3)
                time.sleep(0.4)
                if (M.mission_state() or {}).get("ammo", 0) > a0: break
            ms = M.mission_state() or {}; M.mark(f"gun 2: {ms.get('weapon')} ammo {ms.get('ammo')}")
            check(); s = to_a_car(world)
    M.mark(f"to the meeting point {MEET}")
    if s and s["driving"]:
        s = drive(world, PARK[0], PARK[1], tol=1.5, budget=300); check()
        s = leave(world)
    M.select_gun()
    # 5. the last blocks on foot, into the box
    M.mark("on foot into the meeting box")
    s = M.walk3(world, MEET[0], MEET[1], None, tol=0.6, budget=90); check()
    t1 = time.time()
    while time.time() - t1 < 15:
        ms = check()
        if ms.get("msg") == "1464" or M.objective() is None: break
        nudge_to(MEET[0], MEET[1], tol=0.3, tries=3)
    M.shot("wm_meet")
    ms = check()
    M.mark(f"at the meeting point (msg {ms.get('msg')}, arrows {len(M.mission_arrows())}): the hitmen are coming")
    [hostile(p) for p in M.peds()]
    say(f"hostiles: {[(p['id'], p['type'], p['gang'], p['x'], p['y'], p['car'], p['mark']) for p in M.peds() if hostile(p)]}")
    # 6. the fight, held on the open plaza south of the yard. The skill starts at once and walks him
    # there itself in bounded steps (gf_wm9: a separate walk to the plaza took 60 health from hitmen
    # who arrived early, with the trigger off)
    [hostile(p) for p in M.peds()]
    M.mark("gunfight skill: the three hitmen")
    r = G.gunfight(world, select=hostile, check=check, secs=float(os.environ.get("GF_SECS", "360")),
                   engage=7.0, close=2.5, anchor=ANCHOR, leash=4.0, low=45, shot_prefix="gf_wm")
    ms = M.mission_state() or {}
    M.mark(f"gunfight skill: {r} {G.STATS} (health {ms.get('health')}, msg {ms.get('msg')})")
    t3 = time.time()
    while time.time() - t3 < 30:
        check(); time.sleep(0.5)
    return "running"


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
    M.mark(f"developer aid: Loonies respect set to {RESPECT} (yellow phone needs 2 bars; a fresh game has 0)")
    respect("loon", RESPECT)
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: WHO'S MAD? (the fight by the gunfight skill)")
    M.set_avoid_phones(world, keep=PHONE)
    t_m = time.time()
    try:
        r = run(world, entry)
    except (Over, G.JobOver) as e:
        r = str(e)
    if r == "running":
        o, ms = G.job_state(); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission {JOB}: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    M.shot("wm_end")
    time.sleep(1.5); M.shot("wm_end2")
    say("RESULTS", {JOB: r})
    M.mark(f"done {JOB}={r}")


if __name__ == "__main__":
    main()
