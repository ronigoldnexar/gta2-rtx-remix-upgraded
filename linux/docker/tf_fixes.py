#!/usr/bin/env python3
"""TOUR-FIXES verification. SCENARIO=wil: the spawn pay phone in third and first
person, then the kerb railing (cutout alpha) in first person. SCENARIO=bil: the
scene-warp car at the spawn road entered, then the park fence in first person.
SCENARIO=ste: the western docks yard, container/crane counts from the log."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def retarget(x, y, z=None):
    t = open(INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={x},{y}" + (f",{z}" if z is not None else ""), t)
    open(INI, "w", encoding="latin-1").write(t)
def warp(x, y, z=None, settle=2.5):
    retarget(x, y, z); tap(os.environ.get("SCENE_KEY", "F10"), 0.3); time.sleep(settle)
    s = D.wait_state(); say(f"warp to {x},{y}: {Q.words(s)}"); return s
sc = os.environ.get("SCENARIO", "wil"); tag = "tf_" + sc
s = Q.start(tag)
if sc == "wil":
    # the tutorial phone at 158.5,138.5 beside the spawn
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_phone_third_a")
    hold("Left", 0.9); time.sleep(0.6); shot(f"{tag}_phone_third_b")
    hold("Left", 0.9); time.sleep(0.6); shot(f"{tag}_phone_third_c")
    Q.set_view("first"); time.sleep(1.0); shot(f"{tag}_phone_first_a")
    hold("Left", 1.2); time.sleep(0.6); shot(f"{tag}_phone_first_b")
    hold("Left", 1.2); time.sleep(0.6); shot(f"{tag}_phone_first_c")
    # onto the phone (eye push-out), then the kerb railing
    D.goto(158.5, 138.5, tol=0.25, limit=12); time.sleep(0.8); shot(f"{tag}_phone_first_on_it")
    hold("Left", 1.0); time.sleep(0.5); shot(f"{tag}_phone_first_on_it_b")
    Q.set_view("classic"); time.sleep(0.5)
    s = warp(159.5, 147.6, 2)
    Q.set_view("first"); time.sleep(1.0)
    for i in range(4):
        hold("Left", 0.55); time.sleep(0.6); shot(f"{tag}_railing_first_{i}")
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_railing_third")
elif sc == "bil4":
    import shutil
    def snap(): shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.partial.log")
    s = warp(44.5, 110.5, 2); shot(f"{tag}_scene")
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_third")
    got = None
    for attempt in range(3):
        tap("Return", 0.3); t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]: got = s; break
            time.sleep(0.4)
        say(f"Return {attempt}: {Q.words(s)} carmodel={s.get('cmodel')}")
        if got: break
    say("RESULT scene entry:", "DRIVING" if got else "not driving"); shot(f"{tag}_after")
    if got:
        hold("Up", 2.5); time.sleep(0.5); shot(f"{tag}_driving_third")
        Q.set_view("first"); time.sleep(0.8); shot(f"{tag}_driving_first")
        Q.leave_car(); time.sleep(1.0)
    snap()
    Q.set_view("classic"); s = warp(80.5, 20.5, 2)
    Q.set_view("third"); time.sleep(1.0)
    for i in range(4):
        hold("Left", 0.55); time.sleep(0.7); shot(f"{tag}_quay_third_{i}")
    snap()
elif sc == "bil2":
    import shutil
    def snap(): shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.partial.log")
    # F9: to the nearest parked car in place, no car moved
    tap("F9", 0.3); time.sleep(2.5); s = D.wait_state(); say("after F9:", Q.words(s), "carmodel", s.get("cmodel"))
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_f9_third")
    got = None
    for attempt in range(3):
        tap("Return", 0.3); t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]: got = s; break
            time.sleep(0.4)
        say(f"F9 Return {attempt}: {Q.words(s)} carmodel={s.get('cmodel')}")
        if got: break
    say("RESULT F9 entry:", "DRIVING" if got else "not driving"); shot(f"{tag}_f9_after")
    if got: Q.leave_car(); time.sleep(1.0)
    snap()
    # F10 at the spawn road, then step away and back before Return
    Q.set_view("classic"); s = warp(44.5, 110.5, 2); shot(f"{tag}_f10_scene")
    hold("Up", 1.5); time.sleep(0.5); hold("Down", 1.5); time.sleep(0.8)
    s = D.wait_state(); say("after stepping:", Q.words(s))
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_f10_third")
    got = None
    for attempt in range(3):
        tap("Return", 0.3); t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]: got = s; break
            time.sleep(0.4)
        say(f"F10 Return {attempt}: {Q.words(s)} carmodel={s.get('cmodel')}")
        if got: break
    say("RESULT F10 entry:", "DRIVING" if got else "not driving"); shot(f"{tag}_f10_after")
    snap()
elif sc == "bil":
    s = warp(44.5, 110.5, 2); shot(f"{tag}_car_scene")
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_car_third")
    got = None
    for attempt in range(3):
        tap("Return", 0.3); t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]: got = s; break
            time.sleep(0.4)
        say(f"Return {attempt}: {Q.words(s)} carmodel={s.get('cmodel')}")
        if got: break
    shot(f"{tag}_car_after_return")
    if got:
        hold("Up", 2.5); time.sleep(0.5); shot(f"{tag}_car_driving_third")
        Q.set_view("first"); time.sleep(0.8); shot(f"{tag}_car_driving_first")
        Q.leave_car(); time.sleep(1.0)
    say("RESULT car entry:", "DRIVING" if got else "not driving")
    Q.set_view("classic"); time.sleep(0.5)
    s = warp(138.5, 238.5, 3)
    Q.set_view("first"); time.sleep(1.0)
    for i in range(4):
        hold("Left", 0.55); time.sleep(0.6); shot(f"{tag}_fence_first_{i}")
    hold("Up", 1.5); time.sleep(0.6); shot(f"{tag}_fence_first_closer")
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_fence_third")
else:
    s = warp(25.5, 70.5, 2)
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_docks_third_a")
    D.goto(9.5, 72.5, tol=1.5, limit=70); time.sleep(0.8)
    for i in range(4):
        hold("Left", 0.55); time.sleep(0.7); shot(f"{tag}_quay_third_{i}")
    Q.set_view("first"); time.sleep(1.0)
    for i in range(3):
        hold("Left", 0.7); time.sleep(0.7); shot(f"{tag}_quay_first_{i}")
    Q.set_view("classic"); time.sleep(0.5)
    s = warp(80.5, 20.5, 2)   # Azeri-like promenade check is bil; here the north quay
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_north_third")
say("done")
