#!/usr/bin/env python3
"""GANG CAR BANG! (Residential file ste, the Rednecks' red phone 4.5,5.5, ste_rh1.mis), played in the
street views by MISSIONS-BATCH2 (Wave M) with the destroy-vehicle skill (skills/destroy_vehicle.py).

What the script wants (assets-src/missions/ste_m/ste_rh1.mis; texts e.gxt):
  2955 title; GIVE_WEAPON (p1, ROCKET_LAUNCHER, 10); 2160 brief; a Redneck with a machine gun (and his
  group of 6) is made a follower of the player; an arrow to 227.5,217.5 (the SRS zone).
  In the sciegang zone: 2161 and START_BONUS_CHECK (sciegang, no clock, 5, CAR, BY_ANY_WEAPON,
  STRATOSB): wreck 5 SRS Meteors (model 48); 2162 out of the zone (arrow back); 2163 passed;
  2164 failed (2998).
  Then an arrow to 199,25.5 (Zaibatsu Village): in zaibgang: 2165, five Z-Types (VTYPE, model 70);
  2166 out of the zone; 2167 passed; 2168 failed. Then +$70,000, 2999.
The red phone wants Rednecks respect >= 4 bars; skills/gang_respect.exe sets 80 at the start
(developer aid, marked). B2_WARP_PHONE=1 (default) puts him on the street beside the phone with the
developer scene warp (marked WARP): the 160 blocks from the district start are not this job.

Weapons: the job's 10 rockets (one wrecks a car; the trigger is tapped once per shot from 6-10
blocks, never held); after them a gun pickup: the rocket generator in Zaibatsu Village
(229.5,68.5, MOVING_COLLECT_02) for stage 2, the machine-gun generator 4.5,83.5 as the last resort,
then the skill's machine-gun loop.

Run (keys script missions/keys_b2_gang_car_bang.sh):
  SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \\
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \\
  gamerun/grun.sh <name> 1800 missions/keys_b2_gang_car_bang.sh -e DISTRICT=ste -e WARP_OK=0 -e GTA2DX9_SCENE_NO_CAR=1
Frames /out/m_gcb_*.png, marks /out/marks.txt, summary /out/gcb_result.json.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
from skills import destroy_vehicle as DV
from skills import gunfight as G
from skills import shake_police as SP
from missions import b2_common as B

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "ste_rh1"
PHONE = (4.5, 5.5)
R = B.Result("/out/gcb_result.json")
MSG = B.Msgs()
SCI_ZONES = [(219, 164, 36, 90), (120, 157, 99, 97)]
ZAIB_ZONES = [(115, 0, 140, 85), (79, 0, 36, 17), (99, 17, 16, 8)]
METEOR, ZTYPE = 48, 70
ROCKET_WID = 5
ROCKET_GEN = (229.5, 68.5)
# b2_gcb14: the walker's route crossed the raised station plaza at 116-125 x 120-137 (level 2) and he
# died on the tracks at 120.1,132.5 with the escort crowding him: kept off it
M.BLOCKED.update({(x, y) for x in range(115, 127) for y in range(120, 138)})
M.BLOCKED.update({(x, y) for x in range(134, 160) for y in range(19, 32)})   # the bridge at x 135-138 and the deck edge (b2_gcb15)
M.GUN_PICKUPS["ste"] = [(4.5, 83.5, 2)]    # b2_gcb7: nothing was picked up at the rocket generator 229.5,68.5 (z 3: a roof)
FAIL = {"2998", "2164", "2168"} | {str(k) for k in range(6150, 6160)}
# 615x: DECLARE_GANG_ONE_DEATH_BASE_BRIEF (p1, 6150), the Rednecks' line after the player dies or is
# arrested on their job (b2_gcb6/12 died, then 6151; b2_gcb13 was arrested after a rocket, then 6156)
STAGES = [
    dict(name="meteors", zones=SCI_ZONES, model=METEOR, start="2161", passed="2163",
         arrow=(227.5, 217.5),
         patrol=[(227.5, 210.5), (200.5, 222.5), (175.5, 200.5), (160.5, 230.5), (235.5, 240.5), (190.5, 175.5), (140.5, 190.5)]),
    # the hunt on the ground roads of the zone's south part (rows 62-77, x 160-250): b2_gcb15 walked
    # off the bridge pavement at 142.6,25.6 into the water on a patrol leg to 150,20 (the village
    # itself is a level-2 deck edged by water)
    dict(name="ztypes", zones=ZAIB_ZONES, model=ZTYPE, start="2165", passed="2167",
         arrow=(199.5, 64.5),
         patrol=[(199.5, 63.5), (172.5, 63.5), (228.5, 63.5), (215.5, 76.5), (185.5, 76.5), (240.5, 72.5)]),
]


class Over(Exception):
    pass


class Passed(Exception):
    pass


CUR = {"passed": None}
TRAVEL = os.environ.get("B2_GCB_TRAVEL", "walk")


FROZEN = {"t": 0.0, "fr": -1, "since": None}


def frozen():
    """the renderer's frame count has not moved for a minute (b2_gcb17: gta2.exe crashed under Wine at
    the WASTED screen and the runner walked a frozen game for 9 minutes)"""
    now = time.time()
    if now - FROZEN["t"] < 20: return False
    FROZEN["t"] = now; fr = M.frames_rendered()
    if fr != FROZEN["fr"]: FROZEN["fr"] = fr; FROZEN["since"] = now; return False
    return FROZEN["since"] is not None and now - FROZEN["since"] > 60


def check():
    if frozen(): raise Over("game frozen (gta2.exe stopped drawing)")
    keys = MSG.keys()
    if "2999" in keys or "1124" in keys: raise Over("complete")
    if any(k in FAIL for k in keys): raise Over("failed")
    if CUR["passed"] and CUR["passed"] in keys: raise Passed(CUR["passed"])
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: raise Over("dead")
    if M.LIVES0[0] is not None and ms.get("lives", 99) < M.LIVES0[0]: raise Over("dead (life lost)")
    return ms


def in_zones(x, y, zones):
    return any(zx <= x < zx + zw and zy <= y < zy + zh for zx, zy, zw, zh in zones)


def rockets(ms=None):
    ms = ms or M.mission_state() or {}
    return ms.get("ammo", 0) if ms.get("wid") == ROCKET_WID else 0


def select_rocket():
    for _ in range(8):
        ms = M.mission_state() or {}
        if ms.get("wid") == ROCKET_WID and ms.get("ammo", 0) > 0: return True
        tap("x", 0.15); time.sleep(0.5)
    return False


STATS = dict(rockets_fired=0, wrecks=0, by_rocket=0, by_gun=0, pickups=0)


def lie_low(secs=90, why=""):
    """on foot, away from the police until the wanted level is gone (b2_gcb13: arrested beside a cop
    car after the second Meteor): legs to a road point on the far side from the police seen"""
    t0 = time.time(); n = 0
    while time.time() - t0 < secs / D.SPEED:
        check()
        ms = M.mission_state() or {}
        s = D.wait_state()
        nc, no, dmin, cen = SP.police_near(s, 30.0, 20.0)
        if ms.get("wanted", 0) == 0 and (nc + no == 0 or dmin > 18):
            if n: R.ev(f"lie low: clear after {time.time() - t0:.0f}s ({n} legs)")
            return True
        p = SP._road_point_away(world, s, cen or (s["x"] + 1, s["y"]), rmin=15, rmax=30)
        n += 1
        if n == 1: R.ev(f"lie low ({why}): wanted {ms.get('wanted')}, police {nc} cars {no} officers nearest {dmin:.0f}")
        if p: M.walk3(world, p[0], p[1], None, tol=2.0, budget=12)
        else: time.sleep(1.0)
    return False


SAID = [0.0]
SKIP = {}      # target id -> time until which it is not chased (no shot found at it)


def rocket_engage(tgt_model, zones, secs=60):
    """on foot, rockets in hand: walk at the nearest target of the model and tap the trigger once
    when it is 5-8 blocks off and the walk's own facing points at it (b2_gcb7: four rockets fired
    standing, after turns on the spot, all missed a parked Meteor at 9-11 blocks: a standing ped's
    logged facing is not his real one, a walking ped's is). Returns True when a target was wrecked."""
    t0 = time.time(); last_fire = 0.0
    while time.time() - t0 < secs:
        check()
        s = D.wait_state()
        if s["driving"]: return False
        ms = M.mission_state() or {}
        if ms.get("wanted", 0) > 0 and SP.police_near(s, 25.0, 18.0)[2] < 25:
            # b2_gcb19: a missed rocket at a moving Meteor raised the wanted level and a cop on foot
            # shot him from 100 to 10 while the hunt went on. Only with police near: b2_gcb22 kept
            # wanted 1 for 17 minutes with nobody after him and the hunt stood still
            lie_low(90, "wanted, police near"); continue
        if rockets(ms) <= 0 and not select_rocket(): return False
        # a burning car (fire, or under the 16000 the game sets them alight at) blows up by itself
        # within seconds: never a target, and kept 7 blocks off (b2_gcb23: a rocket at a Meteor on
        # 1739 hp from 6 blocks, its blast took him from 96 to 0)
        for b in M.cars():
            if (b["fire"] > 0 or 0 < b["hp"] < 16000) and b["driver"] != "P" and math.hypot(b["x"] - s["x"], b["y"] - s["y"]) < 7:
                DV.back_off(s, b["x"], b["y"], 8.0); s = D.wait_state()
        ts = [c for c in DV.targets(models={tgt_model}) if SKIP.get(c["id"], 0) < time.time()
              and c["fire"] == 0 and c["hp"] >= 16000]
        if not ts: return False
        c = min(ts, key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
        if time.time() - t0 > 40 / D.SPEED:
            # b2_gcb16: 9 minutes round one Meteor with no shot taken (no reason logged): give it up a while
            SKIP[c["id"]] = time.time() + 90 / D.SPEED
            R.ev(f"no shot at {c['id']} in 40 s (d {math.hypot(c['x'] - s['x'], c['y'] - s['y']):.1f}): skipped for 90 s")
            return False
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d > 14:
            M.walk3(world, c["x"], c["y"], None, tol=10.0, budget=min(20, 4 + d)); continue
        if d < 4.5:
            DV.back_off(s, c["x"], c["y"], 7.0); continue
        lead = min(2.0, 0.6 * c["v"])
        ax, ay = c["x"] + c["hx"] * lead, c["y"] + c["hy"] * lead
        # the gcb15 way (5 Meteors in 12 minutes): a slice of walking at it keeps the facing true,
        # the rocket goes off while walking when the walk's facing points at it
        M._aim_walk(ax, ay, fire=False, walk=True, secs=0.35)
        s = D.wait_state()
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if time.time() - SAID[0] > 5:
            SAID[0] = time.time()
            say(f"rocket_engage: {c['id']} d {d:.1f} angle {D.angle_to(s, ax, ay):.2f} v {c['v']:.1f} clear {G.clear_shot(world, s, c['x'], c['y'])}")
        if c["v"] > 1.0 or not (4.5 <= d <= 8.5) or abs(D.angle_to(s, ax, ay)) > 0.12 or time.time() - last_fire < 2.5 / D.SPEED:
            continue
        # nobody of ours in the line of fire (a rocket into an escort a block away killed him, b2_gcb17):
        # hold the shot and keep walking
        if any(p["hp"] > 0 and p["car"] is None
               and 0.2 < ((p["x"] - s["x"]) * (c["x"] - s["x"]) + (p["y"] - s["y"]) * (c["y"] - s["y"])) / d < d - 1.0
               and abs(((p["x"] - s["x"]) * (c["y"] - s["y"]) - (p["y"] - s["y"]) * (c["x"] - s["x"])) / d) < 0.8
               for p in M.peds()):
            continue
        nc, no, dmin, _ = SP.police_near(s, 20.0, 14.0)
        if nc + no:
            lie_low(60, "police near the target"); continue
        if not G.clear_shot(world, s, c["x"], c["y"]):
            M.walk3(world, c["x"], c["y"], None, tol=5.0, budget=6); continue
        hp0 = c["hp"]; n0 = rockets()
        xdo("keydown", "Up"); xdo("keydown", "Control_L"); time.sleep(0.12); xdo("keyup", "Control_L"); xdo("keyup", "Up")
        last_fire = time.time(); STATS["rockets_fired"] += 1
        time.sleep(1.0 / D.SPEED)
        q = next((x for x in M.cars() if x["id"] == c["id"]), None)
        say(f"rocket at {c['id']} (m{c['model']}) d {d:.1f} v {c['v']:.1f}: hp {hp0} -> {q['hp'] if q else 'gone'}; rockets {n0} -> {rockets()}")
        if q is None or q["hp"] <= 0 or (q["hp"] < hp0 and q["fire"] > 0):
            STATS["wrecks"] += 1; STATS["by_rocket"] += 1
            R.ev(f"rocket hit {c['id']} (m{c['model']}) at {c['x']:.1f},{c['y']:.1f} (hp {q['hp'] if q else 'gone'})")
            M.shot(f"gcb_wreck_{STATS['wrecks']}")
            time.sleep(1.0)
            if (M.mission_state() or {}).get("wanted", 0) > 0: lie_low(40, "after the hit")
            return True
    return False


def target_visible(model, zones):
    s = D.wait_state()
    return any(math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 22 and SKIP.get(c["id"], 0) < time.time()
               and c["fire"] == 0 and c["hp"] >= 16000
               for c in DV.targets(models={model}))


def into_car():
    s = D.wait_state()
    if s["driving"]: return s
    return B.any_car(world, budget=240, view_switch=P.view_switch)


def drive_to(x, y, until=None, budget=300):
    s = into_car()
    if not s or not s["driving"]: return s
    P.FP["until"] = 0.0
    return M.drive3(world, x, y, tol=4.0, budget=budget, view_switch=P.view_switch, until=until)


def stage(st):
    """get into the zone (arrow), then hunt the model: patrol by car until one is in sight, out,
    rockets (or the skill's gun loop) until the script's 'passed' message"""
    CUR["passed"] = st["passed"]
    R.d["stage"] = st["name"]; R.ev(f"stage {st['name']}: to the zone (arrow {st['arrow']})")
    zx, zy = st["arrow"]
    cell = M.street_cell_near(world, zx, zy, radius=10) or (zx, zy, 2)
    s = D.wait_state(); legs = 0
    while not in_zones(s["x"], s["y"], st["zones"]) and legs < 30:
        legs += 1
        if TRAVEL == "car":
            s = drive_to(cell[0], cell[1], until=lambda: (lambda q: in_zones(q["x"], q["y"], st["zones"]))(D.wait_state()), budget=420)
        else:
            # on foot (b2_gcb5/6: three borrowed cars burned on the 250-block drive, one with him beside
            # it; the walker is steadier and the Redneck escort keeps up on foot)
            s = M.walk3(world, cell[0], cell[1], None, tol=2.0, budget=45)
        check(); s = D.wait_state()
    R.ev(f"stage {st['name']}: in the zone at {s['x']:.1f},{s['y']:.1f} (start message {st['start']} seen: {MSG.saw({st['start']})})")
    M.shot(f"gcb_{st['name']}_zone")
    k = 0; t0 = time.time()
    while time.time() - t0 < 1500:
        check()
        s = D.wait_state()
        if (M.mission_state() or {}).get("wanted", 0) > 0 and SP.police_near(s, 25.0, 18.0)[2] < 25: lie_low(90, "wanted, police near")
        if target_visible(st["model"], st["zones"]):
            if s["driving"]:
                hold("Down", 0.5); M.leave_car(); M.ensure_view("third")
                R.ev("out of the car: a target in sight")
            M.shot(f"gcb_{st['name']}_engage")
            if rockets() > 0 or select_rocket():
                rocket_engage(st["model"], st["zones"], secs=45)
                continue
            # no rockets: the rocket generator in Zaibatsu Village first, then the skill's gun loop
            if not M.gun_ready() and not M.select_gun():
                R.ev("out of rockets and rounds: to a pickup")
                near = ROCKET_GEN if st["model"] == ZTYPE else None
                M.fetch_gun(world, budget=300, near=near); STATS["pickups"] += 1
                continue
            r = DV.destroy(world, models={st["model"]}, count=1, check=check, secs=90, engage=10.0,
                           stand_off=4.0, view_switch=P.view_switch, shot_prefix=f"gcb_{st['name']}_dv", ram=False)
            R.ev(f"destroy (gun): {r}")
            if r == "done": STATS["wrecks"] += 1; STATS["by_gun"] += 1
            continue
        # nothing in sight: patrol the zone by car, stopping as soon as one shows up
        p = st["patrol"][k % len(st["patrol"])]; k += 1
        ms = M.mission_state() or {}
        say(f"hunt: {st['name']} weapon {ms.get('weapon')} ammo {ms.get('ammo')} wanted {ms.get('wanted')} health {ms.get('health')} msgs {MSG.keys()[-3:]}")
        cell = M.street_cell_near(world, p[0], p[1], radius=10)
        if not cell: continue
        say(f"patrol to {cell[0]},{cell[1]}")
        if TRAVEL == "car":
            drive_to(cell[0], cell[1], until=lambda: target_visible(st["model"], st["zones"]), budget=150)
        else:
            for _ in range(8):
                check()
                if target_visible(st["model"], st["zones"]): break
                s = M.walk3(world, cell[0], cell[1], None, tol=2.0, budget=12)
                if math.hypot(cell[0] - s["x"], cell[1] - s["y"]) < 3: break
    return "timeout"


# The red phone stands on a strip of field on the north shore, reached only by a one-block wooden
# jetty (column 6, rows 8-16) over the water (b2_gcb2: the shared walker's unstick turn walked him
# off the jetty, he drowned and lost a life). The approach is walked point by point, straight up
# the jetty's centre line, with no side-step unstick.
JETTY = [(4.5, 19.5), (4.5, 18.5), (6.5, 18.5), (6.5, 17.5), (6.5, 16.5), (6.5, 12.0), (6.5, 7.6), (5.5, 6.5), (4.5, 6.4)]
# b2_gcb3: (4,17) has a fence on its south side, (5,17) on its east; the jetty cells (6,16)-(6,17)
# have fences west and east: the walk enters column 6 at row 18 and turns north standing still


def face(x, y, tol=0.12, tries=10):
    for _ in range(tries):
        s = D.wait_state(); a = D.angle_to(s, x, y)
        if abs(a) < tol: return True
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, max(0.04, min(abs(a) / max(D.rate, 2.0), 0.3))); time.sleep(0.25)
    return False


def careful_walk(pts, tol=0.3, secs=60, look=0.6):
    """segment by segment with Up held and pure-pursuit steering on a point `look` blocks ahead ON
    the segment, so a sideways drift turns into a heading error at once (b2_gcb4 drifted off the
    one-block jetty steering at the far end point; b2_gcb8 stepped in pulses after turns on the
    spot, whose logged facing is stale for a standing ped, and walked off at 6.0,10.7 under load).
    Steering pulses are short; a lateral error over 0.28 stops him and turns him back toward the
    line before he walks on."""
    M.ensure_view("classic")
    s = D.wait_state(); p0 = (s["x"], s["y"])
    for (x, y) in pts:
        L = math.hypot(x - p0[0], y - p0[1]) or 1e-6
        ux, uy = (x - p0[0]) / L, (y - p0[1]) / L
        t0 = time.time(); up = False; worst = 0.0
        try:
            while time.time() - t0 < secs:
                s = D.wait_state()
                if math.hypot(x - s["x"], y - s["y"]) < tol: break
                tp = (s["x"] - p0[0]) * ux + (s["y"] - p0[1]) * uy
                lat = (s["x"] - p0[0]) * uy - (s["y"] - p0[1]) * ux
                worst = max(worst, abs(lat))
                la = min(L, max(0.0, tp) + look)
                lx, ly = p0[0] + ux * la, p0[1] + uy * la
                a = D.angle_to(s, lx, ly)
                if abs(lat) > 0.2 and L > 1.5:
                    if up: xdo("keyup", "Up"); up = False
                    lx, ly = p0[0] + ux * min(L, max(0.0, tp) + 0.3), p0[1] + uy * min(L, max(0.0, tp) + 0.3)
                    face(lx, ly, tol=0.1, tries=4)
                    hold("Up", 0.1); continue
                if abs(a) > 0.6:
                    if up: xdo("keyup", "Up"); up = False
                    face(lx, ly, tol=0.15, tries=4); continue
                if not up: xdo("keydown", "Up"); up = True
                if abs(a) > 0.06:
                    key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                    xdo("keydown", key); time.sleep(min(abs(a) / max(D.rate, 2.0), 0.06)); xdo("keyup", key)
                time.sleep(0.04)
        finally:
            if up: xdo("keyup", "Up")
        s = D.wait_state(); p0 = (x, y)
        say(f"careful_walk: at {s['x']:.2f},{s['y']:.2f} for {x},{y} (worst lateral {worst:.2f})")
    return D.wait_state()


def to_phone(entry):
    s = D.wait_state()
    road = (4.5, 22.5, 1)
    if math.hypot(road[0] - s["x"], road[1] - s["y"]) > 30:
        if os.environ.get("B2_WARP_PHONE", "1") == "1":
            P.set_view("classic")
            for _ in range(5):
                s2 = M.scene_warp(road[0], road[1], road[2], "B2_WARP_PHONE: the road south of the Rednecks' red phone; the job starts at the phone")
                # b2_gcb9: the container was paused by the governor right after the warp key and the
                # warp line was read against a stale position: look again after a settle
                time.sleep(3.0); s2 = D.wait_state()
                if s2 and math.hypot(s2["x"] - road[0], s2["y"] - road[1]) < 8: break
                time.sleep(2.0)
            R.ev(f"phone warp to {road}")
        else:
            M.walk3(world, road[0], road[1], None, tol=1.5, budget=600)
    s = D.wait_state()
    if math.hypot(road[0] - s["x"], road[1] - s["y"]) > 8:
        return False, f"not at the road below the phone ({s['x']:.1f},{s['y']:.1f})"
    M.set_avoid_phones(world, keep=PHONE)
    careful_walk(JETTY)
    P.nudge_to(PHONE[0], PHONE[1], tol=0.12, tries=16)
    t0 = time.time()
    while time.time() - t0 < 8 and not MSG.saw({"2955", "2160"}): time.sleep(0.2)
    if MSG.saw({"2955", "2160"}):
        # straight back over the jetty, still in the classic view: the job's Redneck and his group of
        # six spawn at 11.5,2.5 and crowd round their new leader; b2_gcb10 spent 7 s on view changes
        # first and they pushed him off the jetty at 6.4,9 (frames shot_150/155)
        M.mark("phone answered: back over the jetty ahead of the Redneck escort")
        careful_walk(list(reversed(JETTY))[1:] + [(4.5, 22.5)])
    P.set_view("third")
    M.set_avoid_phones(world, keep=None)
    return MSG.saw({"2955", "2160"}), (MSG.keys() or [""])[-1]


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: GANG CAR BANG! (missions/b2_gang_car_bang.py, skills/destroy_vehicle.py)")
    M.mark("developer aid: Rednecks respect set to 80 (red phone needs 4 bars; a fresh game has 0)")
    B.respect("0", 80)          # gang 0 = redngang (first SET_GANG_INFO); its name reads back unprintable
    ok, key = to_phone(entry)
    MSG.poll()
    M.shot("gcb_phone")
    if not MSG.saw({"2955", "2160"}):
        return f"phone not answered ({ok}, {key}, {MSG.keys()[-5:]})"
    R.d["stage"] = "phone"; R.ev(f"phone answered ({MSG.keys()[-4:]})")
    ms = M.mission_state() or {}
    M.LIVES0[0] = ms.get("lives")
    R.ev(f"weapon {ms.get('weapon')} wid {ms.get('wid')} ammo {ms.get('ammo')}")
    for st in STAGES:
        try:
            r = stage(st)
        except Passed:
            R.ev(f"stage {st['name']} passed ({st['passed']})"); B.shots(f"gcb_{st['name']}_passed", n=2)
            continue
        return f"stage {st['name']} {r}"
    # after the last pass the 2999 follows
    t0 = time.time()
    while time.time() - t0 < 20:
        check(); time.sleep(0.5)
    return "passed both, no 2999"


def main():
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    finally:
        xdo("keyup", "Control_L")
    if r == "complete": B.shots("gcb_complete", n=4, gap=0.5)
    ms = M.mission_state() or {}
    R.ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')}")
    time.sleep(2.0); M.shot("gcb_end")
    R.d["result"] = r; R.d["stats"] = STATS; R.d["messages"] = MSG.keys()
    R.d["skill_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in DV.EVENTS]
    R.save()
    say("RESULT", NAME, r, STATS)
    M.mark(f"done b2_gang_car_bang={r}")


if __name__ == "__main__":
    main()
