#!/usr/bin/env python3
"""District tours in the street-level views: shared helpers. A tour visits
landmarks on foot and by car, takes a labelled frame at each, logs every
developer warp (the scene key brings the nearest parked car to scene_xy with
the player at its door; the ini's scene_xy is re-read on every press, so the
script retargets it by editing the file in the prefix), and keeps a timeline
in /out/marks.txt. The warp happens behind a cut to the classic view, so the
clip shows the arrival on foot, not the teleport."""
import math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import qa_lib as Q

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
T0 = time.time()
WARPS = []

def mark(what):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {what}\n")
    say("MARK", what)

def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/t_{name}.png"])

def ms():
    return M.mission_state() or {}

def words(s):
    return (f"state={s['state']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} z={s['z']:.2f} "
            f"{'DRIVING' if s['driving'] else 'on foot'} view={Q.current_view()}")

def retarget(x, y, level=None):
    t = open(INI, encoding="latin-1").read()
    val = f"{x},{y}" + (f",{level}" if level is not None else "")
    t = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={val}", t)
    open(INI, "w", encoding="latin-1").write(t)

def devtools_lines():
    return [l for l in Q.log_text(60000).splitlines() if "devtools:" in l]

def ensure_on_foot():
    """the locator may hold a car (after a respawn the Return of leave_car can
    put him into a parked car): get out and confirm"""
    for _ in range(3):
        s = D.wait_state()
        if not s or not s["driving"]: return s
        tap("Return", 0.3); time.sleep(2.0)
    return D.wait_state()

def warp(x, y, level=None, why=""):
    """developer scene warp behind a classic-view cut; logged; the press is
    confirmed by the renderer's devtools line and retried"""
    s0 = ensure_on_foot()
    Q.set_view("classic", settle=1.0)
    retarget(x, y, level)
    s = s0
    for attempt in range(4):
        n0 = len(devtools_lines())
        tap("F10", 0.3); time.sleep(2.5)
        new = devtools_lines()[n0:]
        s = D.wait_state()
        if new and "ignored" not in new[-1]:
            break
        say(f"warp attempt {attempt + 1}: {new[-1].split('devtools:')[-1] if new else 'no devtools line (key not seen)'}")
        if new and "not located on foot" in new[-1]: s0 = ensure_on_foot()
        time.sleep(1.0)
    WARPS.append((time.time(), (s0["x"], s0["y"]), (x, y), (s["x"], s["y"]), why))
    mark(f"WARP from {s0['x']:.1f},{s0['y']:.1f} to {x},{y},{level} ({why}) -> at {s['x']:.1f},{s['y']:.1f} z={s['z']:.2f} state={s['state']}")
    return s

def view(target):
    Q.set_view(target, settle=1.5); mark(f"view {target}")

def look(key, secs, pause=0.8):
    hold(key, secs); time.sleep(pause)

def clear_of_cars(min_d=1.3):
    """on foot and within min_d of a car: step away from it, so a first-person
    eye is not inside a parked car's body (the scene warp parks the car at his
    door; after a respawn a stray Return can even put him in one)"""
    s = ensure_on_foot()
    for _ in range(3):
        if not s or s["driving"] or not s["car"] or s["cd"] >= min_d: return s
        dx, dy = s["x"] - s["cx"], s["y"] - s["cy"]
        n = math.hypot(dx, dy) or 1.0
        s = D.goto(s["x"] + dx / n * 1.6, s["y"] + dy / n * 1.6, tol=0.4, limit=6) or s
    return s

def look_around(name, secs=0.9):
    """a slow turn in place with frames at four headings; first person starts clear of any car"""
    if Q.current_view() == "first": clear_of_cars()
    shot(f"{name}_a")
    for i, k in enumerate(("Left", "Left", "Left")):
        look(k, secs); shot(f"{name}_{'bcd'[i]}")

def walk(world, x, y, budget=90, tol=0.6):
    s = M.walk_to(world, x, y, tol=tol, budget=budget)
    say(f"walk to {x},{y}: {words(s)}")
    return s

def get_in_scene_car(s_hint=None, attempts=3):
    """Return at the door the scene warp put him at; on failure step round the car"""
    for a in range(attempts):
        tap("Return", 0.3); time.sleep(2.5)
        s = D.wait_state()
        if s and s["driving"]:
            mark(f"in car model={s.get('cmodel', -1)}"); return s
        hold("Left", 0.4); hold("Up", 0.4); time.sleep(0.5)
    s = D.wait_state(); say("could not enter the scene car:", words(s)); return s

def drive(world, x, y, label, budget=150, fp_after=12.0):
    """chase view first, first person at the wheel after fp_after seconds, back to chase near the end"""
    t0 = time.time(); switched = [False]
    def vs(s):
        if not switched[0] and time.time() - t0 > fp_after:
            Q.set_view("first", settle=0.3); mark("first person at the wheel"); switched[0] = True
    view("third"); mark(f"drive to {label} {x},{y}")
    lives0 = ms().get("lives", 5)
    # the locator re-scans for a few frames after an entry (the game recycles
    # the ped): wait until it reports him driving before the controller starts
    for _ in range(8):
        s = D.wait_state()
        if s and s["driving"]: break
        time.sleep(0.5)
    s = M.drive_to(world, x, y, tol=2.5, budget=budget, view_switch=vs)
    m = ms()
    if m.get("lives", lives0) < lives0:
        mark(f"DIED during the drive to {label}; respawned at {s['x']:.1f},{s['y']:.1f}")
    say(f"drive to {label}: {words(s)}")
    return s

def leave_car():
    s = D.wait_state()
    if s and s["driving"]:
        s = M.leave_car()
    s = ensure_on_foot(); mark(f"out of the car at {s['x']:.1f},{s['y']:.1f}"); return s

def frame_times():
    return Q.frame_summaries()[-2:] if hasattr(Q, "frame_summaries") else []

def answer(world, phone, title):
    mark(f"to the phone at {phone['x']},{phone['y']} ({title})")
    ok, m = M.answer_phone(world, phone, budget=120)
    if not ok and m:
        # the warp can land him on the phone, so the brief is already up when
        # the baseline message is read: the mission's own text keys say so
        keys = set()
        for entry in world.db["missions"]:
            if entry.get("x") == phone["x"] and entry.get("y") == phone["y"]:
                for st in entry.get("plan", []):
                    for k in ("display_message", "display_brief", "display_brief_now"):
                        if k in st: keys.add(str(st[k]))
        if str(m.get("msg")) in keys: ok = True
    mark(f"phone {'answered' if ok else 'NOT answered'}: msg={m.get('msg') if m else '?'}")
    return ok, m

def finish(label):
    s = D.wait_state()
    mark(f"end {label}: {words(s)}")
    say("WARPS:", len(WARPS))
    for w in WARPS: say("  warp", w)
    say("done")
