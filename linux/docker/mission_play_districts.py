#!/usr/bin/env python3
"""Plays missions of the Industrial (file bil) and Residential (file ste)
districts in the street-level views, with the Downtown runner's primitives
(mission_lib v3: the game's objective arrows, the multi-level router, the
held-key walker and driver) and per-mission scripts for the jobs whose plans
are counter loops rather than LOCATE waits.

Usage inside the container (the level is swapped by SWAP_LEVEL in the run script):
    DISTRICT=ste MISSIONS="ste_re1" python3 /work/mission_play_districts.py
    DISTRICT=bil MISSIONS="bil_re2" python3 /work/mission_play_districts.py

Third person on foot, first person for a stretch of every walk and every
drive. Marks in /out/marks.txt, milestone frames /out/m_*.png."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
DISTRICT = os.environ.get("DISTRICT", "ste")
wanted = sys.argv[1:] or os.environ.get("MISSIONS", {"ste": "ste_re1", "bil": "bil_re2"}[DISTRICT]).split()
VIEW = ["classic"]

def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
world = M.World(DISTRICT)
if DISTRICT == "bil":
    # the south stair to the Russians' rooftop phone (x=189, y 85..78) does not go through
    # at its top (pt7_bil1's walker stood at 189.6,79.3 for four minutes of re-routes) and
    # neither does the west one (row 77: pt7_bil2 stuck at 180.2,77.8 on its second step).
    # The east stair (row 75, from 197 up to 190) is the way up pt6_bil2 took
    M.BLOCKED.update({(189, 79), (189, 78), (180, 77), (181, 77)})
M.mark(f"level ({DISTRICT})")
M.arrows_baseline()
set_view("third")
FP = {"until": 0.0}
TITLES = {m["plan"][0].get("display_message"): m for m in world.db["missions"]
          if m.get("plan") and "display_message" in m["plan"][0]}

def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 18; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

def money():
    return (M.mission_state() or {}).get("money", 0)

def msg():
    return (M.mission_state() or {}).get("msg", "")

# The walker steers with heading pulses calibrated in the classic view; the 3D
# views remap the keys (Up walks where the camera looks, Left/Right turn a wanted
# heading through a lagging controller), so walk3 takes the classic view for the
# walk and gives the 3D view back after it, as the Downtown runner does since
# pt4_wil15. Without the hook (pt5_bil1) the walker walked in the chase view:
# 20 minutes of re-routes at the Industrial spawn and on the way to the Z-Type.
M.VIEW_HOOK[0] = set_view

def walk(tx, ty, tl=None, tol=0.5, budget=300, fp_secs=0):
    """a walk (classic view while walking; first person is at the wheel)"""
    return M.walk3(world, tx, ty, tl, tol=tol, budget=budget)

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

# ---------------------------------------------------------------- arrows

def wait_arrow(secs, kinds=None):
    """the mission arrow (x, y, z, kind, obj), optionally of the given kinds"""
    t0 = time.time()
    while time.time() - t0 < secs:
        o = M.objective()
        if o and (kinds is None or o[3] in kinds): return o
        time.sleep(0.4)
    return None

def wait_arrow_gone(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        if M.objective() is None: return True
        time.sleep(0.3)
    return False

# ---------------------------------------------------------------- phones

# Approach waypoints for phones whose direct route the walker cannot take
# (verified: the Rednecks' phone in file ste is fenced on the west; the
# approach from the south along x=18.5 worked in run pd3_ste2).
# A chain of waypoints: run pd3_ste5 wandered east of the plaza after the first
# waypoint and never got onto the phone; the second keeps the walker on x=18.5.
APPROACH = {(18.5, 68.5): ((18.5, 100.0), (18.5, 78.0)), (18.5, 67.5): ((18.5, 100.0), (18.5, 78.0))}

RUNNING_KEYS = {"3103"}   # e.gxt: the Russians' "you are working a Russian contract"
def answer(entry):
    """get to the phone (by car when far, on foot up its stairs), stand on it,
    and read which job started from the game's title message or its arrow"""
    m0 = msg()
    s = D.wait_state() or D.wait_state(60)
    if not s: return False, ""     # no position line (pt8_bil21 crashed here after a failed job)
    tl = None if entry["z"] >= 200 else max(1, int(round(entry["z"])) - 1)
    far = math.hypot(entry["x"] - s["x"], entry["y"] - s["y"])
    walk_all = os.environ.get("PHONE_WALK", "1" if DISTRICT == "bil" else "0") == "1"
    if s and not s["driving"] and far > 40 and not walk_all:
        M.mark(f"a long way to the phone ({far:.0f} blocks): by car")
        s = M.any_car2(world, budget=120)
    elif walk_all and far > 40:
        # PLAYTHROUGH-8: Industrial's 150 blocks from the start to the Russians' rooftop phone
        # cost two to four burning borrowed cars and 8-15 minutes a session (pt8_bil5-16);
        # the walker goes the whole way in about four
        M.mark(f"a long way to the phone ({far:.0f} blocks): walking")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=3.0, budget=600)
    legs = 0
    while s and s["driving"] and legs < 3:
        legs += 1
        FP["until"] = 0.0
        s = M.drive3(world, entry["x"], entry["y"], tol=5.0, budget=420, view_switch=view_switch, slow=False)
        s = M.leave_car(); set_view("third")
        left = math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) if s else 0
        M.mark(f"out of the car {left:.0f} blocks from the phone")
        if left > 40:
            # the drive bailed out (wall hits) or stalled far away: another car, another leg
            M.mark("still far from the phone: another car")
            s = M.any_car2(world, budget=120)
    ap = APPROACH.get((entry["x"], entry["y"]))
    if ap:
        for i, (wx, wy) in enumerate(ap):
            M.mark(f"approach waypoint {wx},{wy} for the phone")
            s = walk(wx, wy, None, tol=1.5, budget=240 if i == 0 else 120, fp_secs=10 if i == 0 else 0)
    if ap:
        # stop a block and a half short on the approach side and step on with nudges: the
        # Rednecks' two phones are neighbours (68.5 / 67.5) and pt6_ste3's walk overshot
        # onto DOUBLE-CROSS CRUSH! (2803) instead of BLOW JOB
        wx, wy = ap[-1]; dn = math.hypot(wx - entry["x"], wy - entry["y"]) or 1.0
        s = walk(entry["x"] + (wx - entry["x"]) / dn * 1.5, entry["y"] + (wy - entry["y"]) / dn * 1.5, tl, tol=0.4, budget=200)
        nudge_to(entry["x"], entry["y"], tol=0.12, tries=16)
        s = D.wait_state()
    else:
        s = walk(entry["x"], entry["y"], tl, tol=0.35, budget=300, fp_secs=10)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2:
        s = M.walk3(world, entry["x"], entry["y"], tl, tol=0.35, budget=120)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        # A warp onto the phone itself never rings it (the game answers on
        # stepping onto the cell), so warp to the nearest street cell a few
        # blocks away and walk the last stretch.
        near = (ap[-1][0], ap[-1][1], 1) if ap else M.street_cell_near(world, entry["x"], entry["y"], radius=10)
        if near and math.hypot(near[0] - entry["x"], near[1] - entry["y"]) < 1.5:
            near = M.street_cell_near(world, entry["x"] + 3, entry["y"] + 3, radius=10) or near
        wx, wy, lvl = (near[0], near[1], near[2]) if near else (entry["x"], entry["y"], M.top_level(world, entry["x"], entry["y"]))
        say(f"phone at {entry['x']},{entry['y']} not reached on foot; developer warp to the street at {wx},{wy} (level {lvl})")
        set_view("classic")
        s = M.scene_warp(wx, wy, lvl, "phone not reached on foot; warp to the street beside it")
        set_view("third")
        s = M.walk3(world, entry["x"], entry["y"], tl, tol=0.35, budget=150)
        if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.6:
            # step off and back on, in case the walk ended on the cell without a ring
            ox, oy = M.step_off_phone(world, entry)
            M.cruise_to(ox, oy, tol=0.5, secs=8); time.sleep(0.5)
            s = M.walk3(world, entry["x"], entry["y"], tl, tol=0.3, budget=40)
    t0 = time.time(); seen = []
    while time.time() - t0 < 30:
        k = msg()
        if k != m0 and k not in ("", "svdone"):
            if k not in seen: seen.append(k)
            if k in TITLES:
                say(f"phone: title {k} ({TITLES[k].get('title')})"); return True, k
            if k in RUNNING_KEYS:
                # PLAYTHROUGH-8: "You are working a Russian contract, Comrade" (3103, e.gxt): the
                # job this phone started on the first step is running and its title was missed
                # (pt8_bil12/18 took it for "not answered" and the session ended)
                say(f"phone: {k}, a job of this gang is already running: this one"); return True, k
        if M.mission_arrows():
            say(f"phone: a mission arrow is up (messages {seen})"); return True, (seen[-1] if seen else "")
        if time.time() - t0 > 6:
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=4)
        time.sleep(0.25)
    say(f"phone: not answered (messages {seen})"); return False, (seen[-1] if seen else "")

# ---------------------------------------------------------------- the mission car

def face_point(x, y, tries=6):
    M.ensure_view("classic")
    for _ in range(tries):
        s = D.wait_state()
        if not s: return s
        a = D.angle_to(s, x, y)
        if abs(a) < 0.3: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, min(abs(a) / max(D.rate, 2.0), 0.35)); time.sleep(0.35)
    return D.wait_state()

WRONG = [None]   # set when got() moved a wrong car away: the mission car's position to walk back to
def enter_parked(cx, cy, budget=150, why="the mission car"):
    """get into the parked car at (cx,cy): walk near, read the renderer's own
    position and heading for it, stand at a door side that has floor, face it,
    Enter; both sides, then the ends; the developer door warp (F9) only as a
    reported last resort"""
    t0 = time.time()
    s = M.walk3(world, cx, cy, None, tol=2.2, budget=min(480, budget))
    tried = 0
    def got(s):
        """driving, and the car is where the mission car was parked (run pd3_bil5:
        a door try put the player into a passing traffic car 90 blocks away and
        the script took it for the Z-Type), and the mission arrow is not on another
        car beside him (pt7_bil3: the borrowed car stopped 3 blocks from the Z-Type
        and Return put him back into it; the dealers' loop then drove nowhere for
        five minutes with the arrow on the Z-Type)"""
        if not (s and s["driving"] and math.hypot(s["x"] - cx, s["y"] - cy) < 4.0): return False
        time.sleep(1.5)
        o = M.objective(); s2 = D.wait_state()
        ms = M.mission_state() or {}
        if o and o[3] in (3, 4) and ms.get("tcar") and math.hypot(ms["tcar"][0] - s2["x"], ms["tcar"][1] - s2["y"]) > 1.2:
            say(f"enter_parked: in a car at {s2['x']:.1f},{s2['y']:.1f}, but the mission car is at {ms['tcar'][0]:.1f},{ms['tcar'][1]:.1f}: out")
            M.mark("in the wrong car beside the mission car: moving it away")
            # PLAYTHROUGH-8: pt8_bil3's borrowed car stood a block from the Z-Type and every
            # door try (nine) put him back into it: drive it eight blocks away from the
            # Z-Type first, then walk back to the Z-Type's own position (tcar)
            tx_, ty_ = ms["tcar"]; vx_, vy_ = s2["x"] - tx_, s2["y"] - ty_; n_ = math.hypot(vx_, vy_) or 1.0
            gx_, gy_ = s2["x"] + vx_ / n_ * 8.0, s2["y"] + vy_ / n_ * 8.0
            cell = M.street_cell_near(world, gx_, gy_, radius=5)
            if cell: M.drive3(world, cell[0], cell[1], tol=2.0, budget=40, slow=True)
            M.BAD_CARS.append((D.wait_state()["x"], D.wait_state()["y"]))
            M.leave_car(); WRONG[0] = (tx_, ty_); return False
        return True
    while s and time.time() - t0 < budget:
        if got(s): return s
        if WRONG[0]:
            # the mission car's own position from the game, and a walk back to it
            cx, cy = WRONG[0]; WRONG[0] = None
            s = M.walk3(world, cx, cy, None, tol=2.0, budget=60); tried = 0; continue
        s = D.wait_state()
        if s["driving"] and math.hypot(s["x"] - cx, s["y"] - cy) < 4.0:
            M.leave_car(); s = D.wait_state()      # the wrong car beside the mission car (got() left it already, or about to)
        if s["driving"]:
            say(f"enter_parked: in a passing car at {s['x']:.1f},{s['y']:.1f}, not {why}; driving it to {cx:.1f},{cy:.1f}")
            M.mark(f"a passing car instead of {why}: driving it over")
            s = M.drive3(world, cx, cy, tol=3.0, budget=180, slow=True)
            s = M.leave_car(); tried = 0
            s = M.walk3(world, cx, cy, None, tol=2.2, budget=60)
            continue
        if math.hypot(s["x"] - cx, s["y"] - cy) > 8.0:
            say(f"enter_parked: still {math.hypot(s['x'] - cx, s['y'] - cy):.0f} blocks from {why}; walking on")
            s = M.walk3(world, cx, cy, None, tol=2.2, budget=90)
            continue
        s = D.wait_state()
        if s["parked"] and s["pd"] < 3.5:
            px, py, hx, hy = s["px"], s["py"], s["phx"], s["phy"]
        else:
            px, py, hx, hy = cx, cy, 0.0, 1.0
        tc = (M.mission_state() or {}).get("tcar")
        if tc and tc[0] > 0 and math.hypot(tc[0] - px, tc[1] - py) > 0.8 and math.hypot(tc[0] - cx, tc[1] - cy) < 4.0:
            # the nearest parked car is not the mission car (pt8_bil3): its door, not that one's
            px, py, hx, hy = tc[0], tc[1], 0.0, 1.0
        if abs(hx) + abs(hy) < 0.1: hx, hy = 0.0, 1.0
        sides = [(px - hy * 0.75, py + hx * 0.75), (px + hy * 0.75, py - hx * 0.75),
                 (px + hx * 1.5, py + hy * 1.5), (px - hx * 1.5, py - hy * 1.5)]
        lvl = world.level(s)
        sides = [pt for pt in sides if M.node_kind(world, int(pt[0]), int(pt[1]), lvl)] or sides
        pt = sides[tried % len(sides)]; tried += 1
        say(f"enter_parked: car at {px:.1f},{py:.1f} heading {hx:.2f},{hy:.2f}; door try {tried} at {pt[0]:.1f},{pt[1]:.1f}")
        nudge_to(pt[0], pt[1], tol=0.3, tries=14)
        face_point(px, py)
        tap("Return", 0.3)
        for _ in range(8):
            time.sleep(0.5); s = D.wait_state()
            if s["driving"] or s["state"] in (2, 3, 6): break
        for _ in range(10):
            if s["driving"]: break
            if s["state"] not in (2, 3, 6): break
            time.sleep(0.6); s = D.wait_state()
        if s["driving"]: continue           # checked (got / passing car) at the top of the loop
        if tried == 2 and os.environ.get("WARP_OK", "1") == "1":
            say("enter_parked: two door tries failed; developer door warp (F9)")
            M.mark(f"WARP: F9 to the door of {why} at {px:.1f},{py:.1f} (honest entry failed twice)")
            tap("F9", 0.3); time.sleep(2.0); tap("Return", 0.3); time.sleep(3.0)
            s = D.wait_state()
    return s

# ---------------------------------------------------------------- driving helpers

def creep_box(x, y, w, h, money0, secs=75):
    """nose the car into the IS_CAR_IN_BLOCK box (w x h about x,y) with short
    pulses until the game reacts (the arrow leaves or the message changes)"""
    key0 = M.objective_key(); m0 = msg(); t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return False, s
        if M.objective_key() != key0 or msg() != m0: return True, s
        o, ms = M.outcome(money0)
        if o != "running": return False, s
        if M.inside_box(s, x, y, w, h): time.sleep(1.5); continue
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.6 and math.hypot(dx, dy) > 0.7:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.12: xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.5); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)
    return False, D.wait_state()

# blocks to line up for: (approach point on the row, the point to creep to). The
# barricade block (110.5,77.5, 3x1) is road row 77 with the barricade in cell 111: in
# from the west along the row, nose up to x=110
APPROACH_BLOCK = {(110.5, 77.5): ((106.5, 77.5), (110.0, 77.5)),
                  (48.5, 20.5): ((53.5, 20.6), (49.0, 20.5))}   # PLAYTHROUGH-8: pt8_ste1's Pickup 1 stopped at 46.86,21.27, half west of the 3x1 trailer block (2005, 2004): lined up on row 20 from the east

def park_in_block(x, y, w, h, money0, budget=300, parked_msgs=()):
    """drive the mission car into the block: the road route, then the creep.
    parked_msgs: game messages that mean "you are in the block": once one shows,
    do not move again (the creep's pulses pushed the rigged Pickup back out in
    run pd3_ste2: 2005 then 2004 then the fail)"""
    M.mark(f"by car to the block at {x},{y} ({w}x{h})")
    ap = APPROACH_BLOCK.get((x, y))
    if ap:
        # a long thin block counts the car only lying along it: pt7_ste3's Pickup drove
        # through the barricade block (2016, then 2017 at once) and stopped in it facing
        # north at 110.43,77.70, half outside; nothing more happened. Line up on the row
        # first, then creep in along it
        (ax, ay), (cx, cy) = ap
        M.mark(f"lining up for the block at {ax},{ay}")
        s = M.drive3(world, ax, ay, tol=0.9, budget=budget, view_switch=view_switch, slow=True, precious=True)
        if msg() in parked_msgs:
            xdo("keyup", "Up"); hold("space", 0.5); return True, D.wait_state()
        ok, s = creep_box(cx, cy, 0.6, 0.6, money0, secs=60)
        if msg() in parked_msgs:
            xdo("keyup", "Up"); hold("space", 0.5); return True, D.wait_state()
    s = M.drive3(world, x, y, tol=max(0.5, min(w, h) * 0.45 + 0.3), budget=budget, view_switch=view_switch, slow=True, precious=True)
    if msg() in parked_msgs:
        say(f"park_in_block: the game already reports the car in the block (msg {msg()}); holding still")
        xdo("keyup", "Up"); hold("space", 0.5); return True, D.wait_state()
    legs = 0
    while s and s["driving"] and math.hypot(s["x"] - x, s["y"] - y) > 4.0 and legs < 2:
        legs += 1
        say(f"park_in_block: the drive ended {math.hypot(s['x'] - x, s['y'] - y):.0f} blocks from the block; driving again (leg {legs+1})")
        s = M.drive3(world, x, y, tol=max(0.5, min(w, h) * 0.45 + 0.3), budget=budget, view_switch=view_switch, slow=True, precious=True)
        if msg() in parked_msgs: xdo("keyup", "Up"); hold("space", 0.5); return True, D.wait_state()
    ok, s = creep_box(x, y, w, h, money0)
    if msg() in parked_msgs: xdo("keyup", "Up"); hold("space", 0.5); return True, D.wait_state()
    if not ok and s and s["driving"]:
        s = M.drive3(world, x, y, tol=0.5, budget=60, slow=True, precious=True)
        ok, s = creep_box(x, y, w, h, money0, secs=60)
    say(f"park_in_block {x},{y}: {'reacted' if ok else 'no reaction'} at {s['x']:.2f},{s['y']:.2f}" if s else "park_in_block: no state")
    return ok, s

def arm_and_run(money0, armed_msgs, run_level=1, blast_at=None):
    """the car bomb: fire arms it (the game says get out), leave, run clear"""
    M.mark("arming the explosives")
    # the classic view now, while the car stands in the block: the escape's first
    # cruise_to would switch views after Enter (two V presses), and pt6_ste4 lost
    # those seconds of the fuse
    M.ensure_view("classic")
    m0 = msg(); armed = False
    for k in range(8):
        if msg() in ("2004", "2017"):
            # "get back and park": the car is out of the block. Firing now sets the bomb
            # off outside it (pt7_ste2: 2017, then the blast with him inside, 2998)
            say(f"arm: the car is out of the block (msg {msg()}); not firing"); break
        if k == 3: tap("Tab", 0.3); time.sleep(0.5)        # the weapon slot, in case the bomb is not selected
        xdo("keydown", "Control_L"); time.sleep(0.4); xdo("keyup", "Control_L"); time.sleep(1.0)
        if msg() in armed_msgs or (msg() != m0 and M.objective() is None): armed = True; break
    if not armed and msg() in ("2004", "2017"): return False
    say(f"arm: {'armed' if armed else 'no reaction'} (msg {msg()})")
    s = D.wait_state(); cx, cy = s["x"], s["y"]
    # out at once (leave_car's 2 s wait is most of the fuse) and run a routed path
    # ten blocks away from the blast centre (the bomb, and the script's EXPLODEs
    # along the target); pt6_ste1 ran 7 blocks in a fixed direction and died
    tap("Return", 0.3); time.sleep(0.8); M.mark("out of the car, running clear")
    s = D.wait_state()
    blast = blast_at or (cx, cy)
    legs = M.escape_route(world, s, dist=10, away=blast) or M.escape_route(world, s, dist=8)
    if not legs:
        ex, ey = M.escape_point(world, cx, cy, run_level, dist=7); legs = [(ex, ey)]
    say("escape legs:", [(round(a, 1), round(b, 1)) for a, b in legs])
    t_e = time.time()
    for k, (ex, ey) in enumerate(legs[:5]):
        if time.time() - t_e > 9: break
        M.cruise_to(ex, ey, tol=0.8, secs=max(2.0, 9 - (time.time() - t_e)), stop=(k == len(legs[:5]) - 1))
    xdo("keyup", "Up")
    time.sleep(6.0)
    return armed

LIE_LOW_SECS = float(os.environ.get("LIE_LOW_SECS", "20"))   # pt7_ste2/3: level 1 did not go in 150 s standing still
def lie_low(secs=150, why=""):
    """wait for the wanted level to go before taking a fragile mission car: pt7_ste1
    blew stage 1 up, got wanted level 1 from it, walked to the second Pickup with a cop
    behind him and was pulled out of the crawling Pickup and arrested (6159) a block
    short of the barricade. Stand still out of the way and watch the game's own field"""
    w0 = (M.mission_state() or {}).get("wanted", 0)
    if w0 <= 0: return True
    M.mark(f"wanted level {w0}{why}: lying low until it goes")
    secs = min(secs, LIE_LOW_SECS)
    t0 = time.time()
    while time.time() - t0 < secs:
        ms = M.mission_state() or {}
        if ms.get("wanted", 0) <= 0:
            M.mark(f"wanted level gone after {time.time() - t0:.0f} s"); return True
        time.sleep(1.0)
    M.mark(f"still wanted ({(M.mission_state() or {}).get('wanted')}) after {secs} s: going on")
    return False

# ---------------------------------------------------------------- the jobs

def play_ste_re1(entry):
    """BLOW JOB! (Rednecks): a rigged Pickup at (24,41.5) into the 3x1 block
    by Fat Boy Jim's trailer (48.5,20.5); arm (fire), get out; then a second
    Pickup at (24,44.5) into the 3x1 block at the barricade (111.5,77.5)."""
    money0 = money()
    M.SLOW_CAP = 2.0          # the rigged Pickup wrecks on wall hits: crawl
    for stage, (car_at, box) in enumerate((((24.0, 41.5), (48.5, 20.5, 3.0, 1.0)), ((24.0, 44.5), (111.5, 77.5, 3.0, 1.0)))):
        o = wait_arrow(120 if stage else 30, kinds=(3, 4))
        if o: car_at = (o[0], o[1])
        M.mark(f"stage {stage+1}: to the Pickup at {car_at[0]:.1f},{car_at[1]:.1f}")
        s = D.wait_state()
        if s["driving"]: s = M.leave_car()
        lie_low(150, " (the blast)" if stage else "")
        s = enter_parked(car_at[0], car_at[1], budget=200, why=f"the Pickup {stage+1}")
        if not (s and s["driving"]): return f"stuck: pickup {stage+1} not entered"
        FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar{stage+1}")
        o = wait_arrow(20, kinds=(1,))
        x, y, w, h = box if not o else (o[0], o[1], box[2], box[3])
        ok, s = park_in_block(x, y, w, h, money0, parked_msgs=("2005", "2016"))
        ms = M.mission_state() or {}
        say(f"after the park: car damage {ms.get('cardmg')} msg {ms.get('msg')}")
        M.shot(f"{entry['mission']}_block{stage+1}")
        out, ms = M.outcome(money0)
        if out != "running": return out
        cs = D.wait_state(); left_at = (cs["x"], cs["y"])
        arm_and_run(money0, ("2006", "2018"), blast_at=(49.0, 19.3) if stage == 0 else (x, y))
        M.shot(f"{entry['mission']}_blast{stage+1}")
        t0 = time.time()
        while time.time() - t0 < 90:
            out, ms = M.outcome(money0)
            if out != "running": return out
            o = M.objective()
            if stage == 0 and o is not None and o[3] in (3, 4) and (math.hypot(o[0] - left_at[0], o[1] - left_at[1]) > 2.5 or (ms and ms["msg"] in ("2012", "2013"))):
                break          # the arrow moved to the second Pickup (run pd3_ste4 mistook the abandoned first Pickup's own arrow for stage 2)
            if ms and ms["msg"] in ("2008", "2019", "2004", "2017"):      # "get back in and trigger the bomb": the arming did not take
                say("the game wants the bomb armed: back into the car")
                s = enter_parked(x, y, budget=90, why="the Pickup again")
                if s and s["driving"]:
                    # the line-up and park again, not a creep from where it stands (pt8_ste1: four
                    # creeps in place, the game said 2004 each time)
                    ok, s = park_in_block(x, y, w, h, money0, parked_msgs=("2005", "2016"))
                    arm_and_run(money0, ("2006", "2018"))
            time.sleep(1.0)
    o, ms = M.wait_outcome(money0, 120)
    return o

def dealer_stop(x, y, s, lo=0.9, hi=1.1):
    """PLAYTHROUGH-8: where the Z-Type stops for a passenger. LOCATE_ANOTHER_CHARACTER_BY_CAR
    (p1, dealer, 3.0, 3.0) wants the car within 1.5 blocks of him on each axis: a point at
    most `hi` from him on each axis and at least `lo` away (pt8_bil2 drove onto dealer 2's own
    cell and ran him over: 3526, then 3730 within the second; pt8_bil5 stopped on the road
    1.5 blocks off on each axis and he never came), on flat ground at his level, a road
    point preferred, the nearest such point to the car"""
    Ld = next((L for L in range(0, 6) if M.node_kind(world, int(x), int(y), L)), 1)
    best = None
    for k in range(-10, 11):
        for m in range(-10, 11):
            dx, dy = k * hi / 10.0, m * hi / 10.0
            if math.hypot(dx, dy) < lo: continue
            px, py = x + dx, y + dy
            nk = M.node_kind(world, int(px), int(py), Ld)
            if not nk or nk[0] != "flat" or nk[1] not in (1, 2): continue
            c = math.hypot(px - s["x"], py - s["y"]) + (0.0 if nk[1] == 1 else 4.0) + 3.0 * (1.6 - math.hypot(dx, dy))   # away from his feet
            if best is None or c < best[0]: best = (c, px, py)
    return (best[1], best[2]) if best else None

def not_over(money0, secs=15):
    """PLAYTHROUGH-8: BUSTED is not the end of RUSSIAN SAILORS: the police pulled him out of the
    Z-Type (pt8_bil10, pt8_bil19: wanted level 1 from the dealer-1 leg, the car at a standstill),
    the death/arrest word went up for a moment and the runner returned "dead"; the game said
    "Stop wasting time, Comrade! Get back in the Z-Type NOW!" (3525) and the job ran on. True
    when, after the respawn, the job is still running"""
    t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(1.0); ms = M.mission_state() or {}
        if ms.get("msg") in M.FAILED_KEYS: return False
        if ms.get("msg") == "3525" or (ms.get("death", 0) == 0 and ms.get("health", 0) > 0 and M.mission_arrows()):
            say(f"busted or down, but the job runs on (msg {ms.get('msg')}): back to the Z-Type")
            M.LIVES0[0] = ms.get("lives", M.LIVES0[0]); return True
    return False

def play_bil_re2(entry):
    """MMM, RUSSIAN SAILORS! (Russians): the Z-Type at (48,73); four dealers
    to collect by car (horn beside each), then the car into the crane box at
    (135.5,5.5) and out of it: the crane dumps it in the water."""
    money0 = money()
    M.SLOW_CAP = 2.0          # the Z-Type burned after wall hits at cap 3.0 (run pd3_bil3): crawl
    M.FAST_CAP = 4.0          # PLAYTHROUGH-8: borrowed cars to the Z-Type burned at 5.5 (pt8_bil5/6/8: two or three a session)
    # PLAYTHROUGH-8: the flyover on the dealer-1 road (columns 54-57, ramps at rows 141-148 and
    # 158-165, a two-wide level-2 deck between): the Z-Type stalled at its south end
    # (55-57,157) eight times in pt8_bil13 and pt8_bil14, 10000 carhp each time. Off the route
    M.CAR_AVOID.update({(xx, yy) for xx in range(54, 58) for yy in range(141, 166)})
    # and the car-shop strip at 58-70 x 88-92 (bomb, mines, oil, gun and respray drive-ins on
    # the dealer-1 road): pt8_bil22's Z-Type lost 7000 in one hit at 70.9,91.6 there
    M.CAR_AVOID.update({(xx, yy) for xx in range(58, 71) for yy in range(88, 93)})
    dealers = [(95.5, 171.5), (46.0, 187.0), (13.5, 233.5), (85.0, 147.0)]
    o = wait_arrow(30, kinds=(3, 4))
    car_at = (o[0], o[1]) if o else (48.0, 73.0)
    s = D.wait_state()
    if s["z"] > 3.2 and os.environ.get("WARP_OK", "1") == "1" and not (s.get("parked") and s["pd"] < 8):
        # only when no car stands by: the rooftop is a car park (pt6_bil4 drove up to
        # two blocks from the phone), and the warp down from z=6 killed him four seconds
        # later (a fall, as far as the game knows: 4223, JOB FAILED)
        near = M.street_cell_near(world, s["x"], s["y"], radius=12)
        if near:
            say(f"the phone's terrace is at z={s['z']:.1f}; developer warp down to the street at {near[0]},{near[1]}")
            set_view("classic"); s = M.scene_warp(near[0], near[1], near[2], "down from the rooftop phone"); set_view("third")
    tries = 0
    if os.environ.get("RS_WALK", "1") == "1" and not s["driving"]:
        # PLAYTHROUGH-8: walk the 140 blocks from the phone to the Z-Type: the borrowed cars on
        # that road burned two or three times a session (pt8_bil5/6/8/9: 5-10 minutes of wall
        # time), the walker does it in about three (pt8_bil2: 423 cells)
        M.mark("walking to the Z-Type"); tries = 4
    while s and math.hypot(car_at[0] - s["x"], car_at[1] - s["y"]) > 40 and tries < 4:
        # by car, again after a drive that ended far off (pt6_bil3: the borrowed car
        # was lost 140 blocks out and the runner set off on a 417-cell walk)
        tries += 1
        M.mark(f"the Z-Type is {math.hypot(car_at[0] - s['x'], car_at[1] - s['y']):.0f} blocks away: by car (leg {tries})")
        s = D.wait_state()
        if not s["driving"]: s = M.any_car2(world, budget=120)
        if not (s and s["driving"]):
            # no car to be had (pt7_bil4 waited at the same kerb through four legs, eight
            # minutes, 86 blocks from the Z-Type): walk it
            M.mark("no car stopped: walking to the Z-Type"); break
        if s and s["driving"]:
            FP["until"] = 0.0
            # stop well short: pt7_bil3 arrived at speed and rammed the Z-Type three times
            # (its carhp dropped 28756 -> 25994 in one second) before the walk to its door
            s = M.drive3(world, car_at[0], car_at[1], tol=9.0, budget=420, view_switch=view_switch, slow=False)
            if s and s["driving"]: s = M.leave_car()
        s = D.wait_state()
    o = M.objective()
    if o and o[3] in (3, 4): car_at = (o[0], o[1])
    s = enter_parked(car_at[0], car_at[1], budget=720, why="the Z-Type")
    if not (s and s["driving"]): return "stuck: the Z-Type not entered"
    FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar")
    t0 = time.time()                      # the arrow keeps the car's position for a moment after entry (run pd3_bil4 read it as "dealer 1 at 48,73")
    while time.time() - t0 < 20:
        o = M.objective(); s = D.wait_state()
        if o and math.hypot(o[0] - s["x"], o[1] - s["y"]) > 3.0: break
        time.sleep(0.5)
    s = D.wait_state()
    if s["driving"] and math.hypot(s["x"] - 48.0, s["y"] - 73.0) < 3.0:
        # PLAYTHROUGH-8: the Z-Type stands in the two-wide alley at 47-48 x 67-78, facing south,
        # where the way out south is one block wide between a slope and a wall: pt8_bil4 pressed
        # it eight times there (31847 -> 15905, alight before dealer 1). Back straight out north
        # to the road on rows 65-66 first; the dealer legs start from there
        M.mark("the Z-Type backs out of its alley to the road")
        still = 0
        for k_r in range(20):
            s0 = D.wait_state()
            if s0["y"] < 67.2: break
            hold("Down", 0.6); time.sleep(0.25); s1 = D.wait_state()
            if math.hypot(s1["x"] - s0["x"], s1["y"] - s0["y"]) < 0.05:
                still += 1
                if still >= 3: break
            else: still = 0
        hold("space", 0.4); s = D.wait_state()
        say(f"backed out to {s['x']:.1f},{s['y']:.1f} (carhp {(M.mission_state() or {}).get('carhp')})")
        if s["y"] < 67.5:
            # out: never back through it (only then: from inside it an avoided alley leaves
            # the router no way out, and drive3 falls back to a straight line, pt8_bil6)
            for yy in range(67, 79):
                for xx in (46, 47, 48, 49): M.CAR_AVOID.add((xx, yy))
    stage = 0
    t_all = time.time()
    while time.time() - t_all < 1500:
        out, ms = M.outcome(money0)
        if out == "dead" and not_over(money0): out = "running"
        if out != "running": return out
        s = D.wait_state()
        if not s["driving"]:
            o = M.objective()
            tc_ = (ms or {}).get("tcar") or (0.0, 0.0)
            if o and ((o[3] in (3, 4) and ms and ms["msg"] in ("3525",)) or o[3] == 0 or (tc_[0] > 0 and math.hypot(o[0] - tc_[0], o[1] - tc_[1]) < 1.5)):
                # (PLAYTHROUGH-8: after an arrest the arrow on the Z-Type came back as kind 0 with no
                # 3525, pt8_bil10, and the loop said 'not handled' for minutes)
                M.mark("back to the Z-Type"); s = enter_parked(o[0], o[1], budget=120, why="the Z-Type"); continue
        o = wait_arrow(40)
        if o is None:
            time.sleep(2.0); continue
        x, y, z, kind = o[0], o[1], o[2], o[3]
        if kind in (2, 3, 4) and stage < 4:
            # the dealer's arrow is a character arrow (kind 2; pt6_bil1 waited 3 min
            # in the Z-Type on it while only kinds 3/4 were taken for dealers)
            M.mark(f"dealer {stage+1}: by car to {x:.1f},{y:.1f}")
            key0 = M.objective_key(); m0 = msg()
            sp = dealer_stop(x, y, s)
            say(f"dealer {stage+1} at {x:.1f},{y:.1f}: the car stops at {sp}")
            if sp: s = M.drive3(world, sp[0], sp[1], tol=0.6, budget=360, view_switch=view_switch, slow=True, precious=True)
            else: s = M.drive3(world, x, y, tol=2.6, budget=360, view_switch=view_switch, slow=True, precious=True)
            M.shot(f"{entry['mission']}_dealer{stage+1}")
            t0 = time.time(); boarded = False; spot = 0; t_spot = time.time()
            while time.time() - t0 < 160:
                cur = msg()
                # a fresh "aboard" brief only: pt7_bil6 took dealer 2's 3530, still in the
                # message buffer, for dealer 3 aboard, waited 100 s and moved on without him
                if cur != m0 and cur in ("3527", "3529", "3531", "3533", "3528", "3530", "3532", "3534"): boarded = True
                if M.objective_key() != key0 and boarded: break
                if time.time() - t_spot > 20 and not boarded:
                    # he does not come (pt7_bil6: dealer 3 stood 2 blocks off the Z-Type at the
                    # Escobar Power Cores for 100 s of horns): move the car round him
                    spot += 1; t_spot = time.time()
                    ang = spot * 1.5708
                    px, py = x + 2.2 * math.cos(ang), y + 2.2 * math.sin(ang)
                    s_side = dict(s); s_side["x"], s_side["y"] = px, py
                    sp3 = dealer_stop(x, y, s_side)
                    if sp3: px, py = sp3
                    say(f"dealer {stage+1}: not coming; moving the car to {px:.1f},{py:.1f} (spot {spot})")
                    s = M.drive3(world, px, py, tol=1.0, budget=40, slow=True, precious=True)
                o3 = M.objective()
                if o3 and math.hypot(o3[0] - x, o3[1] - y) > 8.0:
                    # the arrow is on the next dealer (or the crane box): this one is aboard.
                    # pt6_bil2 missed the 1-second "aboard" brief (3527, then 3528) and sat
                    # 100 s at each dealer in traffic
                    boarded = True; break
                if M.objective_key() != key0 or cur == "3526":
                    M.horn(2); time.sleep(2.5)
                else:
                    o2 = M.objective()
                    if o2 and math.hypot(o2[0] - s["x"], o2[1] - s["y"]) > 3.2:
                        sp2 = dealer_stop(o2[0], o2[1], s)
                        if sp2: s = M.drive3(world, sp2[0], sp2[1], tol=0.6, budget=60, slow=True, precious=True)
                    M.horn(1); time.sleep(2.0)
                out, ms = M.outcome(money0)
                if out == "dead" and not_over(money0): out = "running"; break
                if out != "running": return out
            say(f"dealer {stage+1}: {'boarded' if boarded else 'not confirmed'} after {time.time()-t0:.0f}s")
            o4 = M.objective()
            if boarded or (o4 and math.hypot(o4[0] - x, o4[1] - y) > 8.0): stage += 1
            else: M.mark(f"dealer {stage+1} not aboard: the same dealer again")
            continue
        if kind not in (1, 2, 3, 4):
            say(f"arrow of kind {kind} at {x:.1f},{y:.1f}: not handled"); time.sleep(2.0); continue
        if kind == 1 or stage >= 4:
            M.mark(f"to the crane box at {x:.1f},{y:.1f}")
            s = M.drive3(world, x, y, tol=2.0, budget=420, view_switch=view_switch, slow=True, precious=True)
            ok, s = creep_box(x, y, 7.0, 7.0, money0, secs=40)
            M.shot(f"{entry['mission']}_cranebox")
            M.leave_car(); M.mark("out of the car in the crane box")
            s = D.wait_state()
            ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=6)
            M.cruise_to(ex, ey, tol=1.0, secs=8)
            o, ms = M.wait_outcome(money0, 240)
            if o == "running":
                cur = msg()
                if cur == "3538":                       # "the car left the box": back in and park again
                    s = enter_parked(x, y, budget=90, why="the Z-Type in the crane box")
                    if s and s["driving"]:
                        creep_box(x, y, 7.0, 7.0, money0, secs=40); M.leave_car()
                        o, ms = M.wait_outcome(money0, 240)
            return o
    return "timeout"

def play_ste_re2(entry):
    """DOUBLE-CROSS CRUSH! (Rednecks, ste_re2.mis): a Zaibatsu Z-Type (model 70) stolen, the
    Scientists' zone (arrow 227.5,217.5): 50 Scientists (remap 7) run over with it under the
    game's BY_VEHICLE bonus count (brief 2026 starts it, 2028 passes it, 2037 fails it); then a
    Stratos-B (model 48) to the Zaibatsu zone (199,25.5) and 50 Zaibatsu (remap 8) the same way
    (2033 / 2035); 2999 Mission Complete. The targets come from the renderer's 'view: peds'
    line (PLAYTHROUGH-9)."""
    money0 = money()
    stages = [dict(model=(70,), remaps=(7,), zone=(227.5, 217.5), done=("2028",), name="Scientists",
                   search=[(199.0, 25.5), (180.5, 40.5), (215.5, 60.5), (160.5, 20.5)]),
              dict(model=(48,), remaps=(8,), zone=(199.0, 25.5), done=("2035", "2999"), name="Zaibatsu",
                   search=[(199.0, 25.5), (180.5, 40.5), (215.5, 60.5), (227.5, 217.5)])]
    fail = ("2037", "2998", "2025", "2032")
    for k, st in enumerate(stages):
        for attempt in range(6):
            M.mark(f"stage {k+1}: a model {st['model']} for the {st['name']}")
            s = M.steal_model(world, st["model"], st["search"], budget=900, view_switch=view_switch)
            if not (s and s["driving"] and s.get("cmodel") in st["model"]):
                return "no car"
            M.shot(f"{entry['mission']}_car{k+1}")
            M.mark(f"stage {k+1}: to the {st['name']} zone {st['zone']}")
            s = M.drive3(world, st["zone"][0], st["zone"][1], tol=6.0, budget=600, view_switch=view_switch)
            r, kills = M.run_over(world, st["remaps"], st["done"], fail, st["zone"], money0, secs=1500, view_switch=view_switch)
            M.mark(f"stage {k+1}: run_over {r}, {kills} counted"); M.shot(f"{entry['mission']}_stage{k+1}_{r}")
            if r == "done": break
            if r == "failed": return "failed"
            out, ms = M.outcome(money0)
            if out not in ("running",): return out
            # on foot or a burning car: another car of the model (the bonus keeps its count)
        else:
            return "gave up"
    o, ms = M.wait_outcome(money0, 30)
    M.shot(f"{entry['mission']}_end")
    return o

PLAYS = {"ste_re1": play_ste_re1, "bil_re2": play_bil_re2, "ste_re2": play_ste_re2}

results = {}
for name in wanted:
    entry = next((m for m in world.db["missions"] if m.get("mission") == name), None)
    if not entry: say("no such mission", name); continue
    M.mark(f"mission {name}: {entry.get('title','')}")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = answer(entry)
    say("answered:", ok, key); M.shot(f"{name}_phone")
    if not ok:
        results[name] = "phone not answered"; M.mark(f"mission {name}: phone not answered"); continue
    started = TITLES.get(key)
    if started and started.get("mission") != name:
        say(f"the phone next door answered: {started['mission']} {started.get('title','')}")
        M.mark(f"mission {started['mission']}: {started.get('title','')} (started instead of {name})")
        entry = started; name = started["mission"]
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    play = PLAYS.get(name)
    if not play:
        say("no script for", name); results[name] = "no script"; continue
    r = play(entry)
    results[name] = f"{r} ({time.time()-t_m:.0f}s)"
    if r == "complete": M.DONE_PHONES.add((entry["x"], entry["y"]))
    M.mark(f"mission {name}: {results[name]}"); M.shot(f"{name}_end")
    time.sleep(4)
    if r == "dead": time.sleep(12)
say("RESULTS", results)
M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
