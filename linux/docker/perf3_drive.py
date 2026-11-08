#!/usr/bin/env python3
"""PERF-3: the PERF-2 chase-view drive (perf2_drive.py, same seeded route) with the cars'
wear and doors forced while it drives: every STEP_SECS (default 5) the next of a cycle of
[devtools] force_car_damage steps (the damage word: 4000/8000/16000/25000, then off) and force_car_door (right, shut,
left, shut) is written into the prefix's ini (re-read by the renderer once a second), so every
car in view needs a new dent step or door split at once. Marks in /out/marks.txt."""
import os, re, runpy, threading, time
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
STEP = float(os.environ.get("STEP_SECS", "5"))
# DAMAGE_STEPS: builds before PERF-3 read the damage as a byte (0..255; 96/160/224/255 gave
# their dent steps 2/3/4/4), so their runs pass DAMAGE_STEPS=96,160,224,255.
D1, D2, D3, D4 = (int(v) for v in os.environ.get("DAMAGE_STEPS", "4000,8000,16000,25000").split(","))
CYCLE = [("force_car_damage", D1), ("force_car_door", 1), ("force_car_damage", D2), ("force_car_door", 0),
         ("force_car_damage", D3), ("force_car_door", -1), ("force_car_damage", D4), ("force_car_door", 0),
         ("force_car_damage", -1)]

def setk(key, val):
    s = open(INI, encoding="latin-1").read()
    s = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", s) if f"{key}=" in s else s.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(INI, "w", encoding="latin-1").write(s)
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} FORCE {key}={val}\n")

def cycler():
    while True:   # from the start of the drive
        try:
            if "DRIVE start" in open("/out/marks.txt").read(): break
        except OSError: pass
        time.sleep(0.5)
    i = 0
    while True:
        time.sleep(STEP)
        try:
            if "DRIVE end" in open("/out/marks.txt").read(): setk("force_car_door", 0); setk("force_car_damage", -1); return
        except OSError: pass
        setk(*CYCLE[i % len(CYCLE)]); i += 1

threading.Thread(target=cycler, daemon=True).start()
runpy.run_path("/work/perf2_drive.py", run_name="__main__")
