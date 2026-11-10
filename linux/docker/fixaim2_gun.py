#!/usr/bin/env python3
"""FIX-AIM-2 (owner10nov B9b) gun gate: in each view (GUN_VIEWS, default third,first) and at each range band
(GUN_BANDS, default 2,4,6 blocks, +-GUN_BAND_W 0.6), GUN_SHOTS (20) single pistol shots at a standing civilian on the
wil Downtown pavement who is inside the reticle: turned onto him to within GUN_TOL radians (0.12, ~7 degrees) at the
band's distance, then one tap of the fire key. Each shot's verdict is the renderer's own per-shot line
('aim: shot N ... -> TARGET' or 'NO TARGET: <class>', GTA2DX9_LOG_AIM=1); a hit is an 'aim: hit' line within 1.2 s.
The result per view and band: with_target share and hit share. Re-arms after a bust. Run with GTA2_DIRECT_KEYS=1,
GTA2DX9_STATE_EVERY=3, GTA2DX9_PEDS_EVERY=3, GTA2DX9_LOG_AIM=1, GTA2DX9_FORCE_WANTED_MAX=0 (no arrests), INI_SED set_player_ammo=300 and scene_key=F11.
keys: keys_fixaim2_gun.sh."""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import fa3_demo as F   # noqa: E402
D, M, Q, T = F.D, F.M, F.Q, F.T
say, tap, hold, mark = F.say, F.tap, F.hold, F.mark
TOL = float(os.environ.get("GUN_TOL", "0.12"))
N = int(os.environ.get("GUN_SHOTS", "20"))
BW = float(os.environ.get("GUN_BAND_W", "0.6"))
BUDGET = float(os.environ.get("GUN_BAND_SECS", "150"))
PAVEMENT_ONLY = os.environ.get("GUN_PAVEMENT_ONLY", "1") == "1"   # targets on the pavement strip: the fire runs along it, not into the traffic (a machine-gunned car's blast killed him, fixaim2_g5)
STALL = float(os.environ.get("GUN_STALL_SECS", "12"))


class Tail:
    def __init__(self):
        with open(D.LOG, "rb") as f: f.seek(0, 2); self.off = f.tell()
        self.rest = b""

    def lines(self):
        with open(D.LOG, "rb") as f: f.seek(self.off); data = f.read(); self.off += len(data)
        data = self.rest + data; cut = data.rfind(b"\n") + 1; self.rest = data[cut:]
        return [l.rstrip("\r") for l in data[:cut].decode("latin-1").splitlines()]


def pick(x, y, lvl, name):
    T.warp(x, y, lvl, why=name)
    hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
    s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
    mark(f"pickup {name} at {s['x']:.2f},{s['y']:.2f}")
    time.sleep(0.8)


def weapon_now():
    m = None
    for m in re.finditer(r"view: mission .*? weapon=(\w+)", D.log_tail()[-20000:]): pass
    return m.group(1) if m else "?"


def rearm(view):
    mark("GUN weapon gone (busted/wasted): re-arming")
    time.sleep(3.0); pick(166.5, 140.5, 2, "pistol")
    T.warp(F.WEST + 6.0, F.PAV_Y, 2, why="fixaim2 gun gate: back to the pavement"); time.sleep(2.0)
    F.view_to(view, "after re-arming"); time.sleep(1.0)


WARPS = [F.WEST + 2.0, F.WEST + 6.0, F.WEST + 10.0, F.WEST + 14.0]
_warp_n = [0]


def back_to_pavement(view, why):
    """the civilians scatter after the shots and he wanders off chasing them: back to the pavement, another spot"""
    _warp_n[0] += 1
    T.warp(WARPS[_warp_n[0] % len(WARPS)], F.PAV_Y, 2, why=f"fixaim2 gun gate: {why}"); time.sleep(1.5)
    F.view_to(view, "after the warp"); time.sleep(1.0)


def band(view, dist, tail):
    shots = []   # (target?, class, hit?)
    t_end = time.time() + BUDGET
    last_shot = time.time()
    while len(shots) < N and time.time() < t_end:
        if weapon_now() == "none": rearm(view); last_shot = time.time(); continue
        s = D.wait_state()
        if s["driving"]: tap("Return", 0.3); time.sleep(2); continue
        if time.time() - last_shot > STALL or abs(s["y"] - F.PAV_Y) > 1.6 or not (150.0 < s["x"] < 174.0):
            back_to_pavement(view, "no shot for a while" if time.time() - last_shot > STALL else "off the pavement")
            last_shot = time.time(); continue
        if F.current_view() != view: F.view_to(view, "back to the gate's view")
        c = sorted([(math.hypot(p["x"] - s["x"], p["y"] - s["y"]), p) for p in M.peds()
                    if p["car"] is None and p["type"] == "civ" and M.ped_alive(p) and abs(p["z"] - s["z"]) < 0.6], key=lambda t: t[0])
        c = [t for t in c if t[0] < 12.0 and (not PAVEMENT_ONLY or F.in_box(t[1]["x"], t[1]["y"]))]
        if not c:
            far = F.BOX[1] - 1.5 if s["x"] < (F.BOX[0] + F.BOX[1]) / 2 else F.BOX[0] + 1.5
            F.step_to(far, F.PAV_Y, tol=0.5, secs=6); continue
        inband = [(abs(D.angle_to(s, p["x"], p["y"])), d, p) for d, p in c if abs(d - dist) <= BW]
        if not inband:
            d, p = c[0]
            a = D.angle_to(s, p["x"], p["y"])
            if abs(a) > 0.3: hold(F.turn_key(a), min(abs(a) / D.rate, 0.3)); time.sleep(0.12); continue
            if d > dist: hold("Up", min(0.6, max(0.1, (d - dist) / 2.5)))
            else: hold("Down", min(0.6, max(0.1, (dist - d) / 2.0)))
            time.sleep(0.1); continue
        _, d, p = min(inband, key=lambda t: t[0])
        a = D.angle_to(s, p["x"], p["y"])
        if abs(a) > TOL:
            hold(F.turn_key(a), max(0.03, min(abs(a) / D.rate, 0.25))); time.sleep(0.12); continue
        tail.lines()
        tap("Control_L", 0.1)
        t0 = time.time(); got = None; hit = False
        while time.time() - t0 < 1.4:
            time.sleep(0.1)
            for l in tail.lines():
                m = re.search(r"aim: shot (\d+) .*-> (TARGET|NO TARGET: (\w+))(.*)", l)
                if m and not got: got = (m.group(2) == "TARGET", m.group(3) or "target", m.group(4).strip())
                elif "aim: hit " in l and got: hit = True
        if not got: mark(f"GUN {view} {dist:.0f}: tap at civ {p['id']} d={d:.2f} off={math.degrees(a):+.1f} gave no shot line"); time.sleep(0.3); continue
        shots.append((got[0], got[1], hit)); last_shot = time.time()
        mark(f"GUN {view} {dist:.0f} shot {len(shots)}: civ {p['id']} d={d:.2f} off={math.degrees(a):+.1f} -> "
             f"{'TARGET' if got[0] else 'NO TARGET ' + got[1]} {got[2]} {'HIT' if hit else 'miss'}")
        time.sleep(0.2)
    n = len(shots); k = sum(1 for t in shots if t[0]); h = sum(1 for t in shots if t[2])
    cls = {}
    for t in shots:
        if not t[0]: cls[t[1]] = cls.get(t[1], 0) + 1
    mark(f"GUN RESULT {view} {dist:.0f} blocks: with_target {k}/{n} ({100.0 * k / max(1, n):.0f}%) hits {h}/{n} ({100.0 * h / max(1, n):.0f}%) no-target classes {cls}")
    return k, h, n


mark("gun gate start")
s = D.wait_state(40)
if not s: mark("NO PLAYER STATE"); sys.exit(1)
D.calibrate_turn()
pick(166.5, 140.5, 2, "pistol")
res = {}
for view in os.environ.get("GUN_VIEWS", "third,first").split(","):
    T.warp(F.WEST + 6.0, F.PAV_Y, 2, why="fixaim2 gun gate: the pavement"); time.sleep(2.0)
    F.view_to(view, "after the warp"); time.sleep(8.0); F.view_to(view, f"{view} (again)")
    for b in [float(v) for v in os.environ.get("GUN_BANDS", "2,4,6").split(",")]:
        res[(view, b)] = band(view, b, Tail())
time.sleep(11.0)
lines = [l for l in open(D.LOG, encoding="latin-1") if "aim: shots=" in l or "aim: no_target=" in l]
for l in lines[-2:]: mark("counter: " + l.split("] ", 1)[-1].strip())
mark("GUN SUMMARY " + " ".join(f"{v}@{b:.0f}=target {k}/{n} hit {h}/{n}" for (v, b), (k, h, n) in res.items()))
mark("end")
say("done")
