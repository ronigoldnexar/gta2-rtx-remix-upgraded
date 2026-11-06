#!/usr/bin/env python3
"""RESPAWN v2. Death on foot in third person: grind the brought car against the
west wall of the carriageway until it burns, get out, stand beside it; the blast
kills the player on foot so the fall clip and the WASTED screen show in the chase
view. Then an arrest in first person: drive along the pavement into pedestrians
until the wanted level rises, stop, get out, stand for the police."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import mission_lib as M

def ms(): return M.mission_state() or {}
def status(tag):
    s = D.wait_state(); m = ms()
    say(tag, f"{Q.words(s)} lives={m.get('lives')} wanted={m.get('wanted')} health={m.get('health')} cardmg={m.get('cardmg')}")
    return s, m
def burst(label, seconds, every=0.5):
    t0 = time.time(); i = 0
    while time.time() - t0 < seconds:
        shot(f"{label}_{i:02d}_{Q.current_view()}"); i += 1; time.sleep(every)
def views_after(label):
    for view in ("third", "first", "classic"):
        Q.set_view(view, settle=1.5); hold("Up", 0.8); time.sleep(0.5)
        shot(f"{label}_{view}"); status(f"{label} {view}:")
def wait_death(lives0, seconds, label):
    t0 = time.time(); last = ""
    while time.time() - t0 < seconds:
        s, m = D.wait_state(), ms()
        w = f"health={m.get('health')} lives={m.get('lives')} cardmg={m.get('cardmg')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
        if w != last: say(f"{label} +{time.time()-t0:5.1f}s {w}"); last = w
        if m.get("lives", lives0) < lives0: say("DEATH:", w); return True
        time.sleep(0.2)
    return False

s = Q.start("respawn2")
c0 = Q.counts()
died = False; arrested = False; wanted = 0

# ---- A: on-foot death beside the burning car, chase view
Q.set_view("third")
s = Q.get_in_car(3)
if s:
    lives0 = ms().get("lives", 5)
    # U-turn to face west, then grind at the wall at x~52
    hold("Left", 2.3); D.xdo("keydown", "Up")
    t0 = time.time(); last = ""
    while time.time() - t0 < 150:
        s, m = D.wait_state(), ms()
        w = f"cardmg={m.get('cardmg')} at {s['x']:.1f},{s['y']:.1f} state={s['state']}"
        if w != last: say(f"grind +{time.time()-t0:4.0f}s {w}"); last = w
        if not s["driving"] and m.get("lives", lives0) < lives0:
            say("died in the car before getting out"); died = True; break
        if m.get("cardmg", 0) >= 175 or (time.time() - t0 > 40 and s["x"] < 54):
            if m.get("cardmg", 0) >= 175:
                D.xdo("keyup", "Up"); say("car damaged enough, getting out:", w); break
        time.sleep(0.3)
    D.xdo("keyup", "Up")
    if not died:
        shot("d_00_burning_third")
        Q.leave_car(); hold("Down", 0.3)
        s, m = status("out beside the car:")
        shot("d_01_standing_third")
        died = wait_death(lives0, 45, "stand")
        if not died:
            say("no blast yet: back in to grind more")
            tap("Return", 0.3); time.sleep(2); D.xdo("keydown", "Up"); time.sleep(25); D.xdo("keyup", "Up")
            Q.leave_car(); hold("Down", 0.3); status("out again:")
            died = wait_death(lives0, 45, "stand2")
    if died:
        burst("d_10_wasted", 12, 0.5)
        status("after respawn:")
        views_after("d_20_respawn")
Q.report("death", died=died)

# ---- B: arrest, first person
Q.set_view("third")
s = Q.get_in_car(3)
if s:
    Q.set_view("first")
    lives0 = ms().get("lives", 5)
    D.xdo("keydown", "Up"); t0 = time.time(); n = 0; east = True; last = ""
    while time.time() - t0 < 150 and wanted < 1:
        s, m = D.wait_state(), ms(); wanted = m.get("wanted", 0)
        if m.get("lives", lives0) < lives0: say("died while driving"); break
        # the pavement with people lies at y~147.5 (the road is y>=148.5)
        err = s["y"] - 147.5
        if east and s["fx"] < 0: east = False
        if not east and s["fx"] > 0: east = True
        left_is_north = east
        if err > 0.25: tap("Left" if left_is_north else "Right", 0.12)
        elif err < -0.25: tap("Right" if left_is_north else "Left", 0.12)
        if (east and s["x"] > 176) or (not east and s["x"] < 122):
            D.xdo("keyup", "Up"); hold("Left", 2.2); D.xdo("keydown", "Up"); east = not east
            say("U-turn, now heading", "east" if east else "west")
        w = f"at {s['x']:.1f},{s['y']:.1f} wanted={wanted} cardmg={m.get('cardmg')}"
        if w != last and n % 4 == 0: say(f"pavement +{time.time()-t0:4.0f}s {w}"); last = w
        if n % 20 == 0: shot(f"a_00_drive{n:03d}_{Q.current_view()}")
        n += 1; time.sleep(0.3)
    D.xdo("keyup", "Up")
    say("wanted level:", wanted); shot("a_01_wanted_first")
    hold("Down", 0.8); Q.leave_car(); hold("Down", 0.3)
    s, m = status("standing for the police:")
    t0 = time.time(); last = ""; x0, y0 = s["x"], s["y"]
    while time.time() - t0 < 120:
        s, m = D.wait_state(), ms()
        w = f"wanted={m.get('wanted')} health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
        if w != last: say(f"police +{time.time()-t0:5.1f}s {w}"); last = w
        jumped = abs(s["x"] - x0) + abs(s["y"] - y0) > 12
        if wanted >= 1 and m.get("wanted", 0) == 0 and jumped and m.get("lives", lives0) == lives0:
            arrested = True; say("ARREST (wanted cleared, moved to the station):", w); break
        if m.get("lives", lives0) < lives0: say("died instead:", w); break
        if int(time.time() - t0) % 8 == 0: shot(f"a_02_wait{int(time.time()-t0):03d}_{Q.current_view()}")
        time.sleep(0.25)
    burst("a_10_busted", 10, 0.5)
    status("after:"); views_after("a_20_respawn")
Q.report("arrest", arrested=arrested, wanted=wanted)
c1 = Q.counts(); say("delta:", {k: c1[k] - c0[k] for k in c1}); say("done")
