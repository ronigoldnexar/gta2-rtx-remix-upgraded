#!/usr/bin/env python3
"""FIX-FIGURE-8 (pfeel32): first person in the start car (bil), a forced body roll/pitch ([devtools]
force_body_roll_deg / force_body_pitch_deg, live ini edit, CRLF kept) while stopped and while
rolling slowly; 30 fps bursts. FIG8_ROLLS="20,-20,0" roll degrees per step, FIG8_STEP secs."""
import os, re, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"

def setkey(k, v):
    t = open(INI, encoding="latin-1", newline="").read()
    if re.search(rf"(?m)^{k}=", t): t = re.sub(rf"(?m)^{k}=[^\r\n]*", f"{k}={v}", t)
    else: t = t.replace("[devtools]", f"[devtools]\r\n{k}={v}", 1)
    open(INI, "w", encoding="latin-1", newline="").write(t)
    mark(f"set {k}={v}")

ROLLS = [int(x) for x in os.environ.get("FIG8_ROLLS", "20,-20,0").split(",")]
PITCH = [int(x) for x in os.environ.get("FIG8_PITCHES", "0").split(",")]
STEP = float(os.environ.get("FIG8_STEP", "3"))
s = D.wait_state(); mark(f"start {s}")
ok = into_car(); mark(f"into_car {ok}")
time.sleep(1.5)
Q.set_view("first", settle=2.0)
p = burst("roll_still", len(ROLLS) * len(PITCH) * STEP + 2.0); time.sleep(0.5)
for pi in PITCH:
    setkey("force_body_pitch_deg", pi)
    for r in ROLLS:
        setkey("force_body_roll_deg", r); time.sleep(STEP)
p.wait()
setkey("force_body_roll_deg", 0); setkey("force_body_pitch_deg", 0)
p = burst("roll_drive", 9.0); time.sleep(0.3)
down("Up"); time.sleep(1.2); up("Up")
setkey("force_body_roll_deg", ROLLS[0]); time.sleep(2.5)
down("Left"); time.sleep(0.8); up("Left")
setkey("force_body_roll_deg", 0); time.sleep(2.0)
down("Down"); time.sleep(1.0); up("Down")
p.wait()
A.save_log()
A.finish()
