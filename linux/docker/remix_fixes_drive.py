#!/usr/bin/env python3
"""Driver's-seat check for the Remix hood cut and the object-model pointer guard:
the devtools scene key (F11) puts the player at a parked road car's door, Return
gets him in, then the three views at the wheel with screenshots. SKIP_START=1
when the key library already brought the game to the level (Remix runs)."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
say, tap, hold, shot = D.say, D.tap, D.hold, D.shot

def words(s): return f"state={s['state']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} {'DRIVING' if s['driving'] else 'on foot'}"
def watch(seconds, label):
    t0 = time.time(); last = ""
    while time.time() - t0 < seconds:
        s = D.wait_state(); w = words(s)
        if w != last: say(f"{label} +{time.time()-t0:4.1f}s {w}"); last = w
        if s["driving"]: return s
        time.sleep(0.4)
    return D.wait_state()
def cruise(seconds, name, turns=True):
    t0 = time.time(); n = 0
    while time.time() - t0 < seconds:
        hold("Up", 2.0); n += 1; shot(f"{name}_{n}")
        if turns: hold("Left" if n % 2 else "Right", 0.3)
    say(f"{name}:", words(D.wait_state()))

if os.environ.get("SKIP_START") != "1":
    D.start()
else:
    os.environ["DISPLAY"] = ":99"
s = D.wait_state(60)
if not s: sys.exit(1)
shot("00_level")
got = None
for attempt in range(1, 4):
    tap("F11", 0.3); time.sleep(1.5)
    s = D.wait_state(); say(f"after F11 ({attempt}): {words(s)} parked d={s['pd']:.2f}")
    tap("Return", 0.3); s = watch(8, f"Return {attempt}")
    if s["driving"]: got = s; break
if not got:
    for attempt in range(1, 3):
        tap("F9", 0.3); time.sleep(1.0); tap("Return", 0.3); s = watch(8, f"F9 Return {attempt}")
        if s["driving"]: got = s; break
say("RESULT:", "DRIVING" if got else "not driving")
if got:
    shot("10_classic_wheel")
    tap("v"); say("V: third person"); time.sleep(2.5); shot("12_third_wheel")
    cruise(10, "13_third")
    tap("v"); say("V: first person"); time.sleep(2.5); shot("14_first_wheel"); time.sleep(1.5); shot("14_first_wheel_b")
    cruise(24, "15_first")
    hold("Left", 1.2); time.sleep(0.5); shot("15_first_turned"); hold("Up", 2.0); shot("15_first_after_turn")
    tap("v"); say("V: classic"); time.sleep(1.5); shot("16_classic_again")
    tap("v"); say("V: third person"); time.sleep(2.0); shot("17_third_again")
    tap("Return"); time.sleep(2.0); shot("18_out")
    tap("v"); time.sleep(2.0); shot("19_first_out")
say("done")
