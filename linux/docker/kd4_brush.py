#!/usr/bin/env python3
"""FIX-KNOCKDOWN-4 pfl38 ped half: drive the F9 van through the wil plaza crowd so the car passes peds at OFF block
from her (centre line; 0.45 = a near miss / flank brush, not the game's run-over), throttle pulsed (~2-4 b/s),
one 30 fps burst per view (KD4_VIEWS, default first,third), KD4_SECS each."""
import os, sys, time, math
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
import feel17_probe as X
vto = X.vto
OFF = float(os.environ.get("KD4_OFF", "0.45"))
def peds():
    m = None
    for m in F.PEDS.finditer(F.Q.log_text(30000)): pass
    out = []
    if not m: return out
    for tok in m.group(1).split():
        f = tok.split(":")
        try:
            x, y, z = (float(v) for v in f[4].split(","))
            if int(f[5]) in (8, 9) or int(f[7]) <= 0: continue
            out.append((int(f[0]), x, y))
        except (IndexError, ValueError): pass
    return out
def enter_street():
    T.warp(164.5, 147.6, 2, why="street"); time.sleep(2); vto("third", 5.0)
    tap("F9", 0.3); time.sleep(4.5)
    hold("Left", 0.55); hold("Up", 0.9); time.sleep(0.4); hold("Left", 0.5); time.sleep(0.8)
    tap("Return", 0.3)
    t0 = time.time()
    while not driving() and time.time() - t0 < 5: time.sleep(0.2)
    if not driving(): into_car()
    mark(f"entered {driving()}"); time.sleep(1.5)
def cal_car():
    down("Up"); time.sleep(0.8); s0=D.wait_state(); f0=(s0['fx'],s0['fy'])
    down("Left"); time.sleep(0.5); up("Left"); time.sleep(0.2); s1=D.wait_state(); up("Up")
    turn=math.atan2(f0[0]*s1['fy']-f0[1]*s1['fx'], f0[0]*s1['fx']+f0[1]*s1['fy'])
    D.left_sign = 1 if turn>0 else -1
    D.rate = max(0.5, abs(turn)/0.5)
    mark(f"car cal turn {turn:+.2f} sign {D.left_sign} rate {D.rate:.2f}")
    down("Down"); time.sleep(1.2); up("Down")
LOCK = {"id": None, "t": 0.0}
def target(s):
    fl = math.hypot(s['fx'], s['fy']) or 1.0; fx, fy = s['fx']/fl, s['fy']/fl
    ps = peds(); best = None
    if LOCK["id"] is not None and time.time() - LOCK["t"] < 5.0:
        for pid, x, y in ps:
            if pid != LOCK["id"]: continue
            dx, dy = x - s['x'], y - s['y']; d = math.hypot(dx, dy)
            if dx*fx + dy*fy > -0.4 and d < 9: best = (0, d, x, y)
    if best is None:
        LOCK["id"] = None
        for pid, x, y in ps:
            dx, dy = x - s['x'], y - s['y']; d = math.hypot(dx, dy)
            if d < 1.5 or d > 9: continue
            ahead = (dx*fx + dy*fy) / d
            if ahead < 0.5: continue
            sc = d * (2.0 - ahead)
            if best is None or sc < best[0]: best = (sc, d, x, y); LOCK["cand"] = pid
        if best: LOCK["id"] = LOCK["cand"]; LOCK["t"] = time.time(); mark(f"lock ped {LOCK['id']} d={best[1]:.2f}")
    if not best: return None
    _, d, x, y = best
    cr = fx*(y - s['y']) - fy*(x - s['x']); sg = 1.0 if cr > 0 else -1.0
    nx, ny = -fy, fx
    return d, x, y, x - sg*nx*OFF, y - sg*ny*OFF
def drive(secs):
    t0 = time.time(); last = None; n = 0; ph = 0
    while time.time() - t0 < secs:
        s = D.wait_state(5)
        if not s: continue
        # throttle pulse: about 2-4 blocks/s
        ph += 1
        b = target(s)
        if ph % int(os.environ.get("KD4_PULSE","4")) == 0 or (b and b[0] < 2.5 and ph % 2 == 0): up("Up")
        else: down("Up")
        up("Left"); up("Right")
        if b:
            d, px, py, tx, ty = b
            a = D.angle_to(s, tx, ty)
            if abs(a) > 0.06: down("Left" if (a > 0) == (D.left_sign > 0) else "Right")
            if d < 2.0 and n < 60: n += 1; mark(f"near ped d={d:.2f} at {px:.2f},{py:.2f} me {s['x']:.2f},{s['y']:.2f}")
        elif ph % 20 == 0:
            # no ped ahead: turn toward the plaza centre
            a = D.angle_to(s, 159.5, 139.5)
            if abs(a) > 0.3: down("Left" if (a > 0) == (D.left_sign > 0) else "Right")
        time.sleep(0.1)
    up("Up"); up("Left"); up("Right")
def jack():
    for _ in range(4):
        if driving(): return True
        tap("Return", 0.3)
        t0 = time.time()
        while time.time() - t0 < 6:
            if driving(): return True
            time.sleep(0.3)
    return driving()
def seg(view):
    if not driving() and os.environ.get("KD4_LANE", "0") == "1":
        tap("F11", 0.3); time.sleep(3.0); vto("third", 3.0); mark(f"lane jack {jack()}")
    if not driving(): enter_street()
    vto(view, 3.0)
    cal_car()
    t0=time.time(); down("Up")
    while time.time()-t0<(float(os.environ.get('KD4_PLAZA','12'))):
        s=D.wait_state(); d=((s['x']-159.5)**2+(s['y']-139.5)**2)**0.5
        if d<6: break
        a=D.angle_to(s,159.5,139.5); up("Left"); up("Right")
        if abs(a)>0.1: hold("Left" if (a>0)==(D.left_sign>0) else "Right", min(abs(a)/D.rate,0.2))
        time.sleep(0.1)
    up("Up"); s=D.wait_state(); mark(f"at plaza {s['x']:.1f},{s['y']:.1f}")
    secs = float(os.environ.get("KD4_SECS", "28"))
    p = burst(f"kd4_{view}_{int(time.time())%1000}", secs + 1.0); time.sleep(0.3)
    drive(secs)
    p.wait(); mark(f"end {D.wait_state()}"); A.save_log()
    down("Down"); time.sleep(1.0); up("Down")
for v in os.environ.get("KD4_VIEWS", "first,third").split(","):
    try: mark(f"segment {v}"); seg(v)
    except Exception as e: mark(f"segment {v} failed: {e!r}")
A.save_log()
