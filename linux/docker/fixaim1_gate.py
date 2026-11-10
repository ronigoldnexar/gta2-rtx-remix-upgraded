#!/usr/bin/env python3
"""FIX-AIM-1 (owner10nov B9) punch gate: in each view (GATE_VIEWS, default third,first) throw GATE_SWINGS (10)
single punches at a standing civilian within arm's reach on the wil Downtown pavement, the way a player does:
walk up to him turned roughly his way (GATE_FACE_TOL radians, default 0.35, ~20 degrees), stop, one tap of the fist.
A swing lands when any civilian within 1.8 blocks loses health or goes down within 0.9 s (the game's own ped pool,
'view: peds'). Every swing is a mark with the distance and the angle off at the press; the result per view at the end.
Needs GTA2_DIRECT_KEYS=1 (arrows the game's own), GTA2DX9_STATE_EVERY=3, GTA2DX9_PEDS_EVERY=3, GTA2DX9_LOG_AIM=1.
keys script: keys_fixaim1.sh."""
import math, os, sys, time
sys.path.insert(0, "/work")
import fa3_demo as F   # noqa: E402  (its probe runs only as __main__)
D, M, Q, T = F.D, F.M, F.Q, F.T
say, tap, hold, xdo, mark = F.say, F.tap, F.hold, F.xdo, F.mark
TOL = float(os.environ.get("GATE_FACE_TOL", "0.35"))
N = int(os.environ.get("GATE_SWINGS", "10"))
REACHES = [float(v) for v in os.environ.get("GATE_REACH", "0.95").split(",")]   # cycled per swing (a sweep)
HOLDS = [float(v) for v in os.environ.get("GATE_HOLD", "0.12").split(",")]      # fist key hold, cycled per swing


def civ_near(s, within, exclude):
    return [(d, p) for d, p in F.civilians(s, within) if p["id"] not in exclude]


def swing_once(s, p, hold_t):
    pool0 = {q["id"]: (q["hp"], q["state"]) for q in M.peds()}
    d = math.hypot(p["x"] - s["x"], p["y"] - s["y"]); a = D.angle_to(s, p["x"], p["y"])
    tap("Control_L", hold_t)
    t0 = time.time(); hit = None
    while time.time() - t0 < 0.9 + hold_t and not hit:
        time.sleep(0.05)
        s2 = D.wait_state()
        for q in M.peds():
            h = pool0.get(q["id"])
            if not h or q["type"] != "civ": continue
            if math.hypot(q["x"] - s2["x"], q["y"] - s2["y"]) > 1.8: continue
            if q["hp"] < h[0] or (q["state"] == 8 and h[1] != 8):
                hit = (q["id"], h[0], q["hp"], q["state"]); break
    return d, a, hit


def gate(view, budget):
    F.view_to(view, f"{view} for the punch gate"); time.sleep(1.0)
    swings = []; t_end = time.time() + budget; target = None; downed = set(); lost = 0
    while len(swings) < N and time.time() < t_end:
        s = D.wait_state()
        if s["driving"]: tap("Return", 0.3); time.sleep(2); continue
        if F.current_view() != view: F.view_to(view, "back to the gate's view")
        c = civ_near(s, 10.0, downed)
        if not c:
            far = F.BOX[1] - 1.5 if s["x"] < (F.BOX[0] + F.BOX[1]) / 2 else F.BOX[0] + 1.5
            F.step_to(far, F.PAV_Y, tol=0.5, secs=6); continue
        d, p = c[0]
        if p["id"] != target: target = p["id"]; say(f"gate {view}: target civ {target} d={d:.2f}")
        a = D.angle_to(s, p["x"], p["y"])
        if abs(a) > TOL:
            hold(F.turn_key(a), min(abs(a) / D.rate, 0.25)); time.sleep(0.12); continue
        reach = REACHES[len(swings) % len(REACHES)]; hold_t = HOLDS[(len(swings) // len(REACHES)) % len(HOLDS)]
        if d > reach:
            hold("Up", min(0.5, max(0.08, (d - 0.7) / 2.0))); time.sleep(0.1); continue
        time.sleep(0.15)
        s = D.wait_state()
        pp = next((q for q in M.peds() if q["id"] == target), None)
        if not pp: continue
        d, a, hit = swing_once(s, pp, hold_t)
        n = len(swings) + 1
        if hit:
            mark(f"GATE {view} swing {n}: HIT civ {hit[0]} hp {hit[1]} -> {hit[2]} state {hit[3]} (aimed at {target} d={d:.2f} off={math.degrees(a):+.0f} hold={hold_t})")
            if hit[3] == 8: downed.add(hit[0])
        else:
            mark(f"GATE {view} swing {n}: MISS at civ {target} d={d:.2f} off={math.degrees(a):+.0f} hold={hold_t} reach={reach}")
        swings.append(bool(hit))
        time.sleep(0.5)
    k = sum(swings)
    mark(f"GATE RESULT {view}: {k}/{len(swings)} punches landed")
    return k, len(swings)


mark("gate start")
s = D.wait_state(40)
if not s: mark("NO PLAYER STATE"); sys.exit(1)
D.calibrate_turn()
res = {}
for view in os.environ.get("GATE_VIEWS", "third,first").split(","):
    T.warp(F.WEST + 6.0, F.PAV_Y, 2, why="fixaim1 gate: the pavement"); time.sleep(2.0)
    F.view_to(view, "after the warp"); time.sleep(10.0)
    res[view] = gate(view, int(os.environ.get("GATE_SECS", "150")))
mark("GATE SUMMARY " + " ".join(f"{v}={k}/{n}" for v, (k, n) in res.items()))
mark("end")
say("done")
