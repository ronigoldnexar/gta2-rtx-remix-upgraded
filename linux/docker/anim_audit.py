#!/usr/bin/env python3
"""ANIM-BLEND-AUDIT scenario: walks the player's figure through every animation transition the
street views draw, in third person on the open Downtown plaza, and films each step as a 30 fps
burst (/out/b_<step>.mp4). /out/marks.txt gets "<epoch> <HH:MM:SS.mmm> step <name> begin|end" and
"burst <name> <epoch>" lines, which tools/anim_audit.py uses to cut the GTA2DX9_LOG_JOINTS trace
(figj: lines) into steps and to pull the worst frame of each defect out of the bursts.

AUDIT_X/AUDIT_Y: the spot (default the Downtown plaza 159.5,139.5); AUDIT_WARP_EACH=1 warps back
to it before every step but the two that need the car (each step then starts on open ground with
the camera behind him). Steps (AUDIT_STEPS picks a subset, in this order by default):
  idle        standing 2.5 s (idle loop, a fidget may start)
  start_stop  Up 1.6 s, released (idle -> start -> run -> stop -> idle)
  tap         Up 0.3 s twice (a start cut short by a stop)
  turn90      on the spot, a quarter turn left, then right
  turn180     on the spot, a half turn
  backstep    Down 1.0 s (walking backwards), released
  run_reverse Up 1.2 s straight into Down 0.8 s (run -> backwards)
  run_180     running, a half turn held in the middle of the run
  curve       Up 3 s with Left over the middle second (lean into a turn)
  jump        Space standing, then Up + Space running
  punch       Ctrl standing 1.0 s, then Ctrl while running
  hit         forced hit reaction (action 22) twice over the idle, once over the run
  knockdown   forced fall (action 4) held 1.5 s, then released (the get-up)
  car_in_out  F9 to a parked car's door, Return (get in), 2 s, Return (get out, parked)
  car_moving  in again, Up 2 s, Return while moving (exit from a moving car)
  bump_car    walk into the car's flank for 1.5 s (clipping into a body)
Run with GTA2_DIRECT_KEYS=1 (nav_map=0: Left/Right turn on the spot), INI_SED scene_key=F10 and
warp_key=F9, GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_JOINTS=1, GTA2DX9_LOG_FIGURES=1,
GTA2DX9_FORCE_ACTION_FILE=audit_force.txt. See docs/anim-audit.md."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

FORCE = "/tmp/wp/drive_c/Games/GTA2/audit_force.txt"
PLAZA = (float(os.environ.get("AUDIT_X", "159.5")), float(os.environ.get("AUDIT_Y", "139.5")))
FPS = int(os.environ.get("AUDIT_FPS", "30"))


def stamp():
    t = time.time()
    return f"{t:.3f} {time.strftime('%H:%M:%S', time.localtime(t))}.{int((t % 1) * 1000):03d}"


def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{stamp()} {w}\n")
    say("MARK", w)


def burst(label, secs):
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(FPS),
                          "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])
    mark(f"burst {label} {secs}")
    return p


def force(action):
    with open(FORCE, "w") as f: f.write(f"{action}\n")


def keydown(k): D.xdo("keydown", k)
def keyup(k): D.xdo("keyup", k)


def driving():
    s = D.wait_state(); return bool(s and s["driving"])


def to_plaza(force=False):
    s = D.wait_state()
    if s and s["driving"]:
        tap("Return", 0.3); time.sleep(2.5)
    if force or not s or math.hypot(s["x"] - PLAZA[0], s["y"] - PLAZA[1]) > 3.0:
        T.warp(PLAZA[0], PLAZA[1], 2, why="audit plaza")
    Q.set_view("third", settle=1.0)
    hold("Up", 0.4); time.sleep(1.5)        # the chase camera settles behind at walking distance


def turn_secs(rad):
    return min(2.0, abs(rad) / max(D.rate, 0.5))


def step_idle():
    time.sleep(2.5)

def step_start_stop():
    hold("Up", 1.6); time.sleep(1.6)

def step_tap():
    hold("Up", 0.3); time.sleep(1.0); hold("Up", 0.3); time.sleep(1.2)

def step_turn90():
    hold("Left", turn_secs(math.pi / 2)); time.sleep(1.0); hold("Right", turn_secs(math.pi / 2)); time.sleep(1.0)

def step_turn180():
    hold("Left", turn_secs(math.pi)); time.sleep(1.4)

def step_backstep():
    hold("Down", 1.0); time.sleep(1.2)

def step_run_reverse():
    keydown("Up"); time.sleep(1.2); keyup("Up"); hold("Down", 0.8); time.sleep(1.2)

def step_run_180():
    keydown("Up"); time.sleep(0.9); hold("Left", turn_secs(math.pi)); time.sleep(0.7); keyup("Up"); time.sleep(1.2)

def step_curve():
    keydown("Up"); time.sleep(1.0); hold("Left", 1.0); time.sleep(1.0); keyup("Up"); time.sleep(1.2)

def step_jump():
    hold("space", 0.2); time.sleep(1.5)
    keydown("Up"); time.sleep(0.8); hold("space", 0.2); time.sleep(0.8); keyup("Up"); time.sleep(1.2)

def step_punch():
    hold("Control_L", 1.0); time.sleep(1.0)
    keydown("Up"); time.sleep(0.6); hold("Control_L", 0.6); time.sleep(0.3); keyup("Up"); time.sleep(1.2)

def step_hit():
    for _ in range(2):
        force(22); time.sleep(0.9); force(-1); time.sleep(0.8)
    keydown("Up"); time.sleep(0.6); force(22); time.sleep(0.8); force(-1); keyup("Up"); time.sleep(1.2)

def step_knockdown():
    force("4 0"); time.sleep(2.0); force(-1); time.sleep(2.5)

def into_car(tries=3):
    for _ in range(tries):
        if driving(): return True
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3)
        t0 = time.time()
        while time.time() - t0 < 6:
            if driving(): return True
            time.sleep(0.3)
    return driving()

def step_car_in_out():
    tap("F9", 0.3); time.sleep(1.5)
    tap("Return", 0.3); time.sleep(3.0)
    if not driving(): mark("car_in_out: not in a car after Return")
    tap("Return", 0.3); time.sleep(2.5)

def step_car_moving():
    if not into_car(): mark("car_moving: no car"); return
    time.sleep(0.8)
    keydown("Up"); time.sleep(2.0); tap("Return", 0.3); keyup("Up"); time.sleep(3.0)

def step_bump_car():
    s = D.wait_state(5)
    if not s or not s.get("car"): mark("bump_car: no car near"); return
    a = D.angle_to(s, s["cx"], s["cy"])
    if abs(a) > 0.2: hold("Left" if (a > 0) == (D.left_sign > 0) else "Right", turn_secs(a))
    time.sleep(0.4); hold("Up", 1.5); time.sleep(1.0)


STEPS = [("idle", step_idle, 4), ("start_stop", step_start_stop, 5), ("tap", step_tap, 4),
         ("turn90", step_turn90, 5), ("turn180", step_turn180, 4), ("backstep", step_backstep, 4),
         ("run_reverse", step_run_reverse, 5), ("run_180", step_run_180, 5), ("curve", step_curve, 6),
         ("jump", step_jump, 6), ("punch", step_punch, 5), ("hit", step_hit, 6), ("knockdown", step_knockdown, 6),
         ("car_in_out", step_car_in_out, 9), ("car_moving", step_car_moving, 9), ("bump_car", step_bump_car, 4)]


if __name__ == "__main__":
    Q.start("anim_audit")
    force(-1)
    to_plaza()
    want = os.environ.get("AUDIT_STEPS", "").split()
    for name, fn, secs in STEPS:
        if want and name not in want: continue
        if os.environ.get("AUDIT_WARP_EACH") == "1" and name not in ("car_moving", "bump_car"):
            to_plaza(force=True)
        elif name in ("idle", "hit", "knockdown"):
            to_plaza()
        p = burst(name, secs + 0.5)
        time.sleep(0.4)
        mark(f"step {name} begin")
        try:
            fn()
        except Exception as e:
            mark(f"step {name} failed: {e!r}")
        mark(f"step {name} end")
        force(-1)
        for k in ("Up", "Down", "Left", "Right", "Control_L"): keyup(k)
        p.wait()
        A.save_log()
    mark("done")
    A.finish()
