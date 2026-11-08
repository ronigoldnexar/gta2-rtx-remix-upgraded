#!/usr/bin/env python3
"""PERF-4: the PERF-3 drive (perf3_drive.py: the PERF-2 chase-view drive through Downtown with the
cars' dents and doors forced every STEP_SECS) with forced model changes on top: every MODEL_SECS
(default 7) [devtools] force_car_model moves to the next of a list of car models, so every car in
view is redrawn as another model. The cars' sprite artwork (the subject of PERF-4) comes from the
traffic itself: each car model and paint that comes into view, and the game's door and damage
patches. One writer thread for both cycles (the ini is read-modify-written). Marks in /out/marks.txt."""
import os, re, runpy, threading, time
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
STEP = float(os.environ.get("STEP_SECS", "5"))
MSTEP = float(os.environ.get("MODEL_SECS", "7"))
D1, D2, D3, D4 = (int(v) for v in os.environ.get("DAMAGE_STEPS", "4000,8000,16000,25000").split(","))
CYCLE = [("force_car_damage", D1), ("force_car_door", 1), ("force_car_damage", D2), ("force_car_door", 0),
         ("force_car_damage", D3), ("force_car_door", -1), ("force_car_damage", D4), ("force_car_door", 0),
         ("force_car_damage", -1)]
MODELS = [int(v) for v in os.environ.get("MODELS", "0,13,29,38,50,63,8,19,36,57,1,44,70,4").split(",")]

def setk(key, val):
    s = open(INI, encoding="latin-1").read()
    s = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", s) if f"{key}=" in s else s.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(INI, "w", encoding="latin-1").write(s)
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} FORCE {key}={val}\n")

def marks():
    try: return open("/out/marks.txt").read()
    except OSError: return ""

def cycler():
    while "DRIVE start" not in marks(): time.sleep(0.5)
    t0 = time.time(); nd = t0 + STEP; nm = t0 + MSTEP; i = j = 0
    while True:
        time.sleep(0.2)
        if "DRIVE end" in marks():
            for k, v in (("force_car_door", 0), ("force_car_damage", -1), ("force_car_model", -1)): setk(k, v)
            return
        now = time.time()
        if now >= nd: setk(*CYCLE[i % len(CYCLE)]); i += 1; nd += STEP
        if now >= nm: setk("force_car_model", MODELS[j % len(MODELS)]); j += 1; nm += MSTEP

threading.Thread(target=cycler, daemon=True).start()
runpy.run_path("/work/perf2_drive.py", run_name="__main__")
