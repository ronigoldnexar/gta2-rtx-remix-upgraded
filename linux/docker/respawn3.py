#!/usr/bin/env python3
"""RESPAWN v3: arm the player at the pistol pickup east of the spawn (scene warp
to 166.5,139.5 resolves to the road cell beside it, then walk onto it), shoot
people on the plaza: the police come. Death on foot in third person (keep
shooting until they shoot him dead), then after the respawn an arrest in first
person (shoot until wanted 1, holster by standing still, let them reach him)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import mission_lib as M

PICKUP = (166.5, 139.5)
def ms(): return M.mission_state() or {}
def synth():
    t = Q.log_text(300000); m = None
    for m in re.finditer(r"synthetic: totals since start \| muzzle (\d+) bullet (\d+) .*? fire (\d+)", t): pass
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
def status(tag):
    s = D.wait_state(); m = ms()
    say(tag, f"{Q.words(s)} lives={m.get('lives')} wanted={m.get('wanted')} health={m.get('health')}")
    return s, m
def burst(label, seconds, every=0.5):
    t0 = time.time(); i = 0
    while time.time() - t0 < seconds:
        shot(f"{label}_{i:02d}_{Q.current_view()}"); i += 1; time.sleep(every)
def views_after(label):
    for view in ("third", "first", "classic"):
        Q.set_view(view, settle=1.5); hold("Up", 0.8); time.sleep(0.5)
        shot(f"{label}_{view}"); status(f"{label} {view}:")

def arm():
    tap("F10", 0.3); time.sleep(2.0)
    s, m = status("after F10:")
    for _ in range(3):
        s = D.goto(PICKUP[0], PICKUP[1], tol=0.3, limit=12) or D.wait_state()
        say(f"at {s['x']:.2f},{s['y']:.2f} (pickup at {PICKUP})")
        hold("Up", 0.3); hold("Down", 0.3)
    before = synth()
    for i in range(3):
        hold("Control_L", 0.5); time.sleep(0.4)
    time.sleep(9)
    after = synth()
    say("shots check: muzzle/bullet/fire before", before, "after", after)
    return after[0] > before[0] or after[1] > before[1]

s = Q.start("respawn3")
c0 = Q.counts()
died = arrested = False; wanted = 0

# ---- A: death on foot, chase view
Q.set_view("third")
armed = arm()
say("armed:", armed)
lives0 = ms().get("lives", 5)
t0 = time.time(); last = ""; n = 0
while time.time() - t0 < 240:
    s, m = D.wait_state(), ms()
    w = f"health={m.get('health')} lives={m.get('lives')} wanted={m.get('wanted')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
    if w != last: say(f"fight +{time.time()-t0:5.1f}s {w}"); last = w
    if m.get("lives", lives0) < lives0:
        died = True; say("DEATH:", w); break
    hold("Control_L", 0.9); hold("Left" if n % 2 else "Right", 0.3); n += 1
    if n % 3 == 0 and m.get("wanted", 0) == 0: hold("Up", 0.5)
    if n % 10 == 0: shot(f"d_05_fight{n:03d}_{Q.current_view()}")
if died:
    burst("d_10_wasted", 12, 0.5); status("after respawn:"); views_after("d_20_respawn")
Q.report("death", died=died, armed=armed)

# ---- B: arrest in first person
Q.set_view("third")
armed2 = arm(); say("armed again:", armed2)
Q.set_view("first")
lives0 = ms().get("lives", 5); t0 = time.time(); n = 0; last = ""
while time.time() - t0 < 120 and wanted < 1:
    s, m = D.wait_state(), ms(); wanted = m.get("wanted", 0)
    if m.get("lives", lives0) < lives0: say("died while provoking"); break
    hold("Control_L", 0.9); hold("Left" if n % 2 else "Right", 0.4); n += 1
    w = f"wanted={wanted} health={m.get('health')}"
    if w != last: say(f"provoke +{time.time()-t0:4.0f}s {w}"); last = w
say("wanted level:", wanted); shot("a_01_wanted_first")
s, m = status("standing for the police:"); x0, y0 = s["x"], s["y"]
t0 = time.time(); last = ""
while time.time() - t0 < 150:
    s, m = D.wait_state(), ms()
    w = f"wanted={m.get('wanted')} health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
    if w != last: say(f"police +{time.time()-t0:5.1f}s {w}"); last = w
    jumped = abs(s["x"] - x0) + abs(s["y"] - y0) > 12
    if wanted >= 1 and m.get("wanted", 0) == 0 and jumped and m.get("lives", lives0) == lives0:
        arrested = True; say("ARREST:", w); break
    if m.get("lives", lives0) < lives0: say("died instead:", w); died2 = True; break
    if int(time.time() - t0) % 6 == 0: shot(f"a_02_wait{int(time.time()-t0):03d}_{Q.current_view()}")
    time.sleep(0.25)
burst("a_10_busted", 10, 0.5); status("after:"); views_after("a_20_respawn")
Q.report("arrest", arrested=arrested, wanted=wanted)
c1 = Q.counts(); say("delta:", {k: c1[k] - c0[k] for k in c1}); say("done")
