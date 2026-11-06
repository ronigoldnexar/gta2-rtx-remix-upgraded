#!/usr/bin/env python3
"""RESPAWN: provoke a death (pinned on the carriageway after the F10 scene warp,
traffic runs the player over) and an arrest (run over pedestrians by car until
wanted, then stand), each in a street view, and record what the views and the
locator do through the WASTED/BUSTED screens and the respawn."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import mission_lib as M

DEATH_VIEW = os.environ.get("DEATH_VIEW", "third")
ARREST_VIEW = os.environ.get("ARREST_VIEW", "first")
DO = os.environ.get("DO", "death,arrest").split(",")

def ms():
    return M.mission_state() or {}

def status(tag):
    s = D.wait_state(); m = ms()
    w = f"{Q.words(s)} lives={m.get('lives')} wanted={m.get('wanted')} health={m.get('health')} msg={m.get('msg')}"
    say(tag, w); return s, m

def burst(label, seconds, every=0.5):
    """screenshots through an event"""
    t0 = time.time(); i = 0
    while time.time() - t0 < seconds:
        shot(f"{label}_{i:02d}_{Q.current_view()}"); i += 1
        time.sleep(every)

def views_after(label):
    for view in ("third", "first", "classic"):
        Q.set_view(view, settle=1.5); hold("Up", 0.8); time.sleep(0.5)
        shot(f"{label}_{view}"); status(f"{label} {view}:")

s = Q.start("respawn")
c0 = Q.counts()

if "death" in DO:
    Q.set_view(DEATH_VIEW)
    tap("F10", 0.3); time.sleep(1.5)
    s, m = status("after F10 (pinned in the lane):")
    lives0 = m.get("lives", 5)
    shot("d_00_pinned")
    t0 = time.time(); died = False; last = ""
    while time.time() - t0 < 150:
        s, m = D.wait_state(), ms()
        w = f"health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
        if w != last: say(f"+{time.time()-t0:5.1f}s {w}"); last = w
        if m.get("lives", lives0) < lives0 or m.get("health", 100) <= 0:
            died = True; say("DEATH:", w); break
        if int(time.time() - t0) % 20 == 0: shot(f"d_01_wait{int(time.time()-t0):03d}")
        time.sleep(0.25)
    if died:
        burst("d_10_wasted", 12, 0.6)
        s, m = status("after respawn:")
        views_after("d_20_respawn")
    else:
        say("no death in 150 s; trying the fast lane on foot")
    Q.report("death", died=died)

if "arrest" in DO:
    Q.set_view("third")
    s = Q.get_in_car(3)
    if s:
        Q.set_view(ARREST_VIEW)
        t0 = time.time(); wanted = 0; n = 0
        while time.time() - t0 < 120 and wanted < 1:
            # drive at the pavement: a diagonal swerve into the kerb side where people walk
            hold("Up", 1.4); hold("Left" if n % 4 < 2 else "Right", 0.5); n += 1
            m = ms(); wanted = m.get("wanted", 0)
            if n % 6 == 0:
                s, m = status(f"driving +{time.time()-t0:4.0f}s:"); shot(f"a_00_drive{n:03d}_{Q.current_view()}")
        say("wanted level:", wanted)
        shot("a_01_wanted")
        hold("Down", 1.0)
        Q.leave_car()
        s, m = status("out, standing for the police:")
        t0 = time.time(); arrested = False; last = ""; lives0 = m.get("lives", 5)
        while time.time() - t0 < 120:
            s, m = D.wait_state(), ms()
            w = f"wanted={m.get('wanted')} health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f} msg={m.get('msg')}"
            if w != last: say(f"+{time.time()-t0:5.1f}s {w}"); last = w
            if "BUSTED" in Q.log_text(40000) or s["state"] in (12, 13) or (wanted >= 1 and m.get("wanted", 0) == 0 and m.get("lives", lives0) == lives0 and time.time() - t0 > 3):
                arrested = True; say("ARREST:", w); break
            if m.get("lives", lives0) < lives0:
                say("died instead of arrested:", w); break
            if int(time.time() - t0) % 10 == 0: shot(f"a_02_wait{int(time.time()-t0):03d}_{Q.current_view()}")
            time.sleep(0.25)
        burst("a_10_busted", 12, 0.6)
        s, m = status("after the arrest:")
        views_after("a_20_respawn")
        Q.report("arrest", arrested=arrested, wanted=wanted)
    else:
        say("no car for the arrest half")
c1 = Q.counts()
say("locator/faults delta:", {k: c1[k] - c0[k] for k in c1})
say("done")
