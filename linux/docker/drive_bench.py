#!/usr/bin/env python3
"""PLAYTHROUGH-9: wall hits per 100 blocks on a fixed Downtown route, for the driver in use
(DRIVER=classic: mission_lib.drive3 as of PLAYTHROUGH-8; DRIVER=smooth: drive3_smooth).

A car from the kerb near the spawn, a drive to the start (not measured), then the measured
route: (246.5,130.5) on the level-3 ramp -> (214.5,209.5) -> (164.5,125.5), about 312 road
blocks (the second and third legs of WHEELER-DEALING's dealer run). A thread samples the log
ten times a second: the distance the player's car moved, and every carhp loss of 250 or
more between two mission lines, called a car contact when another car stood within 2.4
blocks of it ('view: cars') and a wall hit otherwise. Writes /out/bench.json."""
import json, math, os, sys, threading, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say = D.say
VIEW = ["classic"]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        D.tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name

START = (246.5, 130.5)
ROUTE = [(215.5, 209.3), (168.5, 123.2)]   # the WHEELER-DEALING lane stops (road cells)
STAT = dict(measuring=False, dist=0.0, hits=[], fires=0, cars=0, legs=[])

def sampler():
    last = None; last_hp = -1; was_fire = False; car_model = None
    while True:
        time.sleep(0.1)
        s = D.state(); ms = M.mission_state() or {}
        if not s: continue
        if not s["driving"]:
            last = None; last_hp = -1; continue
        if last and STAT["measuring"]:
            d = math.hypot(s["x"] - last[0], s["y"] - last[1])
            if d < 3.0: STAT["dist"] += d
        last = (s["x"], s["y"])
        hp, cf = ms.get("carhp", -1), ms.get("carfire", -1)
        if hp >= 0:
            if last_hp >= 0 and last_hp - hp >= 250 and cf <= 0 and STAT["measuring"]:
                near = [c for c in M.cars() if c["driver"] != "P" and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 2.4]
                kind = "car" if near else "wall"
                STAT["hits"].append(dict(kind=kind, x=round(s["x"], 1), y=round(s["y"], 1), hp=hp, loss=last_hp - hp, at=round(STAT["dist"], 1)))
                say(f"bench: {kind} hit {last_hp} -> {hp} at {s['x']:.1f},{s['y']:.1f} ({STAT['dist']:.0f} blocks)")
                if len(STAT["hits"]) <= 30: M.shot(f"hit{len(STAT['hits']):02d}_{kind}")
            if cf > 0 and not was_fire and STAT["measuring"]: STAT["fires"] += 1; say("bench: the car caught fire")
            was_fire = cf > 0
            last_hp = hp

def save():
    walls = sum(1 for h in STAT["hits"] if h["kind"] == "wall"); carh = len(STAT["hits"]) - walls
    per = 100.0 / max(STAT["dist"], 1.0)
    out = dict(driver=os.environ.get("DRIVER", "classic"), blocks=round(STAT["dist"], 1), wall_hits=walls, car_hits=carh,
               wall_hits_per_100=round(walls * per, 2), all_hits_per_100=round(len(STAT["hits"]) * per, 2), fires=STAT["fires"],
               cars_used=STAT["cars"], legs=STAT["legs"], hits=STAT["hits"])
    json.dump(out, open("/out/bench.json", "w"), indent=1)
    say("bench:", json.dumps({k: v for k, v in out.items() if k not in ("hits",)}))

D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
world = M.World("wil")
M.VIEW_HOOK[0] = set_view
M.arrows_baseline()
set_view("third")
threading.Thread(target=sampler, daemon=True).start()

def car():
    for _ in range(6):
        s = M.any_car2(world, budget=150)
        if s and s["driving"]:
            STAT["cars"] += 1; M.mark(f"in a car (model {s.get('cmodel')})"); return s
    return D.wait_state()

s = car()
M.mark("to the start"); s = M.drive3(world, *START, tol=2.5, budget=400)
for k, (tx, ty) in enumerate(ROUTE):
    STAT["measuring"] = True
    t0 = time.time(); d0 = STAT["dist"]; h0 = len(STAT["hits"])
    M.mark(f"leg {k + 1} to {tx},{ty}")
    tries = 0
    while tries < 5:
        tries += 1
        s = D.wait_state()
        if not (s and s["driving"]):
            STAT["measuring"] = False; s = car(); STAT["measuring"] = True
        s = M.drive3(world, tx, ty, tol=2.5, budget=500)
        if s and math.hypot(s["x"] - tx, s["y"] - ty) < 3.5: break
    STAT["legs"].append(dict(to=[tx, ty], blocks=round(STAT["dist"] - d0, 1), hits=len(STAT["hits"]) - h0,
                             secs=round((time.time() - t0) * D.SPEED, 1), reached=bool(s and math.hypot(s["x"] - tx, s["y"] - ty) < 3.5)))
    M.mark(f"leg {k + 1} done: {STAT['legs'][-1]}"); save()
STAT["measuring"] = False
M.shot("bench_end"); save()
