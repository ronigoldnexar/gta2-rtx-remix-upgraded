#!/usr/bin/env python3
"""CAMERA-PROPS probe (QA3 findings 2-4 and the mouse with the soft follow).
Items (CPR_ITEMS, default "booth shop lamp mouse"); frames /out/cpr_<item>_<tag>.png; every
phase is marked in /out/marks.txt with the container clock (the renderer log's clock):
  booth  the Downtown tutorial phone box (map 158.5,138.5): standing 0.8 and 1.4 blocks south
         of it facing south, and 0.9 east/west of it facing away, so the chase camera behind
         him would stand in the box; third person after a classic->third switch (the camera
         starts behind his heading), frames at 0.3 and 2.0 s
  shop   the QA3 shop front (map 118.24,156.84, the qa_q3_crash exit spot): third person facing
         away from the wall, along it both ways and into it
  lamp   first person at the same spot and walking east along the pavement past the posts,
         frames every 0.3 s
  mouse  third person walking (Up held, tank controls) while the mouse moves: right for 1.5 s,
         still 4 s (the follow waits 1.5 s, then swings back behind him), left for 1.5 s, still
         4 s; then standing, right 1.5 s and still 3 s (standing: it holds)
Run with GTA2_DIRECT_KEYS=1, GTA2DX9_LOG_CAMERA=1, GTA2DX9_SCENE_NO_CAR=1 and
INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/'."""
import datetime, os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
import tour_lib as T
from tour_lib import D, Q, say, tap, hold

MARKS = open("/out/marks.txt", "a")


def mark(what):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    MARKS.write(f"{ts} {what}\n"); MARKS.flush()
    say("MARK", what)


def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/cpr_{name}.png"])
    mark(f"shot {name}")


def third_from_heading(settle=0.3):
    """classic, then third: the chase camera starts behind his heading"""
    Q.set_view("classic", settle=0.5)
    Q.set_view("third", settle=settle)


def stand(x, y, tx, ty, tag):
    s = T.warp(x, y, 2, why=tag)
    time.sleep(1.0)
    s = A.face(tx, ty)
    mark(f"{tag} at {s['x']:.2f},{s['y']:.2f} face {s['fx']:.2f},{s['fy']:.2f}")
    return s


def booth():
    bx, by = 158.5, 138.5
    for tag, (x, y, tx, ty) in {"s08": (bx, by + 0.8, bx, by + 8), "s14": (bx, by + 1.4, bx, by + 8),
                                "e09": (bx + 0.9, by, bx + 8, by), "w09": (bx - 0.9, by, bx - 8, by)}.items():
        stand(x, y, tx, ty, f"booth {tag}")
        third_from_heading(3.5); shot(f"booth_{tag}_b")


def shop():
    x, y = 118.24, 156.84
    for tag, (tx, ty) in {"away": (x, y - 8), "east": (x + 8, y), "west": (x - 8, y), "wall": (x, y + 8)}.items():
        stand(x, y, tx, ty, f"shop {tag}")
        third_from_heading(3.5); shot(f"shop_{tag}_b")


def lamp():
    x, y = 118.24, 156.84
    for tag, (tx, ty) in {"east": (x + 8, y), "west": (x - 8, y), "road": (x, y - 8)}.items():
        stand(x, y, tx, ty, f"lamp {tag}")
        Q.set_view("first", settle=1.2); shot(f"lamp_{tag}")
    # along the pavement eastward past whatever stands on it
    stand(x - 3.0, y, x + 20, y, "lamp walk")
    Q.set_view("first", settle=1.0)
    D.xdo("keydown", "Up")
    t0 = time.time(); k = 0
    while time.time() - t0 < 6.0:
        shot(f"lamp_walk_{k:02d}"); k += 1
        time.sleep(0.15)
    D.xdo("keyup", "Up")


def mouse_move(dx, secs, tag):
    mark(f"mouse {tag} start dx={dx}")
    t0 = time.time()
    while time.time() - t0 < secs:
        D.xdo("mousemove_relative", "--", str(dx), "0")
        time.sleep(0.03)
    mark(f"mouse {tag} stop")


def mouse():
    stand(150.5, 149.6, 170, 149.6, "mouse street")
    third_from_heading(2.0)
    mark("walk start")
    D.xdo("keydown", "Up")
    time.sleep(2.0)
    mouse_move(12, 3.0, "walkR")
    time.sleep(4.0)
    mouse_move(-12, 3.0, "walkL")
    time.sleep(4.0)
    D.xdo("keyup", "Up")
    mark("walk stop")
    time.sleep(2.0)
    mouse_move(12, 1.5, "standR")
    time.sleep(3.0)
    mark("mouse end")


def car():
    """F9 to the nearest parked car's door in third person; Return; frames every 0.15 s through
    the entry (QUALITY-BAR row 7); Return out; frames; first person, turn toward the car (QA3 3)"""
    stand(164.5, 149.5, 170, 149.5, "car street")
    tap("F9", 0.3); time.sleep(2.0)
    third_from_heading(2.5)
    shot("car_door")
    mark("enter press")
    tap("Return", 0.3)
    t0 = time.time(); k = 0
    while time.time() - t0 < 3.5:
        shot(f"car_in_{k:02d}"); k += 1
        time.sleep(0.05)
    s = D.wait_state(); mark(f"car entered driving={s['driving']}")
    tap("Return", 0.3); mark("exit press")
    t0 = time.time(); k = 0
    while time.time() - t0 < 3.0:
        shot(f"car_out_{k:02d}"); k += 1
        time.sleep(0.1)
    Q.set_view("first", settle=1.0); shot("car_fp_0")
    for k in range(1, 6):
        hold("Left", 0.35); time.sleep(0.5); shot(f"car_fp_{k}")


ITEMS = {"car": car, "booth": booth, "shop": shop, "lamp": lamp, "mouse": mouse}
Q.start("camprops")
for item in os.environ.get("CPR_ITEMS", "car booth shop lamp mouse").split():
    mark(f"item {item}")
    try:
        ITEMS[item]()
    except Exception as e:
        mark(f"item {item} failed: {e!r}")
    A.save_log()
A.finish()
