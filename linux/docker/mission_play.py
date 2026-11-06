#!/usr/bin/env python3
"""Plays GTA2 missions by their decompiled plans. Usage (inside the game
container, after run_game*.sh started the game):

    python3 /work/mission_play.py wil wil_tra wil_ye1

Each mission: walk to its phone, answer it, then follow the plan's waits:
get into the mission car, drive/walk to each arrow target, sound the horn,
and read the outcome off the game's own state (JOB COMPLETE! / JOB FAILED! /
money). Third person throughout, first person for a stretch of every drive."""
import math, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say = D.say
district = sys.argv[1] if len(sys.argv) > 1 else "wil"
wanted = sys.argv[2:] or ["wil_tra", "wil_ye1"]

D.start()                       # window, intro, menu, level
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
world = M.World(district)
M.mark("level")
D.tap("v"); time.sleep(2.0); M.mark("third person")   # classic -> third person for the whole play

fp_until = [0.0]
def view_switch(s):
    """first person for ~15 s at the start of every drive, then back to third"""
    now = time.time()
    if fp_until[0] == 0.0:
        D.tap("v"); fp_until[0] = now + 15; M.mark("first person at the wheel")
    elif fp_until[0] > 0 and now > fp_until[0]:
        D.tap("v"); D.tap("v"); fp_until[0] = -1; M.mark("back to third person")

def run_plan(entry):
    plan = entry["plan"]
    car_at = None
    last_car_step = None
    money0 = (M.mission_state() or {}).get("money", 0)
    for step in plan:
        if "car" in step:
            car_at = step["at"]; last_car_step = step; say("plan: mission car", step["car"], "at", car_at); continue
        if "wait" not in step: continue
        cond, nums = step["wait"], step["numbers"]
        s = D.wait_state()
        o, ms = M.outcome(money0)
        if o in ("complete", "failed", "dead"): return o
        if "IS_CHARACTER_IN_CAR" in cond or "IS_CHARACTER_IN_ANY_CAR" in cond:
            if car_at:
                M.mark(f"to the car at {car_at[0]},{car_at[1]}")
                s = M.enter_car_at(world, car_at[0], car_at[1], budget=150)
                say("in car:", bool(s and s["driving"]))
                if not (s and s["driving"]): return "stuck: could not enter the car"
                fp_until[0] = 0.0
        elif "LOCATE_CHARACTER_ON_FOOT" in cond:
            x, y = nums[1], nums[2]
            M.mark(f"on foot to {x},{y}")
            if s["driving"]:
                # the game wants him on foot there: leave the car and walk (the
                # walker is the reliable navigator; a drive is used where the
                # script demands the car)
                s = M.leave_car(); M.mark("out of the car, walking")
            s = M.walk_to(world, x, y, tol=0.45, budget=360)
            D.goto(x, y, tol=0.3, limit=6); time.sleep(1.5)
        elif "LOCATE_CHARACTER_BY_CAR" in cond or "IS_CAR_IN_BLOCK" in cond:
            x, y = (nums[1], nums[2]) if "LOCATE" in cond else (nums[2], nums[3])
            M.mark(f"by car to {x},{y}")
            if not s["driving"] and car_at:
                s = M.enter_car_at(world, car_at[0], car_at[1], budget=120)
            s = M.drive_to(world, x, y, tol=1.8, budget=300, view_switch=view_switch)
            time.sleep(1.5)
        elif "LOCATE_CHARACTER_ANY_MEANS" in cond:
            x, y = nums[1], nums[2]
            M.mark(f"any means to {x},{y}")
            if s["driving"]:
                s = M.drive_to(world, x, y, tol=2.5, budget=240, view_switch=view_switch)
                if math.hypot(x - s["x"], y - s["y"]) > 1.0:
                    s = M.leave_car(); s = M.walk_to(world, x, y, tol=0.45, budget=200)
            else:
                s = M.walk_to(world, x, y, tol=0.45, budget=300)
        elif "IS_CHAR_PRESSING_HORN" in cond:
            M.mark("horn"); M.horn(3); time.sleep(2.0)
        elif "IS_CHAR_OBJECTIVE_PASSED" in cond:
            say("plan: waiting for the character"); time.sleep(18)
        elif "HAS_PARK_FINISHED" in cond:
            say("plan: parking"); time.sleep(10)
        elif "IS_CAR_CRUSHED" in cond:
            say("plan: waiting for the crusher"); time.sleep(20)
        elif "count" in cond:
            say("plan: briefs on screen, waiting"); time.sleep(45)
        else:
            say("plan: unhandled wait", cond); time.sleep(5)
        o, ms = M.outcome(money0)
        say("state:", o, ms)
        if o in ("complete", "failed", "dead"): return o
    o, ms = M.wait_outcome(money0, 40)
    return o

results = {}
for name in wanted:
    entry = next((m for m in world.db["missions"] if m.get("mission") == name), None)
    if not entry: say("no such mission", name); continue
    M.mark(f"mission {name}: {entry.get('title','')}")
    ok, ms = M.answer_phone(world, entry, budget=400)
    say("answered:", ok, ms)
    M.shot(f"{name}_phone")
    if not ok:
        results[name] = "phone not answered"; continue
    results[name] = run_plan(entry)
    M.mark(f"mission {name}: {results[name]}")
    M.shot(f"{name}_end")
    time.sleep(3)
say("RESULTS", results)
M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
