#!/usr/bin/env python3
"""LABRAT'S PLAN! (Residential file ste, the SRS Scientists' yellow phone 206.5,227.5, ste_sm1.mis),
played by the on-foot gunfight skill (gamerun/skills/gunfight.py). MISSIONS-BATCH1, Wave M.

The script (assets-src/missions/ste_m/ste_sm1.mis): title 2959, brief 2351, the arrow to The Village
(224.5,20.5, z 3: the raised level-2 quarter in the north-east); a Scientist with a machine gun
(CRACK_SHOT) at 202.5,232.5 joins his group. In zone m18 (the map's zone table: x 162-255,
y 0-57): brief 2353 and START_BONUS_CHECK(m18, no time limit, 47, CHAR, BY_ANY_WEAPON, zaibgang):
kill 47 Zaibatsu in The Village. Out of the zone: 2354 and the arrow back. At 30, 20 and 10 left
a Zaibatsu hitman comes in a VTYPE (silenced machine gun from 214.5,7.5; flamethrower from
190.5,7.5; rocket launcher from 203.5,52.5), KILL_CHAR_ANY_MEANS on the player; their cars stand
still while he is on foot. Passed: 2365, 2999 (JOB COMPLETE), $50,000. A death or arrest fails it.

The yellow phone wants SRS Scientists respect >= 2 bars; a fresh game has 0: skills/gang_respect.exe
sets 60 at the start of the session (a developer aid, written to the marks; as WHO'S MAD? and
OPERATION Z! do). Nothing else in the job is helped.

The phone has the GRAN'PA WE LOVE YOU! phone one block south (206.5,228.5): approached from the
north and the other phone kept off the router.

Steps: respect; the phone (by car when far); a gun (the machine-gun generator at 209.5,147.5 on the
way north; refills at the Village's generator 229.5,68.5); a car into The Village; the fight in
rounds of the gunfight skill, each anchored on one of four open spots of the Village so the hunt
covers the quarter; the job's verdict from the game's words. Frames /out/m_lp_*.png and
/out/m_gf_lp*.png (chase view: GTA2_DIRECT_KEYS=1), marks /out/marks.txt, /out/lp_result.json.

Run (keys script missions/keys_labrats_plan.sh):
  SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 gamerun/grun.sh <name> 2400 missions/keys_labrats_plan.sh
"""
import json, math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
os.environ.setdefault("LP_CAR", "0")         # MISSIONS-BATCH2: mb2_lp2 lost two lives in the run-over cars (shot alight
                                            # at once); the gun rounds kept health 100 for 12 counted kills
os.environ.setdefault("GF_BACK_R", "4.0")     # MISSIONS-BATCH2 (2.2): the gunfight shoots walking backwards at a man this near;
                                            # MISSIONS-BATCH3: 4.0 (mb2_lp1/lp4/lp7/lp8 were shot at 1-4 blocks)
os.environ.setdefault("GF_NEAR_CLEAR", "1.8")  # MISSIONS-BATCH3: mb2_lp1 never fired at a man 0.5-1.1 off ('no clear shot')
os.environ.setdefault("GF_BACKOFF_FIRE", "1")  # MISSIONS-BATCH3: hurt -> retreat firing, never the back turned (mb2_lp1)
os.environ.setdefault("GF_AIM_GATE", "0.15")   # MISSIONS-BATCH3: the trigger only on aim (~70 rounds a counted kill before)
os.environ.setdefault("GF_CARMEN_R", "2.5")
if os.environ.get("LP_ROCKET", "1") == "1":
    os.environ.setdefault("GF_HEAVY", "rocket_launcher")   # MISSIONS-BATCH3: picked up at 230.5,203.5 after the phone    # MISSIONS-BATCH3: off parked VTYPEs with men inside (mb2_lp6/lp7)
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
from skills import gunfight as G

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "ste_sm1"
PHONE = (206.5, 227.5)
PHONE_N = (205.5, 223.5)                    # north of the phone: the GRAN'PA phone is south of it
PHONE_STEPS = [(205.5, 223.5), (204.5, 224.2), (204.5, 226.4), (205.3, 227.35)]   # MISSIONS-BATCH3: down column 204, east along row 227
PHONE_WAY = [(205.5, 219.5), PHONE_N]          # straight south down the field column 203-206 (mb1_ra5 wandered onto the roofs from the east)
WARP = (205.5, 216.0)                       # the road rows 215-217 north of the phone's field (mb1_ra5: the pavement east of it is walled off by column 208 and row 220)
TITLE = {"2959", "2351"}
ZONE = (162, 0, 255, 57)                    # m18 from ste.gmp's zone table
GUNS = [(209.5, 147.5, 1)]                  # on the way north (LP_GUN_FIRST=1 only: 300-500 s a session for it)
VILLAGE_GUN = (221.5, 34.5, 2)              # GENERATOR gen30 COLLECT_01 (machine gun) inside The Village, respawns every 1800 frames
                                            # (mb1_ra1: the one at 229.5,68.5 was never reached; mb1_ra6: no car in The Village)
VILLAGE_ROAD = (224.6, 17.5)                # the level-2 road column 224-225 through The Village
UP_LEGS = [(244.5, 76.6), (250.6, 66.0), (245.0, 58.6), (228.0, 58.6), (224.6, 51.0), (233.6, 46.0), (233.6, 25.0), VILLAGE_ROAD]   # the ramp at rows 58-59, then the level-2 roads (column 224-225 rows 50-59, row 48-49, column 233-234 rows 24-47, row 22-23, column 224-225 rows 9-23)
PATROL = [(224.6, 12.5), (233.6, 30.5), (235.5, 22.6), (245.5, 22.6), (245.5, 32.5), (230.5, 35.6),
          (215.5, 35.6), (205.5, 35.6), (215.5, 48.6), (205.5, 10.6), (215.5, 10.6)]   # level-2 roads in m18
ANCHORS = [(229.5, 18.5), (210.5, 15.5), (243.5, 14.5), (226.5, 6.5)]
ANCHORS_LATE = [(243.5, 14.5), (229.5, 18.5), (233.6, 30.5)]   # 18+ blocks from the first hitman's car (214.5,7.5)
RESPECT = int(os.environ.get("LP_RESPECT", "60"))
RESULT = dict(stage="start", events=[], rounds=[])
STARTED = [False]


class Over(Exception):
    pass


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what)


def messages_since(off):
    try:
        with open(D.LOG, "rb") as f:
            f.seek(off); data = f.read().decode("latin-1")
    except OSError:
        return []
    out = []
    for k in re.findall(r"view: mission [^\n]*?msg=(\S+)", data):
        if not out or out[-1] != k: out.append(k)
    return out


HUD_RX = re.compile(rb"hud3d: money=\S+ .*? health=(-?\d+) .*? counter=(-?\d+)")
def hud_counter():
    """MISSIONS-BATCH2: the job's on-screen counter (m_3_count10 = 47 - the game's bonus count) as the
    renderer's HUD line has it every 2 s (`hud3d: ... counter=N`; -1 when none is up). The skill's
    'down' lines over-count (mb1_ra8: ~45 'down', the game at 27): this is the real count"""
    try:
        with open(D.LOG, "rb") as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 400000)); data = f.read()
    except OSError:
        return None
    m = None
    for m in HUD_RX.finditer(data): pass
    return int(m.group(2)) if m else None


def ev_count(what):
    c = hud_counter()
    ev(f"{what} [counter {c}{'' if c is None or c < 0 else f', {47 - c} of 47 counted'}]")


def step_answer(entry, off0):
    """MISSIONS-BATCH2: mb2_lp5 and mb2_lp9 lost the session at the phone: walk3's cruise unstick
    beside the phone (stuck 0.9 from 206.1,226.0, sideways moves) ended on the GRAN'PA phone one
    block south (2392) or on nothing (2793). Here: the waypoints north of it as before, then aimed
    short steps straight south down column 206 onto the phone, watching the messages; back north
    and on again when silent. Falls back to the session's answer"""
    for (x, y) in PHONE_WAY:
        M.walk3(world, x, y, None, tol=0.5, budget=30)
    px, py = entry["x"], entry["y"]
    for k in range(3):
        # MISSIONS-BATCH3: the map (gmp walls at level 1) has a wall on the south side of 205,224 and of
        # 205,225: from the field north of the phone the only way down is the corridor of column 204 (rows
        # 224-226, walls east and west), then east along row 227 into the phone's cell 206,227 (its north and
        # east sides walled). mb3l_lp1/lp3/lp7 pressed against that wall at y 224.4 (lp7's unstick then put him
        # on the GRAN'PA phone, 206,228, open to the south of the phone's cell); lp2 crept down x 204.8 by luck
        for (wx, wy) in PHONE_STEPS:
            P.nudge_to(wx, wy, tol=0.25, tries=10) if math.hypot(wx - px, wy - py) < 2.0 else M.cruise_to(wx, wy, tol=0.3, secs=6)
        P.nudge_to(px - 0.1, py - 0.1, tol=0.15, tries=14)
        t0 = time.time()
        while time.time() - t0 < 6.0 / D.SPEED:
            seen = messages_since(off0)
            if set(seen) & TITLE: M.mark(f"step_answer: title {seen[:4]}"); return True, next(k2 for k2 in seen if k2 in TITLE)
            if "2392" in seen or "2793" in seen or "2791" in seen:
                o = M.objective()
                if "2392" not in seen and o and math.hypot(o[0] - 224.5, o[1] - 20.5) < 3:
                    M.mark(f"step_answer: {seen[:4]} with the arrow on The Village: started"); return True, "2351"
                M.mark(f"step_answer: not this job ({seen[:4]})"); return False, None
            time.sleep(0.3)
        M.mark(f"step_answer: phone silent after try {k + 1}; off west and on again")
        for (wx, wy) in reversed(PHONE_STEPS[1:]):
            P.nudge_to(wx, wy, tol=0.3, tries=8)
    return P.answer(entry)


def check():
    if not STARTED[0]: return M.mission_state() or {}
    o, ms = G.job_state()
    if o not in ("running", "unknown"): raise Over(o)
    return ms or {}


def respect(gang, value=None):
    args = ["wine", "/work/skills/gang_respect.exe"] + ([gang, str(value)] if value is not None else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    for line in out.splitlines(): say(line)
    return out


def set_respect(tries=8):
    """mb1_ra3: set at game start, before the level had filled the gang table (the police read 0,
    not their -100), and the level's init put the Scientists back to 0: the phone refused (2791).
    Set it once the table is live (police at -100), just before the phone, and read it back"""
    for k in range(tries):
        out = respect("sci", RESPECT)
        if "poligang respect=-100" in out:
            back = respect("sci")
            if f"sciegang respect={RESPECT}," in back:
                M.mark(f"respect: Scientists {RESPECT} (read back)"); return True
        time.sleep(3.0)
    M.mark("respect: could not confirm the Scientists' respect"); return False


def in_zone(x, y):
    return ZONE[0] <= x <= ZONE[2] and ZONE[1] <= y <= ZONE[3]


HOSTILE = set()
def hostile(p):
    """a Zaibatsu man in The Village (the bonus counts Zaibatsu kills in m18 only), or a hitman the
    job sent (gang zaibatsu, in a VTYPE or marked) wherever he is"""
    if p["gang"] != "zaibatsu": return False
    # MISSIONS-BATCH3: mb3l_lp1 chased a man onto a level-3 roof by the flamethrower pad and fell off the
    # Village's edge: only men on the Village level (z 3) and the job's marked hitmen
    if os.environ.get("LP_SAME_LEVEL", "1") == "1" and p["mark"] is None and abs(p["z"] - 3.0) > 0.6:
        return False
    if p["id"] in HOSTILE: return True
    # mb2_lp1: the HUD counter (hud3d counter=) rose with the 'gang/zaibatsu' downs only; the
    # 'civ/zaibatsu' peds (half of the skill's downs in mb1_ra*, 68 of 133) never count. The job's
    # hitmen are CRIMINALs put in zaibgang: 'crim', or marked, or in a car
    if os.environ.get("LP_GANG_ONLY", "1") == "1" and p["type"] not in ("gang", "crim") and p["mark"] is None and p["car"] is None:
        return False
    if in_zone(p["x"], p["y"]) or p["mark"] is not None:
        HOSTILE.add(p["id"]); return True
    return False


def spare(p):
    # our own companion (the Scientist the job gives him) and the Scientists generally
    return p["gang"] in ("scientists", "srs", "sciegang") or (p["gang"] or "").startswith("sci")


def warp_near_phone():
    """LP_WARP_PHONE=1: the developer scene warp to the pavement 4 blocks east of the phone (the
    ~140-block trip from the district start is the shared runner's, not this job's: mb1_lp1 lost
    200 s to a burning borrowed car and a stuck walker on it). Marked WARP in marks.txt"""
    if os.environ.get("LP_WARP_PHONE", "0") != "1": return
    s = D.wait_state()
    if math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) < 30: return
    P.set_view("classic")
    for k in range(4):
        s2 = M.scene_warp(WARP[0], WARP[1], 1, "LP_WARP_PHONE: the road north of the Scientists' phone; the job starts at the phone")
        if s2 and math.hypot(s2["x"] - WARP[0], s2["y"] - WARP[1]) < 8: break
        time.sleep(2.0)
    P.set_view("third")
    RESULT["events"].append("phone warp")


def gun(budget=300):
    if M.gun_ready() or M.select_gun(4): return True
    s = D.wait_state()
    M.GUN_PICKUPS["ste"] = list(GUNS)
    ok = M.fetch_gun(world, budget=budget, near=(s["x"], s["y"]), count=2)
    ms = M.mission_state() or {}
    ev(f"gun: {ok} ({ms.get('weapon')} ammo {ms.get('ammo')})")
    return ok


def empty_car_near(radius=18.0):
    """into the nearest empty car (driver '-', not burning) within radius on his level: the
    developer scene warp leaves its car beside him (marked), and The Village has parked VTYPEs;
    mb1_ra6-9: any_car2 waits at kerbs for traffic that rarely comes on the raised level"""
    s = D.wait_state()
    if not s or s["driving"]: return s
    cs = [c for c in M.cars() if c["driver"] == "-" and c["fire"] <= 0 and c["hp"] > 12000
          and abs(c["z"] - s["z"]) < 0.8 and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < radius]
    cs.sort(key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
    for c in cs[:3]:
        ev(f"into the empty car m{c['model']} at {c['x']:.1f},{c['y']:.1f}")
        s = M.enter_car3(world, c["x"], c["y"], budget=40)
        if s and s["driving"]: return s
    return D.wait_state()


# MISSIONS-BATCH3: 8.0 -> 5.0. mb3l_lp5 lost two whole rounds (120 s) stepping away from one slowly burning
# car (step_away reached 6-7.6, never 9), and the two deaths MISSIONS-BATCH2 put on blasts (mb2_lp6, lp8) were
# gunfire at 1-4 blocks with the burning cars 6-10 off and unexploded (read from their logs)
LP_BLAST = float(os.environ.get("LP_BLAST", "5.0"))
FIRE_R = float(os.environ.get("LP_FIRE_R", "5.5"))      # the station's wait: a burning car this near him or the pads
ROCKET_GEN = (230.5, 203.5)   # GENERATOR gen24 COLLECT_02 (the rocket launcher: pickup model order pistol, machine gun,
                              # rocket launcher...), 35 blocks from the phone on its own level; gen25 (231.5) COLLECT_31 beside it


def rocket():
    """MISSIONS-BATCH3: the rocket launcher before The Village. The machine gun alone gave ~1.5 counted kills a
    game minute at ~70 rounds a kill (mb3l_lp4-lp6), every round cut short by the 100-round generator"""
    if os.environ.get("LP_ROCKET", "1") != "1": return
    ev(f"to the rocket launcher generator at {ROCKET_GEN}")
    M.walk3(world, ROCKET_GEN[0], ROCKET_GEN[1], None, tol=0.35, budget=90 / D.SPEED)
    check()
    got = False
    for k in range(8):
        ms = M.mission_state() or {}
        if ms.get("weapon") == "rocket_launcher": got = True; break
        M.cruise_to(ROCKET_GEN[0] + 0.25 * math.cos(k * 2.1), ROCKET_GEN[1] + 0.25 * math.sin(k * 2.1), tol=0.12, secs=3)
        time.sleep(0.4)
    if not got: got = G.wield("rocket_launcher")
    ms = M.mission_state() or {}
    G.HEAVY_LEFT[0] = ms.get("ammo", 0) if ms.get("weapon") == "rocket_launcher" else 0
    M.cruise_to(ROCKET_GEN[0] + 1.0, ROCKET_GEN[1], tol=0.2, secs=3)      # gen25 COLLECT_31 beside it
    ev(f"rocket launcher: {got}, {G.HEAVY_LEFT[0]} rockets (hand {ms.get('weapon')})")
    M.select_gun(4)


HEAL = (223.5, 34.5)        # GENERATOR gen32 COLLECT_30: health back to 100 (mb2_lp3: 30 -> 100 and 90 -> 100 on it)
LOW_HEALTH = int(os.environ.get("LP_LOW_HEALTH", "70"))   # MISSIONS-BATCH3: 60 -> 70 (most deaths drained from 60 in 2-3 s)
ARMOUR = (222.5, 34.5)      # GENERATOR gen31 COLLECT_31 between the gun and the health pads (the game's armour power-up, by
                            # the collectible order after COLLECT_30 health; not read back: the HUD line has no armour field)
LOW_AMMO = int(os.environ.get("LP_LOW_AMMO", "35"))     # mb2_lp4: back with 16 rounds, no answer to the men at the pads


STATION_FAILED = [False]     # the last station visit did not fix the need: the rounds' done() checks health only


def threat(r=6.0):
    """MISSIONS-BATCH3: the nearest live hostile on foot within r of him, or None. mb3l_lp4: the round ended
    on 31 rounds with a man 3.8 off, and the station's burning-car wait stood still while two men at 1.6
    shot him 100 -> 0 in 3 s: nothing that is not a fight while one is this near"""
    s = D.wait_state()
    if not s: return None
    near = [p for p in M.peds() if M.ped_alive(p) and hostile(p) and p["car"] is None
            and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < r]
    return min(near, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"])) if near else None


def round_done():
    ms = M.mission_state() or {}
    if ms.get("ammo", 0) > 5 and ms.get("health", 100) >= 30 and threat(6.0) is not None:
        return False
    if STATION_FAILED[0]: return ms.get("health", 100) < LOW_HEALTH
    return need_station(ms)


def need_station(ms=None):
    """MISSIONS-BATCH2: mb2_lp3 died with 18 counted fighting on with the dual pistol (the machine gun
    empty) at health 30-10; mb2_lp1 at 90 -> 0 in one round. The round ends and he goes to the
    station (the machine gun and the health generators side by side at 221.5-223.5,34.5)"""
    ms = ms or M.mission_state() or {}
    if ms.get("weapon") == "rocket_launcher" and ms.get("ammo", 0) > 0:
        # MISSIONS-BATCH3 (mb3l_lp8): the rockets in the hand are not a reason for the station (every round ended at once)
        return ms.get("health", 100) < LOW_HEALTH
    return ms.get("health", 100) < LOW_HEALTH or ms.get("weapon") != "machine_gun" or ms.get("ammo", 0) < LOW_AMMO


def station(secs=40):
    """to the generators: health (223.5,34.5) when hurt, the machine gun (221.5,34.5) when short;
    waits by them for a respawn (1800 frames) while the need lasts, the gun in hand at the end"""
    t0 = time.time(); ms = check()
    ev(f"station: health {ms.get('health')}, {ms.get('weapon')} ammo {ms.get('ammo')}")
    def clear_pads():
        # mb2_lp4: three Zaibatsu stood on the pads (221.7-224.1,34.7) when he walked in with 16 rounds
        # and no trigger: 100 -> 0 in 3 s. Any hostile within 8 of the pads is fought first
        s = D.wait_state()
        # mb2_lp7: shot 100 -> 20 standing 5.7 from the pads, the hostile counted only near the pads
        # MISSIONS-BATCH3: mb3l_lp2 started this fight 25 blocks from the pads with 27 rounds, emptied the gun
        # and died unarmed: the pads' men only when he is within 12 of them, men by him only within 9 (5 when
        # short of rounds), and the fight ends with the magazine nearly empty so the walk to the gun pad goes on
        ms0 = M.mission_state() or {}
        ammo = ms0.get("ammo", 0)
        by_pads = s and math.hypot(s["x"] - 222.5, s["y"] - 35.0) < 12.0
        near = [p for p in M.peds() if M.ped_alive(p) and hostile(p) and p["car"] is None
                and ((by_pads and math.hypot(p["x"] - 222.5, p["y"] - 35.0) < 8.0)
                     or (s and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < (9.0 if ammo >= 40 else 5.0)))]
        if near and ammo >= 10 and (M.gun_ready() or M.select_gun(4)):
            ev(f"station: {len(near)} hostile by the pads; fighting first")
            fight(select=hostile, spare=spare, secs=20, clear=3.0, engage=9.0, close=5.0, far=12.0,
                  done=lambda: (M.mission_state() or {}).get("ammo", 0) < 6,
                  anchor=(222.5, 37.5), leash=3.0, low=50, blast=float(LP_BLAST), close_car=6.0, police="shoot", shot_prefix="gf_lp_pads",
                  car_targets=False)       # mb2_lp6: shooting a VTYPE by the pads set it alight

    def no_fire(limit=35):
        # mb2_lp6: the walk back to the pads passed a car he had set alight (step-aways twice) and the
        # blast killed him at health 100: no walk while a burning car is within 7 of him or of the pads
        t1 = time.time()
        while time.time() - t1 < limit / D.SPEED:
            s = D.wait_state(); check()
            if threat(6.0) is not None:
                if (M.mission_state() or {}).get("ammo", 0) < 10: return     # empty: on to the gun pad
                clear_pads(); continue
            bc = [c for c in M.cars() if c["fire"] > 0 and (math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < FIRE_R
                                                           or math.hypot(c["x"] - 222.5, c["y"] - 35.0) < FIRE_R)]
            if not bc: return
            c = bc[0]
            if math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < FIRE_R:
                G.step_away(s, c["x"], c["y"], d=FIRE_R + 0.5 - math.hypot(c["x"] - s["x"], c["y"] - s["y"]), secs=3.0)
            else:
                time.sleep(1.0)
    no_fire()
    clear_pads()
    M.walk3(world, 222.5, 37.0, None, tol=1.2, budget=40 / D.SPEED)
    while time.time() - t0 < secs / D.SPEED:
        ms = check()
        clear_pads(); no_fire()
        if os.environ.get("LP_ARMOUR", "1") == "1":
            M.cruise_to(ARMOUR[0], ARMOUR[1], tol=0.2, secs=3); time.sleep(0.2)
        if ms.get("health", 100) < 100:
            M.cruise_to(HEAL[0], HEAL[1], tol=0.2, secs=3); time.sleep(0.3)
        ms = check()
        if ms.get("weapon") != "machine_gun" or ms.get("ammo", 0) < 60:
            M.cruise_to(VILLAGE_GUN[0], VILLAGE_GUN[1], tol=0.2, secs=3); time.sleep(0.3)
        ms = check()
        if ms.get("health", 100) >= LOW_HEALTH + 20 and ms.get("ammo", 0) >= 60:
            break
        M.cruise_to(222.5, 36.0, tol=0.3, secs=2); time.sleep(1.0)     # off the pads: they give only when stepped on
    for k in range(6):
        ms = M.mission_state() or {}
        if ms.get("weapon") == "machine_gun": break
        tap("x", 0.15); time.sleep(0.5)
    ms = check()
    STATION_FAILED[0] = need_station(ms)     # mb2_lp7: the gun pad never reached, every round ended at once
    ev(f"station: done, health {ms.get('health')}, {ms.get('weapon')} ammo {ms.get('ammo')}{' (need not met)' if STATION_FAILED[0] else ''}")


def fight(**kw):
    """the gunfight skill, with one guard: mb1_ra7's fight walked to the gun generator itself (the
    skill's own refill via M.GUN_PICKUPS) and its jump check took that 20-block walk for an arrest
    ("moved 20 blocks at once"), lives 5, no JOB FAILED: the job's own state decides"""
    try:
        return G.gunfight(world, check=check, **kw)
    except G.JobOver as e:
        o, ms = G.job_state()
        if o in ("running", "unknown") and (M.LIVES0[0] is None or ms.get("lives", 0) >= M.LIVES0[0]):
            ev(f"gunfight said '{e}' but the job runs (lives {ms.get('lives')}, msg {ms.get('msg')}): on")
            return "skill jump check"
        raise


def warp_keep_car(x, y, level, why):
    """mission_lib.scene_warp without its last step (it gets out of the scene's car): the developer
    scene warp leaves him in a car, which the run-over rounds use. Marked WARP like the shared one"""
    t = open(M.INI, encoding="latin-1").read()
    km = re.search(r"(?m)^scene_key=(\S+)", t)
    key = km.group(1) if km else "F11"
    open(M.INI, "w", encoding="latin-1").write(re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={x},{y},{level}", t))
    for attempt in range(4):
        off0 = M.log_size(); tap(key, 0.3); time.sleep(2.5)
        new = M.devtools_lines(off0)
        if new and "ignored" not in new[-1] and "refused" not in new[-1]: break
        time.sleep(1.0)
    time.sleep(1.5); s = D.wait_state()
    M.mark(f"WARP to {x},{y},{level} ({why}) -> at {s['x']:.1f},{s['y']:.1f} z={s['z']:.2f} driving={s['driving']}")
    return s


def to_village():
    s = D.wait_state()
    if in_zone(s["x"], s["y"]) and not s["driving"]: return s
    if os.environ.get("LP_WARP_VILLAGE_FIRST", "0") == "1":
        # mb1_lp1-ra11: one honest drive up of eight (the others burned, drowned or wandered): the trip
        # is the shared driver's, not this job's; the warp keeps the scene's car for the run-over rounds
        s = D.wait_state()
        if s["driving"]: M.leave_car()
        P.set_view("classic")
        warp_keep_car(233.6, 30.5, 2, "LP_WARP_VILLAGE_FIRST: The Village road; the trip there is not this job's skill")
        P.set_view("third"); RESULT["events"].append("village warp (first)")
    for k in range(6):
        check(); s = D.wait_state()
        if in_zone(s["x"], s["y"]): break
        if not s["driving"]: s = empty_car_near()
        if not s["driving"]: s = M.any_car2(world, budget=120)
        if not (s and s["driving"]) or (k >= 2 and os.environ.get("LP_WARP_VILLAGE", "0") == "1"):
            # mb1_ra4: the on-foot fallback toward the ramp climbed a roof (z 8) and fell: no walking.
            # After two honest drives (cars burned on the way in mb1_ra1-4), LP_WARP_VILLAGE=1 is the
            # developer scene warp to The Village's road, marked WARP (the trip, not the job's fight)
            if k >= 2 and os.environ.get("LP_WARP_VILLAGE", "0") == "1":
                if s and s["driving"]: M.leave_car()
                P.set_view("classic")
                s = M.scene_warp(233.6, 30.5, 2, f"LP_WARP_VILLAGE: two drives to The Village failed; the road at its south end")
                P.set_view("third"); RESULT["events"].append("village warp")
                continue
            if not (s and s["driving"]): time.sleep(2.0); continue
        ev(f"by car to The Village ({math.hypot(VILLAGE_ROAD[0] - s['x'], VILLAGE_ROAD[1] - s['y']):.0f} blocks), leg {k + 1}")
        P.FP["until"] = 0.0
        # mb1_lp1: the router's way north ran along column 250 and the car fell into the water
        # channel at 249.5,82.8 (z 2 -> 1, a life lost at health 100). The only way up to the raised
        # Village is the ramp at rows 58-59 (slope x 232-239, from the level-1 road at x 240-251):
        # explicit legs, the channel strip kept off the car router
        M.CAR_AVOID.update({(x, y) for x in range(247, 256) for y in range(79, 112)})
        for lx, ly in UP_LEGS:
            s = D.wait_state()
            if not s["driving"]: break
            if ly > s["y"] + 2 and lx != UP_LEGS[-1][0]: continue      # already past this leg
            ev(f"leg to {lx},{ly}")
            M.drive3(world, lx, ly, tol=2.5, budget=300, view_switch=P.view_switch)
            check()
        s = D.wait_state()
        if in_zone(s["x"], s["y"]): break
    s = D.wait_state()
    if s["driving"] and not (in_zone(s["x"], s["y"]) and os.environ.get("LP_CAR", "1") == "1"):
        hold("space", 0.4); M.leave_car()
    P.set_view("third")
    return D.wait_state()


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: {entry.get('title', '')} (missions/labrats_plan.py, skills/gunfight.py)")
    M.mark(f"developer aid: SRS Scientists respect set to {RESPECT} (the yellow phone needs 2 bars; a fresh game has 0)")
    P.APPROACH[(entry["x"], entry["y"])] = PHONE_WAY
    warp_near_phone()
    set_respect()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    off0 = M.log_size()
    ok, key = step_answer(entry, off0) if os.environ.get("LP_STEP_ANSWER", "1") == "1" else P.answer(entry)
    M.set_avoid_phones(world, keep=None)
    ms = M.mission_state() or {}
    # mb1_ra12: the GRAN'PA phone one block south answered (its brief 2392, never 2351/2353) and a
    # whole session fought for a job that was not running: confirm the title in the log since the answer
    time.sleep(2.0)
    seen = messages_since(off0)
    ev(f"messages since the answer: {seen[:8]}")
    o = M.objective()
    village_arrow = bool(o and math.hypot(o[0] - 224.5, o[1] - 20.5) < 3)
    if not (set(seen) & TITLE) and village_arrow and "2392" not in seen:
        # MISSIONS-BATCH3: mb3l_lp3 got ['6146', '2793'] and the job's arrow to The Village (224.5,20.5): the
        # 2351 brief fell between two samples of the mission line (mb3l_lp1 had 6146, 2351, 2793)
        ev(f"title not sampled ({seen[:6]}) but the job's arrow points at The Village: started")
        seen.append("2351"); key = key or "2351"
    if not (set(seen) & TITLE):
        return f"wrong job or none (messages {seen[:6]}, arrow {o[:2] if o else None})"
    M.shot("m_lp_phone")
    started = P.TITLES.get(key)
    ev(f"phone: {ok} {key} msg {ms.get('msg')}")
    if started and started.get("mission") != NAME:
        return f"wrong phone ({started['mission']})"
    if not ok and ms.get("msg") not in TITLE and not (M.objective() and abs(M.objective()[0] - 224.5) < 2):
        return "phone not answered"
    STARTED[0] = True; M.arm_lives(); G.arm_job()
    # MISSIONS-BATCH3: the skill's own refill (gunfight 'no gun in hand' -> M.fetch_gun) took the district list
    # and drove mb3l_lp2 200 blocks south out of The Village after a death it did not see: the Village gun only
    M.GUN_PICKUPS["ste"] = [VILLAGE_GUN]
    RESULT["stage"] = "phone"
    ax, ay = M.step_off_phone(world, entry)
    M.cruise_to(ax, ay, tol=0.5, secs=8)
    rocket(); check()
    # 1. a gun on the way north
    if os.environ.get("LP_GUN_FIRST", "0") == "1": gun(budget=200); check()
    # 2. The Village
    to_village(); check()
    RESULT["stage"] = "village"; M.shot("m_lp_village")
    ms = M.mission_state() or {}
    s = D.wait_state()
    ev(f"{'in' if in_zone(s['x'], s['y']) else 'NOT in'} The Village at {s['x']:.1f},{s['y']:.1f} (msg {ms.get('msg')}, health {ms.get('health')}, ammo {ms.get('ammo')})")
    # 3. the fight, round by round over the quarter
    t0 = time.time(); k = 0
    budget = float(os.environ.get("LP_SECS", "2000"))
    while time.time() - t0 < budget:
        ms = check(); k += 1
        s = D.wait_state()
        if not in_zone(s["x"], s["y"]):
            ev(f"round {k}: out of The Village at {s['x']:.1f},{s['y']:.1f}: back in")
            to_village(); continue
        if not s["driving"] and os.environ.get("LP_CAR", "1") == "1":
            # mb1_ra8/ra9: on foot the Zaibatsu, hostile once their respect falls, killed him at close
            # range (100 -> 0 in 3 s; beaten at 0.3 blocks): the car first, the gun when there is none
            s = empty_car_near()
        if s["driving"]:
            P.set_view("third")
            r, n = M.run_over(world, [8], {"2999"}, {"2998"}, (224.6, 20.0), secs=150, patrol=PATROL)
            RESULT["rounds"].append(dict(kind="car", result=r, kills=n))
            ms = M.mission_state() or {}
            ev_count(f"round {k} (car): {r} run over {n} (health {ms.get('health')}, carhp {ms.get('carhp')}, msg {ms.get('msg')})")
            if r in ("burning", "on foot"):
                s = D.wait_state()
                if s["driving"]: M.leave_car()
                # away from the burning car before anything else
                # mb1_ra10: out of the burning car and straight into a fight at health 100 -> 10: to the
                # generators (power-ups beside the gun) first, 8+ blocks off the wreck
                M.walk3(world, 222.5, VILLAGE_GUN[1], None, tol=0.5, budget=25 / D.SPEED)
                for gx in (221.5, 222.5, 223.5):
                    M.cruise_to(gx, VILLAGE_GUN[1], tol=0.2, secs=3)
            if k % 3 == 1: M.shot(f"m_lp_round{k}")
            continue
        if ms.get("ammo", 0) <= 0 and not s["driving"] and not M.select_gun(4):
            M.GUN_PICKUPS["ste"] = [VILLAGE_GUN]
            got = M.fetch_gun(world, budget=90, count=1, walk_only=True); check()
            if not got:
                # the generator's 1800-frame respawn: stand by it a while
                t1 = time.time()
                while time.time() - t1 < 30 / D.SPEED and not M.gun_ready():
                    M.cruise_to(VILLAGE_GUN[0] + 0.3 * math.cos(t1), VILLAGE_GUN[1], tol=0.15, secs=3); check(); time.sleep(1.0)
            # the two generators beside it (COLLECT_31 / COLLECT_30, 222.5 / 223.5,34.5): power-ups
            # (mb1_ra8 died 100 -> 0 in 3 s to Zaibatsu firing back at close range)
            for gx in (222.5, 223.5):
                M.cruise_to(gx, VILLAGE_GUN[1], tol=0.2, secs=3); check()
            ms = M.mission_state() or {}
            ev(f"round {k}: refill at the Village generator: {M.gun_ready()} ammo {ms.get('ammo')}")
        if os.environ.get("LP_STATION", "1") == "1" and not s["driving"] and need_station(ms) and \
                not (STATION_FAILED[0] and ms.get("health", 100) >= LOW_HEALTH and k % 2 == 0):
            station(); ms = check()
        if (ms.get("ammo", 0) > 0 or M.select_gun(4)) and not s["driving"]:
            c = hud_counter()
            # MISSIONS-BATCH2: from 30 left a hitman sits in a VTYPE at 214.5,7.5 with a crack-shot silenced
            # machine gun (his car stands while the player is on foot): the anchors beside it are dropped
            pool = ANCHORS_LATE if (c is not None and 0 <= c <= 30) else ANCHORS
            a = pool[k % len(pool)]
            r = fight(select=hostile, spare=spare, secs=60, done=(round_done if os.environ.get("LP_STATION", "1") == "1" else None), clear=20.0, engage=9.0, close=5.0, far=24.0,
                      anchor=a, leash=7.0, low=70, blast=float(LP_BLAST), close_car=6.0, police="shoot", shot_prefix=f"gf_lp{k}",
                      car_targets=os.environ.get("LP_CAR_TARGETS", "0") == "1")   # mb2_lp6: the VTYPEs shot alight blew up beside him
            st = dict(G.STATS)
            RESULT["rounds"].append(dict(kind="gun", anchor=a, result=r, stats=st))
            ms = M.mission_state() or {}
            ev_count(f"round {k} (gun) at {a}: {r} down {st.get('down')} (health {ms.get('health')}, ammo {ms.get('ammo')}, msg {ms.get('msg')})")
        else:
            # mb1_ra1: 100 rounds gave 3 kills and the refill generator (229.5,68.5) was never
            # reached; the bonus counts BY_ANY_WEAPON, so a car: the Zaibatsu (remap 8) run over
            # on a tour of The Village's level-2 roads (mission_lib.run_over, as DOUBLE-CROSS CRUSH)
            if not s["driving"]:
                s = M.any_car2(world, budget=90); check()
            if not (s and s["driving"]):
                ev(f"round {k}: no gun and no car"); time.sleep(2.0); continue
            P.set_view("third")
            r, n = M.run_over(world, [8], {"2999"}, {"2998"}, (224.6, 20.0), secs=150, patrol=PATROL)
            RESULT["rounds"].append(dict(kind="car", result=r, kills=n))
            ms = M.mission_state() or {}
            ev_count(f"round {k} (car): {r} run over {n} (health {ms.get('health')}, carhp {ms.get('carhp')}, msg {ms.get('msg')})")
            if r == "burning":
                s = D.wait_state()
                if s["driving"]: M.leave_car()
        if k % 3 == 1: M.shot(f"m_lp_round{k}")
    return "timeout"


def main():
    try:
        r = play()
    except (Over, G.JobOver) as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o, ms = G.job_state()
    if o == "complete": r = "complete"
    ms = M.mission_state() or {}
    ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')} msg {ms.get('msg')}")
    for i in range(3):
        M.shot(f"m_lp_end{i}"); time.sleep(0.6)
    RESULT["result"] = r
    with open("/out/lp_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", NAME, r)
    M.mark(f"done labrats_plan={r}")
    return r


if __name__ == "__main__":
    main()
