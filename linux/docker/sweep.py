#!/usr/bin/env python3
"""The city sweep: visits every point of a district's plan
(sweep_plan_<district>.json, from tools/sweep_plan.py) by developer warp and
takes labelled frames at four headings in third person and in first person,
so a detector (tools/sweep_detect.py) can look for holes, black frames, flat
untextured faces and camera clipping everywhere in the city. Run with the
magenta clear (GTA2DX9_CLEAR_MAGENTA=1) and the sky off, so whatever is not
drawn shows as magenta.

Env: SWEEP_DISTRICT (wil|bil|ste), SWEEP_CHUNK (i/n: this run's share of
the plan), SWEEP_TURN (seconds per quarter turn, default 0.8).
Per point: /out/sw_<name>_<view><a-d>.png and a line in /out/sweep.jsonl
with the point, the player's reported position, lives, the log line count
before and after, so the detector can slice the renderer log per point.
"""
import json, os, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, hold, mark

district = os.environ.get("SWEEP_DISTRICT", "wil")
chunk = os.environ.get("SWEEP_CHUNK", "0/1")
turn = float(os.environ.get("SWEEP_TURN", "0.8"))
ci, cn = [int(v) for v in chunk.split("/")]
plan = json.load(open(os.environ.get("SWEEP_PLAN", f"/work/sweep_plan_{district}.json")))["points"]
mine = [p for i, p in enumerate(plan) if i % cn == ci]
say(f"sweep {district} chunk {chunk}: {len(mine)} of {len(plan)} points")

T.Q.start(f"sweep_{district}_{ci}")
mark("level")
s = D.wait_state(); say("start:", T.words(s))


def log_lines():
    return Q.log_text().count("\n")


def shots(name, view):
    """four headings, a frame each; first person steps clear of cars first"""
    Q.set_view(view, settle=1.2)
    if view == "first": T.clear_of_cars()
    tag = "t" if view == "third" else "f"
    T.shot(f"{name}_{tag}a")
    # third person: four headings; first person: two (the eye sees further)
    for suffix in ("bcd" if view == "third" else "c"):
        hold("Left", turn if view == "third" else 2 * turn); time.sleep(0.35)
        T.shot(f"{name}_{tag}{suffix}")


out = open("/out/sweep.jsonl", "a")
lives = T.ms().get("lives", -1)
for n, p in enumerate(mine):
    name = f"{p['kind']}_{int(p['x'])}_{int(p['y'])}"
    l0 = log_lines(); t0 = time.time()
    try:
        s = T.warp(p["x"], p["y"], p["z"], why=f"sweep {name}")
    except Exception as e:          # the game died (a crash after a warp): record and stop
        say(f"point {name}: warp failed ({e}); game state lost"); s = None
        out.write(json.dumps(dict(n=n, name=name, point=p, landed=False, at=None, state=None, t=round(t0, 3),
                                  log_lines=[l0, log_lines()], seconds=round(time.time() - t0, 1), error=str(e))) + "\n"); out.flush()
        if not D.wait_state(5): break
        continue
    landed = s and abs(s["x"] - p["x"]) + abs(s["y"] - p["y"]) < 8
    rec = dict(n=n, name=name, point=p, landed=bool(landed),
               at=[round(s["x"], 2), round(s["y"], 2), round(s["z"], 2)] if s else None,
               state=s["state"] if s else None, t=round(t0, 3))
    if landed:
        shots(name, "third")
        shots(name, "first")
    else:
        T.shot(f"{name}_miss")
    m = T.ms()
    if m.get("lives", lives) < lives:
        mark(f"DIED at point {name}; lives {lives} -> {m.get('lives')}")
        rec["died"] = True
        lives = m.get("lives", lives)
        T.ensure_on_foot()
    rec["log_lines"] = [l0, log_lines()]
    rec["seconds"] = round(time.time() - t0, 1)
    out.write(json.dumps(rec) + "\n"); out.flush()
    say(f"point {n + 1}/{len(mine)} {name}: landed={landed} in {rec['seconds']} s")
Q.set_view("classic", settle=1.0)
T.shot("end_classic")
T.finish(f"sweep_{district}_{ci}")
