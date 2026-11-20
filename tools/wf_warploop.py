#!/usr/bin/env python3
"""WARP-CRASH repro: the 5090 soak's warp cycle (F10 scene key, F9 door warp, Return to board, hold Up, Return to
get out) over and over, counting deaths and faults. WF_MODE=board (soak cycle) | walk (F9 then walk on, no boarding).
Reads the log for 'FAULT:' and 'WASTED' and the pedtrace lines."""
import os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
from drive_lib import say, tap, hold

INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
LOG = D.LOG
PTS = ["164.5,149.5", "157.5,104.95", "124.5,126.95", "236.5,207.95", "120.5,151.95", "167.5,127.5", "92.5,125.5", "191.5,197.5"]
MODE = os.environ.get("WF_MODE", "board")
CYCLES = int(os.environ.get("WF_CYCLES", "400"))
HOLD_UP = float(os.environ.get("WF_UP", "1.5"))

def retarget(xy):
    t = open(INI, encoding="latin-1").read()
    t2 = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={xy}", t)
    if len(t2) > 10240:
        open(INI + ".wf", "w", encoding="latin-1").write(t2); os.replace(INI + ".wf", INI)

def count(pat):
    try: return len(re.findall(pat, open(LOG, encoding="latin-1").read()))
    except OSError: return 0

def lives():
    t = D.log_tail(0.0); m = None
    for m in re.finditer(r"view: mission .*? lives=(\d+)", t): pass
    return int(m.group(1)) if m else 5

def alive():
    return os.system("pgrep -f gta2.exe >/dev/null") == 0

s = D.wait_state(60)
say("start", s and (s["x"], s["y"], s["state"]))
for i in range(CYCLES):
    if not alive() or count(r"FAULT: unhandled"): say("GAME GONE after", i, "cycles"); break
    retarget(PTS[i % len(PTS)]); time.sleep(0.7)
    tap("F10", 0.3); time.sleep(1.5)
    if lives() > 1:
        tap("F9", 0.3); time.sleep(1.2)
        if MODE == "board":
            tap("Return", 0.3); time.sleep(2.5)
            hold("Up", HOLD_UP)
            s = D.state()
            if s and s["driving"]: tap("Return", 0.3)
            time.sleep(1.5)
        else:
            hold("Up", HOLD_UP + 1.5); time.sleep(1.0)
    else:
        time.sleep(3)
    if i % 10 == 0:
        say("cycle", i, "wasted", count(r"beat: WASTED start"), "faults", count(r"FAULT:"), "guard", count(r"guard: the respawn"), "kills", count(r"pedtrace: kill"), "frees", count(r"pedtrace: physics"))
say("done", "wasted", count(r"beat: WASTED start"), "faults", count(r"FAULT:"), "guard", count(r"guard: the respawn"))
