#!/usr/bin/env python3
"""ACTIONS-3D-4 probe: the figure's feet and fists, Downtown. Every item films itself as a
15 fps burst (/out/b_<label>.mp4, x11grab while the keys are pressed), so the strips show
every other game frame. A34_ITEMS picks, in order (default "exit enter walk turn punch"):
  exit    at the wheel of a parked car (warp_key F9 to the nearest driver's door, Return), then
          out of it: third person, then in again and out in first person
  enter   on foot beside the car he just left: Return, the walk to the door, the reach, the climb
  walk    standing still, Up held 2.2 s (start: idle -> walk -> run), released (the stop settles)
  turn    standing still, Left held 1.4 s, Right 0.7 s (turning on the spot)
  moving  at the kerb, Return as a driven car passes: boarding a car on the move
  punch   the nearest pedestrian (mission_lib.peds(), else the crowd ahead): walk up, face him,
          the attack key held 2.5 s (repeated swings: the combo; his hit reaction), again
Run with GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_PED_FRAMES=1, GTA2DX9_LOG_FIGURES=1 and the INI_SED
setting scene_key=F10, warp_key=F9, nav_map=0 (tank controls: Left/Right turn on the spot)."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot
try:
    import mission_lib as M
except Exception:   # an older stage: no peds line
    M = None


def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
    say("MARK", w)


def burst(label, secs, fps=15):
    """film the screen for secs (wall) in the background; returns the process"""
    mark(f"burst {label} {secs}")
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                             "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])


def driving():
    s = D.wait_state(); return bool(s and s["driving"])


def into_car(tries=3):
    for attempt in range(tries):
        if driving(): return True
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3)
        t0 = time.time()
        while time.time() - t0 < 8:
            if driving(): return True
            time.sleep(0.4)
    return driving()


def exit_item():
    T.warp(164.5, 147.6, 2, why="street with parked cars")
    time.sleep(1.0)
    if not into_car():
        mark("no car"); return False
    for view in ("third", "first"):
        Q.set_view(view, settle=1.5)
        p = burst(f"exit_{view}", 4.0)
        time.sleep(0.6); tap("Return", 0.3)
        p.wait()
        s = D.wait_state(); mark(f"out ({view}): {Q.words(s)}")
        A.save_log()
        if view == "third":
            time.sleep(1.0)
            p = burst("enter_third", 6.0)
            time.sleep(0.5); tap("Return", 0.3)
            p.wait()
            mark(f"enter: {Q.words(D.wait_state())}")
            if not into_car(): mark("could not get back in"); return False
            time.sleep(1.0)
    Q.set_view("third", settle=1.0)
    return True


def enter_item():
    """from beside a car he has just left: a step away (Down), then Return"""
    if driving():
        tap("Return", 0.3); time.sleep(2.5)
    Q.set_view("third", settle=1.0)
    hold("Down", 0.35); time.sleep(1.0)
    p = burst("enter2_third", 6.0)
    time.sleep(0.5); tap("Return", 0.3)
    p.wait()
    mark(f"enter2: {Q.words(D.wait_state())}")
    if driving():
        tap("Return", 0.3); time.sleep(3.0)
    A.save_log()


def walk_item():
    s = T.warp(159.5, 139.5, 2, why="plaza")
    Q.set_view("third", settle=1.5)
    for k in range(2):
        p = burst(f"walk_{k}", 4.5)
        time.sleep(0.5); hold("Up", 2.2 if k == 0 else 0.6)
        p.wait()
        hold("Left", 0.5); time.sleep(0.8)
    A.save_log()


def turn_item():
    """turning on the spot, three times (the chase camera sometimes sits so close that his legs
    leave the frame; a few steps first let it settle behind at its walking distance), then in
    first person. A34_TURN_WARP=1 first goes to the open plaza."""
    if os.environ.get("A34_TURN_WARP") == "1":
        T.warp(159.5, 139.5, 2, why="open plaza for the turn")
    Q.set_view("third", settle=1.0)
    for k in range(3):
        hold("Up", 0.6); time.sleep(2.0)
        p = burst(f"turn_{k}" if k else "turn", 4.0)
        time.sleep(0.4); hold("Left", 1.4); time.sleep(0.5); hold("Right", 0.7)
        p.wait()
    Q.set_view("first", settle=1.0)
    p = burst("turn_first", 3.0)
    time.sleep(0.3); hold("Left", 1.2)
    p.wait()
    Q.set_view("third", settle=0.8)
    A.save_log()


def nearest_ped():
    if not M: return None
    s = D.wait_state()
    ps = [p for p in M.peds() if p["occ"] != 0 or True]
    ps = [p for p in ps if M.ped_alive(p) and p["car"] is None and abs(p["z"] - s["z"]) < 0.6 and
          math.hypot(p["x"] - s["x"], p["y"] - s["y"]) > 0.05]
    if not ps: return None
    return min(ps, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))


def punch_item():
    """walk up to the nearest pedestrian, the camera settled behind, then the attack key held
    while closing in on him (Up taps toward him as he staggers or runs)"""
    T.warp(float(os.environ.get("A34_PUNCH_X", "159.5")), float(os.environ.get("A34_PUNCH_Y", "139.5")), 2, why="plaza crowd")
    Q.set_view("third", settle=1.0)
    for k in range(int(os.environ.get("A34_PUNCHES", "3"))):
        p0 = nearest_ped()
        if p0:
            mark(f"target {p0['id']} at {p0['x']:.2f},{p0['y']:.2f} state {p0['state']}")
            D.goto(p0["x"], p0["y"], tol=0.4, limit=10)
            p1 = nearest_ped() or p0
            A.face(p1["x"], p1["y"], tries=4)
            time.sleep(0.8)
        p = burst(f"punch_{k}", 4.0)
        time.sleep(0.2)
        D.xdo("keydown", "Control_L"); t0 = time.time()
        while time.time() - t0 < 3.0:
            q = nearest_ped(); s = D.wait_state()
            if q and math.hypot(q["x"] - s["x"], q["y"] - s["y"]) > 0.4 and math.hypot(q["x"] - s["x"], q["y"] - s["y"]) < 2.0:
                a = D.angle_to(s, q["x"], q["y"])
                if abs(a) > 0.4:
                    hold("Left" if (a > 0) == (D.left_sign > 0) else "Right", min(abs(a) / D.rate, 0.2))
                hold("Up", 0.15)
            time.sleep(0.25)
        D.xdo("keyup", "Control_L")
        p.wait()
        mark(f"after punch {k}: {[ (q['id'], q['state'], q['sub'], q['hp']) for q in (M.peds() if M else [])][:6]}")
        A.save_log()


def moving_item():
    """board a car that is moving: at the kerb by the traffic, wait for a driven car passing
    within 1.8 blocks, press Return (the game runs him beside it and pulls him in), film it;
    out again and repeat, up to A34_MOVING tries (default 4) in A34_MOVING_SECS (150)"""
    if not M: mark("no cars line"); return
    T.warp(float(os.environ.get("A34_KERB_X", "164.5")), float(os.environ.get("A34_KERB_Y", "147.6")), 2, why="kerb by the traffic")
    Q.set_view("third", settle=1.0)
    t0 = time.time(); k = 0
    while time.time() - t0 < float(os.environ.get("A34_MOVING_SECS", "150")) and k < int(os.environ.get("A34_MOVING", "4")):
        s = D.wait_state()
        if s["driving"]:
            tap("Return", 0.3); time.sleep(2.5); continue
        cs = [c for c in M.cars() if c["driver"] not in ("-", "P") and abs(c["v"]) > 0.01 and abs(c["z"] - s["z"]) < 0.6]
        near = [c for c in cs if math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < float(os.environ.get("A34_NEAR", "2.2"))]
        if not near:
            time.sleep(0.1); continue
        c = min(near, key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
        mark(f"moving car m{c['model']} v={c['v']:.3f} at {c['x']:.2f},{c['y']:.2f}, player {s['x']:.2f},{s['y']:.2f}")
        p = burst(f"moving_{k}", 5.0)
        time.sleep(0.1); tap("Return", 0.3)
        p.wait()
        s2 = D.wait_state(); mark(f"moving {k}: {Q.words(s2)}")
        k += 1
        A.save_log()
        if s2["driving"]:
            tap("Return", 0.3); time.sleep(2.5)
        T.warp(float(os.environ.get("A34_KERB_X", "164.5")), float(os.environ.get("A34_KERB_Y", "147.6")), 2, why="kerb again")
        Q.set_view("third", settle=0.8)


def hitshow_item():
    """the hit reaction forced on the player's figure (GTA2DX9_FORCE_ACTION_FILE=a34_force.txt):
    hit_head three times, then the knock-down and up, from behind and the side"""
    f = "/tmp/wp/drive_c/Games/GTA2/a34_force.txt"
    T.warp(159.5, 139.5, 2, why="plaza for the showcase")
    Q.set_view("third", settle=1.0); hold("Up", 0.6); time.sleep(1.5)
    p = burst("hitshow", 5.0)
    for k in range(3):
        open(f, "w").write("-1\n"); time.sleep(0.55)
        open(f, "w").write("22\n"); time.sleep(0.9)
    p.wait()
    open(f, "w").write("-1\n"); time.sleep(0.6)
    A.side("hitshow_side_pre", "Left", 0.30)
    p = burst("hitshow_side", 3.0)
    for k in range(2):
        open(f, "w").write("22\n"); time.sleep(0.9); open(f, "w").write("-1\n"); time.sleep(0.5)
    p.wait()
    open(f, "w").write("-1\n")


ITEMS = {"exit": exit_item, "enter": enter_item, "walk": walk_item, "turn": turn_item, "punch": punch_item, "moving": moving_item, "hitshow": hitshow_item}
if __name__ == "__main__":
    Q.start("a34")
    for name in os.environ.get("A34_ITEMS", "exit enter walk turn punch").split():
        mark(f"item {name}")
        try:
            ITEMS[name]()
        except Exception as e:
            mark(f"item {name} failed: {e!r}")
        A.save_log()
    A.finish()
