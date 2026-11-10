#!/usr/bin/env python3
"""BANK ROBBERY! (wil_ye2) with its guard fight done by the kill-marked skill (SKILL-KILLMARK).

    python3 /work/missions/bank_robbery_km.py        (inside the container, after to_level.sh)

The job's own runner (missions/bank_robbery.py, PLAYTHROUGH-10) is used unchanged for everything
around the fight: the phone, the GRAHAM, the bank box, the pre-positioned getaway, the respray and
the safehouse. Its hand-written guard loop is replaced by `skills/kill_marked.kill_marked` with the
job's facts as arguments only: the targets (marked `crim/police` peds near the bank walk; Hiroshi,
the Yakuza inside man who walks out behind them, is spared and never in the line of fire), the
stairs (the job's CLIMB points to level 2) and the walk's fire spots. Frames /out/m_km_*.png and
/out/m_br_*.png, marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from missions import bank_robbery as BR
from skills import kill_marked as K
from skills import shake_police as SP

world_ref = [None]     # the World for follow_path's overtaking (set in run)

say, hold, xdo = D.say, D.hold, D.xdo


def is_guard(p):
    return p["gang"] == "police" and p["type"] != "cop" and \
        min(math.hypot(p["x"] - gx, p["y"] - gy) for gx, gy in BR.GUARDS) < 8


def is_spare(p):
    # Hiroshi: a Yakuza out of door16 beside the guards; any non-target near the walk
    return p["gang"] == "yakuza" and math.hypot(p["x"] - 186.0, p["y"] - 175.0) < 6


def job_check():
    return BR.check()


CAR = {"model": 18, "at": None}      # the GRAHAM (model 18)
# kmg1: the GRAHAM left in the box facing east stood on row 180, a westbound lane (traffic keeps right:
# rows 179-180 run west, 181-182 east); the first second of the getaway was a head-on with a car in
# that lane, drive3 re-routed back west round it, two officers reached the car and pulled him out.
# The getaway car is now parked in the eastbound lane and the first 15 blocks are a launch: throttle
# held, steering along the lane, no re-routing.
GETAWAY_PARK = (197.6, 181.6)
GETAWAY_LANE_Y = 181.6
GETAWAY_LAUNCH_X = 211.0
# kmg5: the launch worked, then drive3's leg into the avenue slowed for the corner after a knock and an
# officer had him out at 217.4,184.6. The whole run from the bank to the bay is now one hand-placed
# path driven without stops (follow_path): east on row 181, right into the southbound cells 215-216 of
# the column-216 avenue, right again into the westbound row 213, to the point in front of the 204 bay.
# kmg6: the path ended at 206.8,213.0 at full speed heading west; lane_in's turn into the bay overshot
# to x 202, swung back onto the pavement beside the bay and ran out of time. The path now carries on
# into the bay's line itself (across the median at row 214) at the corner speed, and lane_in only
# does the last straight.
GETAWAY_PATH = [(213.5, 181.6), (216.0, 184.2), (216.0, 210.6), (213.4, 213.0), (208.0, 213.0),
                (204.5, 216.0), (204.5, 218.0)]
GETAWAY_LEGS = [(216.5, 187.0)]   # into the column-216 avenue southbound (cells 215-216); then the bay leg

# MISSION-GETAWAY (9 Nov, mg_sp2, mg_km3): the job's CLIMB line (bank_robbery.CLIMB, 193.6,178.0 ->
# 192.3,177.8) runs over the game's own girder object at 193.20,177.50 (`collide: near ...
# obj_girder@193.20,177.50/0.28`, a solid map object since FIX-COLLISION) standing in the middle of
# cell 193,177, the only way onto the flight (a wall along y 178 west of x 193); the walker stood
# pinned against it (SKILL-POLICE's 193.4,177.2 in sp11-19; mg_sp2 pinned 50 s and shot dead by the
# guards). A trash can stands on the flight's line at 191.14,177.50. The climb now threads the gap
# north of the girder (y 177.85-178.15; the mailbox at 193.10,178.50 bounds it on the other side) and
# keeps to the north half of the flight.
# mg_fb2: from the car (199.7,180.9) the first leg to 194.4,178.15 was blocked at 197.6,179.8 twice
# and the router's climb that followed walked into the girder again (cell centres): the walk now
# steps onto the pavement first, square to the kerb
# mg_km14: with path_walk's 0.45 tolerance the flight's points (y 177.8-177.85) counted as reached from
# y 178.2, on the pavement below the wall along y 178 (x 190-193): he walked under the flight to x 190.5
# and the leg north failed three times. The flight's points sit at y <= 177.78 and are walked with
# a 0.3 tolerance (walk_pts): from the far side of the wall (y >= 178.085) none can be "reached"
CLIMB_KM = [(198.3, 178.5), (196.4, 178.45), (194.4, 178.15), (193.5, 178.05), (192.8, 177.7), (192.0, 177.7), (191.3, 177.78),
            (190.6, 177.65), (190.4, 176.4), (190.3, 175.4)]
STAIR_TOL = 0.3
# (mg_km5: the old last point 189.0,175.1 was 3.5 blocks from the guards; one walked up to 0.8 and shot
# him while the walker finished the leg. The climb ends at the flight's top, 4.8 off; the skill's
# fire spots start at 190.5,175.0)
# mg_km4, mg_km8: the fight leaves him west of the flight's top (187.9-188.1,175.9) and the first
# descent point was missed from there; the descent starts along the walk
DESCEND_KM = [(189.2, 175.25), (190.3, 175.4), (190.4, 176.4), (190.6, 177.65), (191.3, 177.78), (192.0, 177.7), (192.8, 177.7),
              (193.5, 178.05), (194.4, 178.15)]

def walk_pts(points, secs_each=6.0, tol=STAIR_TOL):
    """BR.path_walk with a tighter tolerance on the way points (the last 0.3 too)"""
    for k, (x, y) in enumerate(points):
        s, ok = M.cruise_to(x, y, tol=tol, secs=secs_each, stop=(k == len(points) - 1))
        if not ok:
            xdo("keyup", "Up"); say(f"walk_pts: missed {x},{y} (at {s['x']:.2f},{s['y']:.2f} z {s['z']:.2f})"); return False
    xdo("keyup", "Up")
    return True


GAP_PTS = [(193.5, 178.05), (192.8, 177.7), (192.0, 177.7), (191.3, 177.78)]   # the stair foot past the girder


def step_to(x, y, tol=0.25, tries=24):
    """MISSIONS-BATCH2: small aimed steps onto a point (turn in place, then a short Up pulse), no
    sideways unstick. mb2_km2-km6: cruise_to stalled 0.4-0.8 from the gap point 192.8,177.7 (its
    unstick shoves him off the line) in the chase view and in the classic view alike, 5 of 5 climbs"""
    for _ in range(tries):
        s = D.wait_state()
        if not s or s["driving"]: return s, False
        d = math.hypot(x - s["x"], y - s["y"])
        if d < tol: return s, True
        a = D.angle_to(s, x, y)
        if abs(a) > 0.3:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            hold(key, min(abs(a) / max(D.rate, 2.0), 0.3)); time.sleep(0.3)
            hold("Up", 0.08); time.sleep(0.35)
            continue
        hold("Up", max(0.08, min(0.35, (d - 0.05) / 1.9))); time.sleep(0.4)
    s = D.wait_state()
    return s, bool(s and math.hypot(x - s["x"], y - s["y"]) < tol)


def thread_gap():
    """the gap points by step_to, then the rest of the flight by walk_pts"""
    for (x, y) in GAP_PTS:
        s, ok = step_to(x, y)
        if not ok:
            M.mark(f"climb: step_to missed {x},{y} (at {s['x']:.2f},{s['y']:.2f})" if s else "climb: step_to, no state")
            return False
    M.mark("climb: the gap threaded by steps")
    return walk_pts(CLIMB_KM[CLIMB_KM.index(GAP_PTS[-1]) + 1:], secs_each=9.0)


def climb_to_walk(tries=3, resume=False):
    """the climb to the level-2 walk by the job, before the skill: CLIMB_KM legs of up to 9 s each
    (the skill's path_walk gives 6 s and one retry, then its router climb heads for the girder: mg_km7,
    mg_km8, mg_fb3 pinned at 193.4,177.6 until the warp fallback, refused); a missed leg resumes from
    the nearest point still ahead after a step back. True when on the walk's level"""
    for k in range(tries):
        s = D.wait_state()
        if K.level_of_z(s["z"]) == BR.WALK_LEVEL: return True
        # resume at the first point beyond the nearest one (the points run east to west, then north)
        i = min(range(len(CLIMB_KM)), key=lambda j: math.hypot(CLIMB_KM[j][0] - s["x"], CLIMB_KM[j][1] - s["y"]))
        i = min(i + 1, len(CLIMB_KM) - 1) if (k or resume) else 0
        if resume and k == 0 and math.hypot(s["x"] - 193.3, s["y"] - 177.9) < 1.5:
            # MISSIONS-BATCH2 (mb2_km9): the classic retry walked back to the first point 5 blocks east
            # and lost the line; from the girder's side it steps straight through the gap
            if thread_gap(): break
            continue
        if walk_pts(CLIMB_KM[i:], secs_each=9.0):
            break
        s = D.wait_state(); M.mark(f"climb: missed a leg at {s['x']:.1f},{s['y']:.1f} (try {k + 1})")
        if K.level_of_z(s["z"]) == BR.WALK_LEVEL: return True
        if os.environ.get("BR_STEP_GAP", "1") == "1" and math.hypot(s["x"] - 193.3, s["y"] - 177.9) < 1.5:
            if thread_gap(): break
            s = D.wait_state()
            if K.level_of_z(s["z"]) == BR.WALK_LEVEL: return True
        M.cruise_to(s["x"] + 0.8, s["y"] + 0.3, tol=0.4, secs=2.0)     # a step back east, off whatever held him
    s = D.wait_state()
    return K.level_of_z(s["z"]) == BR.WALK_LEVEL


def to_car(world, check=True):
    """back into the GRAHAM where it is now: the model read at the wheel, found in `view: cars`
    nearest to where it was last seen (km2: a gang member took it 17 s into the getaway and the
    job runner walked to where it had been parked)"""
    s = D.wait_state()
    if s["driving"]: return s
    at = CAR["at"] or BR.CAR0
    if CAR["model"] is not None:
        cs = [c for c in M.cars() if c["model"] == CAR["model"]]
        if cs:
            c = min(cs, key=lambda c: math.hypot(c["x"] - at[0], c["y"] - at[1]))
            at = (c["x"], c["y"])
    M.mark(f"back to the GRAHAM at {at[0]:.1f},{at[1]:.1f}")
    s = None
    if os.environ.get("BR_DOOR_ENTER", "1") == "1":
        s = door_enter(world, at)
    if not (s and s["driving"]):
        s = M.enter_car3(world, at[0], at[1], budget=60)
    if check: s = board_graham(world, s)
    if s and s["driving"] and in_graham() is not False:
        BR.FP["until"] = -1; M.ensure_view("third"); remember_car()
    return s

GRAHAM = 18          # the job's car model (carmodel in the mission line)


def door_enter(world, at):
    """MISSIONS-BATCH2: into the GRAHAM from its driver's door. mb2_km3 (a police car: busted), mb2_km7
    (models 53, 36: 1125), and km4/km5 (models 68/36/69, recovered) got into a car queued beside or
    behind the parked GRAHAM: enter_car3 presses Return 1.5 blocks off the car's centre, and the game
    takes the nearest door. Here: the point 1.0 off the left flank (the driver's side) by walk3 and
    aimed steps, then Return"""
    cs = [c for c in M.cars() if c["model"] == GRAHAM and math.hypot(c["x"] - at[0], c["y"] - at[1]) < 3.0]
    if not cs: return None
    c = min(cs, key=lambda c: math.hypot(c["x"] - at[0], c["y"] - at[1]))
    hx, hy = c.get("hx", 1.0), c.get("hy", 0.0)
    dx, dy = c["x"] + hy * 1.0 + hx * 0.2, c["y"] - hx * 1.0 + hy * 0.2
    M.mark(f"door_enter: the GRAHAM at {c['x']:.1f},{c['y']:.1f} heading {hx:.2f},{hy:.2f}; its door {dx:.1f},{dy:.1f}")
    M.walk3(world, dx, dy, None, tol=0.8, budget=40)
    s, ok = step_to(dx, dy, tol=0.35, tries=12)
    D.tap("Return", 0.3)
    for k in range(20):
        time.sleep(0.25); s = D.wait_state()
        if s and s["driving"]: break
    return s

def in_graham(wait=2.0):
    """True when the car he sits in is the GRAHAM; None while the mission line has no model yet"""
    t0 = time.time()
    while True:
        m = (M.mission_state() or {}).get("carmodel", -1)
        if m is not None and m >= 0: return m == GRAHAM
        if time.time() - t0 > wait: return None
        time.sleep(0.25)

def board_graham(world, s):
    """kmg11: with the GRAHAM parked in a live lane, Return beside it put him in a model-56 car queued
    next to it; he resprayed that (wanted 0) while the script asked for the GRAHAM (1658). Out of any
    other car and into the GRAHAM by its model"""
    for k in range(3):
        if not (s and s["driving"]): return s
        ok = in_graham()
        if ok is not False: return s
        model = (M.mission_state() or {}).get('carmodel')
        M.mark(f"wrong car (model {model}): out, to the GRAHAM")
        if os.environ.get("BR_CLEAR_WRONG", "1") == "1" and model not in SP.POLICE_MODELS:
            # MISSIONS-BATCH2 (mb2_km13: five boardings of the same model-69 car stopped 0.8 off the
            # GRAHAM's door, at 198.7,180.5): the car he is in is the one in the way; move it 3 blocks
            # off (away from the GRAHAM, forward or back) before he gets out
            s2 = D.wait_state(); at = CAR["at"] or BR.CAR0
            hx, hy = M.heading(s2)
            key = "Down" if (at[0] - s2["x"]) * hx + (at[1] - s2["y"]) * hy > 0 else "Up"
            hold(key, 1.4 / max(D.SPEED, 1.0)); time.sleep(0.5)
            s2 = D.wait_state(); M.mark(f"wrong car moved off ({key}) to {s2['x']:.1f},{s2['y']:.1f}")
        M.leave_car(); time.sleep(0.6); s = to_car(world, check=False)
    return s

def remember_car():
    s = D.wait_state(); ms = M.mission_state() or {}
    if s and s["driving"] and ms.get("carmodel", -1) == GRAHAM:
        CAR["model"] = GRAHAM; CAR["at"] = (s["x"], s["y"])

def roll_in(x, y, secs=25, until=None):
    """into a drive-through shop without stopping: Up held all the way, steering pulses toward
    (x, y), the handbrake once inside (km1: the drive stopped at the tunnel mouth with officers
    1-1.5 blocks off, he was pulled out and arrested, 1666)"""
    t0 = time.time()
    xdo("keydown", "Up")
    try:
        while time.time() - t0 < secs:
            s = D.wait_state()
            if not s or not s["driving"]: return s
            BR.check()
            if until and until(): return s
            if abs(s["x"] - x) < 0.45 and abs(s["y"] - y) < 0.5:
                xdo("keyup", "Up"); hold("space", 0.4); return s
            hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 0.7:
                # not lined up (km6: arriving along row 216 at speed, the Up-held turn into the
                # one-cell tunnel circled at its mouth until an officer pulled him out): stop,
                # point the nose with reverse/forward pulses, then on
                xdo("keyup", "Up"); hold("space", 0.3)
                BR.turn_car_toward(x, y, secs=12); xdo("keydown", "Up"); continue
            if abs(a) > 0.08:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.25, abs(a) * 0.4)); xdo("keyup", key)
            time.sleep(0.12)
    finally:
        xdo("keyup", "Up")
    return D.wait_state()


# Each respray block is four one-cell drive-through bays under one roof (wil.mis): at row 221 the
# bays at columns 200/202/204/206 are the machine-gun, BOMB, respray (CAR_SHOP 10) and oil-slick
# shops, and the same at row 160 (82/84/86/88; respray 86). km6 swung into the shop turning off
# row 216 at speed, ended in the 202 bay, paid $5,000 for a car bomb (money 5040 -> 41, wanted
# still 2: no money left for the respray), and the reverse pulses of the turn backed him out into
# an officer (1666, arrest). The bay is now entered only lined up: stop on the carriageway in
# front of it, turn there, then a straight run down the bay's centre line.
BAYS = {(204.5, 221.5): +1, (86.5, 160.5): -1}     # shop -> direction along y into the bay

# kmg2: the drive to a point in front of the 204 bay on the eastbound row 215 was 69 blocks (west on
# row 213 to the junction at column 186 and back), in a queue, and the officers had him 1 s after the
# turn-in stop. The 204 bay is now approached on the westbound row 213, the leg off the column-216
# avenue, and turned into without a stop (the bay's line crosses the median at row 214).
BAY_PRE = {(204.5, 221.5): (206.8, 213.0), (86.5, 160.5): (86.5, 166.5)}

def bay_pre(shop):
    return BAY_PRE[shop]

def speed(prev, s, dt):
    return math.hypot(s["x"] - prev["x"], s["y"] - prev["y"]) / max(dt, 1e-3)

class Speedo:
    """speed over the last 0.4 s (the state line comes every few frames: two reads of the same
    line gave a speed of 0 and a false stall)"""
    def __init__(self): self.h = []
    def __call__(self, s, now):
        self.h.append((now, s["x"], s["y"]))
        while len(self.h) > 2 and now - self.h[0][0] > 0.4: self.h.pop(0)
        t0, x0, y0 = self.h[0]
        return math.hypot(s["x"] - x0, s["y"] - y0) / (now - t0) if now - t0 > 0.15 else 1.0

def stop_car(secs=2.0):
    xdo("keyup", "Up"); t0 = time.time(); sp = Speedo()
    xdo("keydown", "space")
    try:
        while time.time() - t0 < secs:
            time.sleep(0.15); s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            if sp(s, now) < 0.3 and now - t0 > 0.3: return s
    finally:
        xdo("keyup", "space")
    return D.wait_state()

def lane_in(shop, secs=30, until=None, vmax=3.0):
    """into a one-cell drive-through bay along its centre line (pure pursuit on x = shop x, 1.8
    blocks ahead), the throttle on only while lined up and under vmax (blocks per wall second);
    a wrong bay (off the line past the bay's mouth) is backed out of straight"""
    lx, sy = shop; d = BAYS[shop]; mouth = sy - d * 1.7
    t0 = time.time(); sp = Speedo(); thr = [False]; stalled = None
    def throttle(on):
        if on != thr[0]: xdo("keydown" if on else "keyup", "Up"); thr[0] = on
    try:
        while time.time() - t0 < secs:
            time.sleep(0.07)
            s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            v = sp(s, now)
            BR.check()
            if until and until(): throttle(False); return s
            ex = s["x"] - lx; along = (s["y"] - sy) * d          # along: < 0 before the shop point
            if along > -0.35 and abs(ex) < 0.5:
                throttle(False); hold("space", 0.5); return s
            if (s["y"] - mouth) * d > 0 and abs(ex) > 0.7:
                throttle(False); M.mark(f"lane_in: in the wrong bay at {s['x']:.1f},{s['y']:.1f}: straight back out")
                stop_car(); hold("Down", 1.4); stop_car()
                BR.turn_car_toward(lx, sy, secs=8); sp = Speedo(); continue
            ty = s["y"] + d * 1.8
            if (ty - sy) * d > 1.0: ty = sy + d * 1.0
            hx, hy = M.heading(s); dx, dy = lx - s["x"], ty - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 1.2 and (s["y"] - mouth) * d < 0:
                throttle(False); stop_car(); BR.turn_car_toward(lx, sy, secs=8)
                sp = Speedo(); continue
            # lined up: up to vmax; turning: keep rolling slowly (a stopped car does not steer; km8,
            # on the version that coasted while turning, stood 50 s at 202.8,215.2 with the throttle off)
            throttle(v < (vmax if abs(a) < 0.45 else 1.2))
            if v < 0.3 and time.time() - t0 > 1.0:
                stalled = stalled or now
                if now - stalled > 1.2:          # pressed against something: back off, wheel the other way
                    throttle(False); key = "Left" if a > 0 else "Right"
                    xdo("keydown", "Down"); xdo("keydown", key); time.sleep(0.5)
                    xdo("keyup", "Down"); xdo("keyup", key); stalled = None
                    sp = Speedo(); continue
            else:
                stalled = None
            if abs(a) > 0.05:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.18, abs(a) * 0.3)); xdo("keyup", key)
    finally:
        throttle(False)
    return D.wait_state()


def park_getaway():
    """from the bank box into the eastbound lane, nose east (GETAWAY_PARK): forward along the
    lane's line at a walking pace (kmg2: reverse/forward pulses toward the point put the car at
    195.9,175.2 on the bank's forecourt)"""
    px, py = GETAWAY_PARK
    s = D.wait_state()
    if M.heading(s)[0] < 0.2: BR.turn_car_toward(px + 6.0, py, secs=10)
    launch(py, px, secs=12, vmax=1.8)
    s = stop_car()
    if M.heading(s)[0] < 0.9: BR.turn_car_toward(px + 12.0, py, secs=8); s = stop_car()
    # MISSION-GETAWAY: the first pass left the car anywhere from y 176.3 (mg_km8, in the side street)
    # to 181.5 (mg_fb3); off the lane the launch was skipped, or the walk back took 41 s. The level is
    # still 0 here (no police yet): one more slow pass toward the lane from where it stands
    s = D.wait_state()
    if s and s["driving"] and abs(s["y"] - py) > 1.2 and s["x"] < 203.0:
        M.mark(f"park: {abs(s['y'] - py):.1f} off the lane at {s['x']:.1f},{s['y']:.1f}: another pass")
        BR.turn_car_toward(s["x"] + 5.0, py, secs=8)
        launch(py, min(s["x"] + 3.5, 203.0), secs=10, vmax=1.8)
        s = stop_car()
        if M.heading(s)[0] < 0.9: BR.turn_car_toward(s["x"] + 12.0, py, secs=8); s = stop_car()
    return s

def launch(lane_y, x_end, secs=20, vmax=7.0):
    """east along the lane with the throttle held (pure pursuit 3 blocks ahead on y = lane_y), no
    stops: a stall (under 0.4 blocks/s for 0.7 s) is a short reverse with the wheel turned, then on"""
    t0 = time.time(); sp = Speedo(); slow_since = None; thr = [False]
    def throttle(on):
        if on != thr[0]: xdo("keydown" if on else "keyup", "Up"); thr[0] = on
    try:
        while time.time() - t0 < secs:
            time.sleep(0.07)
            s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            v = sp(s, now)
            BR.check()
            if s["x"] >= x_end: return s
            hx, hy = M.heading(s); dx, dy = s["x"] + 3.0 - s["x"], lane_y - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            throttle(v < vmax)
            if v < 0.4 and time.time() - t0 > 1.0:
                slow_since = slow_since or now
                if now - slow_since > 0.7:
                    throttle(False); key = "Left" if a > 0 else "Right"
                    xdo("keydown", "Down"); xdo("keydown", key); time.sleep(0.55)
                    xdo("keyup", "Down"); xdo("keyup", key); slow_since = None
                    sp = Speedo(); continue
            else:
                slow_since = None
            if abs(a) > 0.05:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.2, abs(a) * 0.3)); xdo("keyup", key)
    finally:
        throttle(False)
    return D.wait_state()


def follow_path(pts, secs=45, vmax=6.0, vcorner=3.0, look=3.0, tol=1.2, slow_end=None):
    """drive a hand-placed polyline without stopping: pure pursuit `look` blocks ahead of the
    nearest point, the throttle held under vmax (vcorner within 4 blocks of a turn), a stall (under
    0.4 blocks/s for 0.8 s) a short reverse with the wheel turned; returns at the last point, or
    when more than 4.5 blocks off the line (the caller falls back to drive3)"""
    s = D.wait_state(); pts = [(s["x"], s["y"])] + list(pts)
    t0 = time.time(); sp = Speedo(); seg = 0; slow_since = None; thr = [False]; braked = 0.0
    def throttle(on):
        if on != thr[0]: xdo("keydown" if on else "keyup", "Up"); thr[0] = on
    def proj(k, x, y):
        (ax, ay), (bx, by) = pts[k], pts[k + 1]
        L2 = max((bx - ax) ** 2 + (by - ay) ** 2, 1e-6)
        t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
        px, py = ax + t * (bx - ax), ay + t * (by - ay)
        return t, px, py, math.hypot(x - px, y - py)
    try:
        while time.time() - t0 < secs:
            time.sleep(0.06)
            s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            v = sp(s, now)
            BR.check()
            ex, ey = pts[-1]
            if math.hypot(ex - s["x"], ey - s["y"]) < tol: return s
            while seg < len(pts) - 2 and proj(seg, s["x"], s["y"])[0] >= 0.999: seg += 1
            if seg < len(pts) - 2 and proj(seg + 1, s["x"], s["y"])[3] < proj(seg, s["x"], s["y"])[3]: seg += 1
            t, px, py, off = proj(seg, s["x"], s["y"])
            if off > 4.5:
                say(f"follow_path: {off:.1f} off the line at {s['x']:.1f},{s['y']:.1f}"); return s
            # the look-ahead point along the polyline
            rem = look; k = seg; cx, cy = px, py
            while True:
                bx, by = pts[k + 1]; dl = math.hypot(bx - cx, by - cy)
                if dl >= rem or k + 1 >= len(pts) - 1:
                    f = min(1.0, rem / max(dl, 1e-6)); tx, ty = cx + f * (bx - cx), cy + f * (by - cy); break
                rem -= dl; cx, cy = bx, by; k += 1
            corner = seg + 1 < len(pts) - 1 and math.hypot(pts[seg + 1][0] - s["x"], pts[seg + 1][1] - s["y"]) < 4.0
            cap = vcorner if corner else vmax
            if slow_end and math.hypot(ex - s["x"], ey - s["y"]) < slow_end[0]: cap = min(cap, slow_end[1])
            if math.hypot(ex - s["x"], ey - s["y"]) > 3.0:
                # MISSION-GETAWAY (mg_km4): a taxi standing in the lane at the row-213 turn; round it
                tx, ty, _blk = SP.overtake(world_ref[0], s, tx, ty) if world_ref[0] is not None else (tx, ty, None)
            hx, hy = M.heading(s); dx, dy = tx - s["x"], ty - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            throttle(v < cap)
            if v > cap * 1.3 + 0.5 and now - braked > 0.5:   # well over the cap: brake, not just coast
                hold("Down", 0.1); braked = now        # (kmg15: a tap every loop on a lagging speed
                                                       # took 5 -> 1 block/s and a foot officer had him)
            if v < 0.4 and now - t0 > 1.0:
                slow_since = slow_since or now
                if now - slow_since > 0.5:           # kmg9: busted 3 s after a ram; react sooner
                    throttle(False); key = "Left" if a > 0 else "Right"
                    xdo("keydown", "Down"); xdo("keydown", key); time.sleep(0.6)
                    xdo("keyup", "Down"); xdo("keyup", key); slow_since = None
                    sp = Speedo(); continue
            else:
                slow_since = None
            if abs(a) > 0.05:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.22, abs(a) * 0.3)); xdo("keyup", key)
    finally:
        throttle(False)
    return D.wait_state()


def run(world, entry):
    world_ref[0] = world
    # 1-2. the car and the bank box: as the job's runner
    M.mark("to the GRAHAM at 52.5,150.5")
    s = M.enter_car3(world, BR.CAR0[0], BR.CAR0[1], budget=200)
    if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
        say("the walk to the mission car failed; developer warp to its door (reported)")
        BR.set_view("classic"); M.scene_warp(BR.CAR0[0], BR.CAR0[1] + 1.0, M.top_level(world, BR.CAR0[0], BR.CAR0[1]) or 1, "to the mission car's door"); BR.set_view("third")
        s = M.enter_car3(world, BR.CAR0[0], BR.CAR0[1], budget=90)
    if not (s and s["driving"]): return "stuck: could not enter the car"
    M.shot("br_incar"); BR.FP["until"] = 0.0; remember_car()
    t1 = time.time()
    while time.time() - t1 < 30 and not BR.arrow_near(BR.BANK_BOX[0], BR.BANK_BOX[1]): time.sleep(0.5)
    BR.check()
    M.mark("to the City Bank box 194.5,177.5 (in the car)")
    for k in range(4):
        s = D.wait_state()
        if not s["driving"]:
            s = BR.to_mission_car(world, BR.CAR0 if k == 0 else (s.get("px", BR.CAR0[0]), s.get("py", BR.CAR0[1])))
            if not s["driving"]: continue
        s = guarded_drive(world, BR.BANK_STOP[0], BR.BANK_STOP[1], 1.2, 420,
                          until=lambda: (M.mission_state() or {}).get("msg") == "1665" or bool(BR.guards()))
        BR.check()
        s = D.wait_state()
        if s["driving"] and math.hypot(BR.BANK_STOP[0] - s["x"], BR.BANK_STOP[1] - s["y"]) < 6:
            BR.creep_in(BR.BANK_STOP[0], BR.BANK_STOP[1], 1.6, 1.2, secs=30)
        t2 = time.time()
        while time.time() - t2 < 8 and not BR.guards(): time.sleep(0.5)
        if BR.guards(): break
    t2 = time.time()
    while time.time() - t2 < 30 and not BR.guards(): time.sleep(0.5); BR.check()
    gs = BR.guards(); ms = BR.check()
    say(f"guards: {[(p['id'], p['x'], p['y'], p['z'], p['hp']) for p in gs]}; carhp {ms.get('carhp')}")
    if not gs: return "stuck: no guards"
    M.shot("br_bank")
    # the getaway runs EAST to the avenue at columns 216-220, south on it and west along row 215 to
    # the respray tunnel at 204.5,218.6: km4 (and br10 before it) were pulled out in the jams on the
    # column-178 avenue, the route west then south
    s = park_getaway()
    s = D.wait_state(); car = (s["x"], s["y"]); remember_car()
    M.mark(f"getaway car set at {s['x']:.1f},{s['y']:.1f} heading {M.heading(s)[0]:.2f},{M.heading(s)[1]:.2f}")
    t3 = time.time()
    while time.time() - t3 < 70:
        BR.check(); s = D.wait_state()
        nc, no, dmin = BR.police_near(s)
        if nc == 0 and no == 0: break
        say(f"police near the bank ({nc} cars, {no} officers, nearest {dmin:.1f}): waiting in the car")
        time.sleep(2.0)

    # 3. the guards: the skill. close=3.2 (was 2.2): each 0.5 s walking step in range carries him 1-2
    # blocks, and from 2.2 he ended on top of the second guard (kmg16 d 0.3, kmg8 and kmg14 at the walk)
    # where his rounds miss and the guard's do not: shot dead in about a second
    M.mark("kill_marked skill: the two bank guards")
    s = M.leave_car(); M.select_gun(); BR.FP["until"] = -1
    M.ensure_view("classic")      # the chase view with GTA2_DIRECT_KEYS=1
    up = climb_to_walk()
    if not up and os.environ.get("BR_CLIMB_CLASSIC", "1") == "1":
        # MISSIONS-BATCH2: mb2_km2 (and mg_sp8) pinned at the stair foot by the girder's renderer-side
        # collider (defect mg-wil-bank-stair-girder-collider-blocks-entry, FIX-COLLISION-2), which is solid
        # only in the 3D views: the same climb once more in the classic view, the fight back in the chase view
        saved = M.WALK_VIEW[0]
        M.mark("climb: not up in the chase view (the stair girder's collider); again in the classic view (renderer-side defect)")
        try:
            M.WALK_VIEW[0] = "classic"; M.ensure_view("classic")
            up = climb_to_walk(resume=True)
        finally:
            M.WALK_VIEW[0] = saved; M.ensure_view("classic")
    s = D.wait_state(); M.mark(f"climb by the job: {'on the walk' if up else 'not up'} at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f}")
    r = K.kill_marked(world, select=is_guard, spare=is_spare, approach=CLIMB_KM, level=BR.WALK_LEVEL,
                      fire_spots=BR.FIRE_SPOTS, secs=150, check=job_check, engage=7.0, close=3.2,
                      stall=8.0, confirm=3.0, shot_prefix="km_bank")
    ms = BR.check()
    M.mark(f"kill_marked skill: {r} (wanted {ms.get('wanted')}, ammo {ms.get('ammo')})"); M.shot("br_guards")
    if r != "done" or BR.guards(): return f"stuck: guards ({r})"

    # 4-6. getaway, respray, safehouse: as the job's runner (its run() from step 4 on)
    s = D.wait_state()
    if K.level_of_z(s["z"]) == BR.WALK_LEVEL:
        if not walk_pts(DESCEND_KM, secs_each=5.0):
            s = D.wait_state(); say(f"descent missed at {s['x']:.1f},{s['y']:.1f}")
    s = D.wait_state()
    if not s["driving"] and math.hypot(car[0] - s["x"], car[1] - s["y"]) < 7.0:
        M.cruise_to(car[0], car[1] - 1.0, tol=0.6, secs=5)       # the driver's (north) side
        s = D.wait_state()
        if math.hypot(car[0] - s["x"], car[1] - s["y"]) < 3.0: s = BR.quick_board(car)
    for k in range(3):
        if s and s["driving"]: break
        BR.check(); s = to_car(world)
    s = board_graham(world, s)
    if not (s and s["driving"]): return "stuck: could not get back in the car"
    ms = BR.check()
    M.mark(f"in the getaway car (wanted {ms.get('wanted')}, carhp {ms.get('carhp')})")
    s = D.wait_state()
    at_bay = False
    # MISSION-GETAWAY: park_getaway left the GRAHAM on the pavement at y 178.1-178.4 (mg_km2, mg_sp3:
    # 3.2-3.5 off the lane, outside the old 3.0 box), the launch was skipped and drive3's getaway leg
    # stalled at 214.4,181.5 with a cop at the door (mg_sp3, arrested). A car facing east anywhere
    # from the pavement to the far lane now launches: the pursuit steers it into the lane on the way
    if s["driving"] and s["x"] < GETAWAY_LAUNCH_X and abs(s["y"] - GETAWAY_LANE_Y) < 6.0 and M.heading(s)[0] > 0.4:
        s = launch(GETAWAY_LANE_Y, GETAWAY_LAUNCH_X - 3.0)
        M.mark(f"launch: at {s['x']:.1f},{s['y']:.1f} (driving {s['driving']}); the path to the bay")
        if s["driving"]:
            # kmg9: rammed by a police car on the slow last stretch (10 blocks at 2.2) and arrested
            # 3 s later; now 7 blocks at 3.0 (offline model: into the bay at turn rates 1.5-4 rad/s)
            s = follow_path(GETAWAY_PATH, look=2.2, tol=0.8, slow_end=(7.0, 3.5))
            ex, ey = GETAWAY_PATH[-1]
            at_bay = bool(s["driving"]) and math.hypot(ex - s["x"], ey - s["y"]) < 2.5
            M.mark(f"follow_path: at {s['x']:.1f},{s['y']:.1f} (driving {s['driving']}, at the bay {at_bay})")
    else:
        hold("Up", 0.8)

    def heads_up():
        return BR.arrow_near(86.5, 160.5) or (M.mission_state() or {}).get("msg") in ("1655", "1666", "1668")
    def safe_up():
        return BR.arrow_near(*BR.SAFE, r=4.0) or (M.mission_state() or {}).get("msg") in ("1661", "1662", "1010")
    sprayed = False
    for k in range(6):
        BR.check()
        if safe_up(): sprayed = True; break
        shop, tunnel = BR.SHOPS[0] if k < 3 else BR.SHOPS[1]
        s = D.wait_state()
        if not s["driving"]: s = to_car(world)
        if not s["driving"]: continue
        BR.FP["until"] = -1
        M.mark(f"to the respray at {shop} (try {k + 1})")
        pre = bay_pre(shop)
        if at_bay and k == 0:
            pass                                   # follow_path brought him to the bay
        elif shop == BR.SHOPS[0][0]:
            for wx, wy in GETAWAY_LEGS:
                s = D.wait_state()
                if not s["driving"] or (wy < 200 and s["y"] > 185) or (wy > 200 and s["y"] > 210): continue
                M.mark(f"getaway leg to {wx},{wy}")
                if os.environ.get("BR_LEGS_CHASE", "1") == "1" and SP.wanted() > 0:
                    # MISSIONS-BATCH2: mb2_km4 (launch skipped after three wrong-car boardings) jammed in
                    # drive3 among standing cars at the bank (8 stalls, 'pinned: giving up', out, 1125): the
                    # wanted legs by shake_police.chase_drive (chase_path: overtakes, reverses out of a stall)
                    s = SP.chase_drive(world, wx, wy, 2.5, 120, check=BR.check)
                else:
                    s = BR.drive(world, wx, wy, 2.5, 120)
                BR.check(); remember_car()
            if not s["driving"]: continue
        if not (at_bay and k == 0):
            s = BR.drive(world, pre[0], pre[1], 1.5, 360)
            BR.check(); remember_car()
            if not s["driving"]: continue
        t6 = time.time()
        while time.time() - t6 < 3 and not heads_up() and not safe_up():
            BR.check(); time.sleep(0.5)
        if safe_up(): sprayed = True; break
        ms = BR.check()
        M.mark(f"into the respray shop {shop} (wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')}): rolling in")
        s = D.wait_state()
        M.mark(f"no stop: from {s['x']:.1f},{s['y']:.1f} heading {M.heading(s)[0]:.2f},{M.heading(s)[1]:.2f} down the bay's line")
        s = lane_in(shop, secs=40, until=safe_up)
        M.shot("br_respray_in")
        t6 = time.time()
        while time.time() - t6 < 25 and not safe_up():
            BR.check(); time.sleep(0.5)
        if safe_up(): sprayed = True; break
        hold("Down", 1.5); time.sleep(0.5)
    ms = BR.check()
    M.mark(f"after the respray ({sprayed}): wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')}, msg {ms.get('msg')}")
    M.shot("br_resprayed")
    for k in range(4):
        BR.check()
        s = D.wait_state()
        if not s["driving"]: s = to_car(world)
        if not s["driving"]: continue
        M.mark(f"to the safehouse {BR.SAFE}")
        s = safehouse_drive(world)
        BR.check(); remember_car()
        if not s["driving"]: continue
        s = BR.creep_in(BR.SAFE[0], BR.SAFE[1], 3.0, 1.0, secs=50, until=lambda: M.objective() is None)
        M.shot("br_garage")
        o, ms = BR.wait_outcome(45)
        if o != "running": return o
        if M.objective() is None: o, ms = BR.wait_outcome(30); return o
    return "stuck: safehouse"


def guarded_drive(world, x, y, tol, budget, until=None):
    """the job's BR.drive (drive3) with shake_police.PinGuard: a car pressed and losing carhp without
    moving is backed off and the drive resumed (mg_km10: burned against a stopped truck)"""
    t0 = time.time(); s = D.wait_state()
    for k in range(8):
        left = budget - (time.time() - t0)
        if left < 5: break
        g = SP.PinGuard(until)
        s = BR.drive(world, x, y, tol, left, until=g)
        if not g.fired or not (s and s["driving"]): return s
        M.mark(f"pinned at {s['x']:.1f},{s['y']:.1f} (carhp {(M.mission_state() or {}).get('carhp')}): back off, on")
        SP.back_off(world)
    return D.wait_state()


def safehouse_drive(world, budget=360):
    """the drive to the safehouse road point: the job's calm drive3 while the level is 0, the
    shake_police chase rules (chase_drive: break-away from an officer at the door, no queueing, and
    chase_path with SP_CHASE_PATH=1) while it is up. MISSION-GETAWAY: mg_km3 (and kmg13 before it)
    picked up a new star from knocks on the 197-block drive after the respray (money 41: no second
    respray); drive3 kept rolling past a cop 2.7 off, slowed, and he was pulled out (state 8) at
    165.7,213.8 and arrested"""
    from skills import shake_police as SP
    # mg_sp6, mg_km17: right after the respray the mission line still read wanted 2 for a moment (the
    # respray took the money, 1010 was up) and the leg started under the chase rules at full pace;
    # the level gets up to 3 game s to read 0 first
    t1 = time.time()
    while time.time() - t1 < 3.0 / D.SPEED and SP.wanted() > 0: time.sleep(0.25)
    t0 = time.time(); s = D.wait_state(); legs = 0
    tx, ty = BR.SAFE_ROAD
    while time.time() - t0 < budget and legs < 12:
        BR.check(); s = D.wait_state()
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= 1.0: return s
        legs += 1; left = max(20, budget - (time.time() - t0))
        if SP.wanted() == 0:
            # mg_km6, mg_fb1: drive3 stalled 22 times in 12 min nosed onto the pavement at the corner
            # near 97,200 and both runs ran out of time; no 3 blocks gained in 40 s -> chase_path
            prog = {"best": math.hypot(tx - s["x"], ty - s["y"]), "t": time.time(), "stuck": False}
            def watch():
                if SP.wanted() > 0: return True
                st = D.wait_state()
                if st:
                    d = math.hypot(tx - st["x"], ty - st["y"])
                    if d < prog["best"] - 3.0: prog["best"] = d; prog["t"] = time.time()
                if time.time() - prog["t"] > 80.0 / D.SPEED: prog["stuck"] = True; return True
                return False
            s = guarded_drive(world, tx, ty, 1.0, left, until=watch)
            if SP.wanted() > 0:
                M.mark(f"safehouse drive: wanted {SP.wanted()} at {s['x']:.1f},{s['y']:.1f}: chase rules")
            elif prog["stuck"]:
                M.mark(f"safehouse drive: drive3 made no headway at {s['x']:.1f},{s['y']:.1f}; chase_path")
                # mg_km15: at the full chase pace (3.0) this unstick drive earned a star in traffic;
                # with the level at 0 it is a calm 2.0 and 60 s, then drive3 again
                s, why = SP.chase_path(world, tx, ty, tol=1.0, budget=min(left, 60), check=BR.check,
                                       until=lambda: SP.wanted() > 0, vmax=2.0)
                M.mark(f"safehouse drive: chase_path {why} at {s['x']:.1f},{s['y']:.1f}")
        else:
            s = SP.chase_drive(world, tx, ty, 1.0, left, view_switch=BR.view_switch, check=BR.check,
                               until=lambda: SP.wanted() == 0)
            if SP.wanted() == 0: M.mark(f"safehouse drive: the level is gone at {s['x']:.1f},{s['y']:.1f}")
        remember_car()
    return D.wait_state()


def main():
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level")
    M.arrows_baseline()
    M.START[0] = (s["x"], s["y"])
    M.VIEW_HOOK[0] = BR.set_view
    BR.set_view("third")
    entry = next(m for m in world.db["missions"] if m.get("mission") == "wil_ye2")
    M.mark("mission wil_ye2: BANK ROBBERY! (guards by the kill_marked skill)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = BR.answer(world, entry)
    if r == "no answer": r, seen = BR.answer(world, entry)
    say("phone:", r, seen); M.shot("br_phone")
    if r != "answered":
        M.mark(f"mission wil_ye2: phone {r} {seen}"); return
    M.arm_lives()
    BR.MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and s["z"] > 3.5 and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on the phone dais (z {s['z']:.1f}); developer warp to the street at {cell[0]},{cell[1]} (reported)")
            BR.set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone dais"); BR.set_view("third")
    try:
        r = run(world, entry)
    except (BR.Over, K.JobOver) as e:
        r = str(e)
    if r == "running":
        o, ms = BR.wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission wil_ye2: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    M.shot("br_end")
    BR.set_view("third"); time.sleep(1.0); M.shot("br_end_third")
    say("RESULTS", {"wil_ye2": r})
    M.mark(f"done wil_ye2={r}")


if __name__ == "__main__":
    main()
