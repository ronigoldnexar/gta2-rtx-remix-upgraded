#!/usr/bin/env python3
"""A death and the respawn in the 3D views, for a swapped district (QA_DISTRICT=bil|ste) or
Downtown. Per round: the view (third, then first), a frame alive, the nearest parked car
(F9) blown up with him at the wheel ([devtools] set_car_damage), frames every 0.5 s through WASTED and
the respawn, then the player found again by the renderer (a 'view: player' line at the new
spot with health back up), frames there and a short walk, so the run visibly continues.
Lines 'MARK' and 'CHECK' in keys.log; frames /out/qa_sd_<round>_*.png."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
import drive_lib as D
import tour_lib as T
from qa_lib import say, tap, shot

MISSION = re.compile(r"\[([\d:.]+)\] view: mission .*?lives=(\d+) death=-?\d+ wanted=-?\d+ health=(-?\d+)")
PLAYER = re.compile(r"\[([\d:.]+)\] view: player x=([\d.]+) y=([\d.]+)")


def last_mission():
    m = None
    for m in MISSION.finditer(Q.log_text(60000)): pass
    return (int(m.group(2)), int(m.group(3))) if m else (-1, -1)


def set_ini(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t2 = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    if t2 == t and f"{key}=" not in t: t2 = t.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(T.INI, "w", encoding="latin-1").write(t2)
    say(f"MARK {key}={val}")


def frames(tag, secs, every=0.5):
    t0 = time.time()
    while time.time() - t0 < secs:
        shot(f"{tag}_{int(round((time.time() - t0) * 10)):03d}")
        time.sleep(max(0.02, every - ((time.time() - t0) % every)))


def one_death(rnd, view):
    tag = f"sd_{rnd}_{view}"
    s = D.wait_state(); lives0, hp0 = last_mission()
    say(f"MARK {tag} start: lives={lives0} health={hp0} {Q.words(s)}")
    Q.set_view(view, settle=1.5); shot(f"{tag}_a_alive")
    at = (s["x"], s["y"])
    # The death: F9 (devtools warp_key) puts him at the nearest parked car's door, Return gets
    # in, [devtools] set_car_damage=31995 leaves the car one point short of exploding, and the
    # next knock (reversing, then driving forward) blows it up with him at the wheel.
    died = False
    # (a loaded host can run the game at a few frames a second: every wait is on the log)
    for attempt in range(4):
        n0 = Q.log_text().count("devtools: warped the player")
        tap("F9", 0.4); t0 = time.time()
        while time.time() - t0 < 15 and Q.log_text().count("devtools: warped the player") == n0: time.sleep(0.3)
        time.sleep(1.5); tap("Return", 0.4)
        t0 = time.time()
        while time.time() - t0 < 25 and not (D.state() or {}).get("driving"): time.sleep(0.3)
        st = D.state() or {}
        say(f"MARK {tag} car attempt {attempt}: driving={st.get('driving')} model={st.get('cmodel')}")
        if st.get("driving"): break
    Q.set_view(view, settle=0.5); shot(f"{tag}_a_car")
    set_ini("set_car_damage", 31995)
    t0 = time.time()
    for key in ("Down", "Up") * 6:
        D.xdo("keydown", key); t1 = time.time()
        while time.time() - t1 < 4.0:
            lv, hp = last_mission(); st = D.state() or {}
            if (0 <= lv < lives0) or st.get("state") in (8, 9): died = True; break
            time.sleep(0.2)
        D.xdo("keyup", key)
        if died: break
    say(f"MARK {tag} died={died} after {time.time() - t0:.1f} s lives={last_mission()[0]}")
    at = ((D.state() or s)["x"], (D.state() or s)["y"])
    frames(f"{tag}_b_death", 7.0, 0.5)
    set_ini("set_car_damage", -1)
    # the respawn: a player line far from the death spot with health back up
    t0 = time.time(); found = None
    while time.time() - t0 < 150:
        st = D.state(); lv, hp = last_mission()
        if st and hp > 0 and abs(st["x"] - at[0]) + abs(st["y"] - at[1]) > 2.0 and st.get("state") not in (8, 9):
            found = st; break
        shot(f"{tag}_c_wait_{int(time.time() - t0):02d}") if int(time.time() - t0) % 2 == 0 else None
        time.sleep(0.5)
    lv, hp = last_mission()
    if not found:
        say(f"CHECK {tag} RESPAWN NOT FOUND lives={lv} health={hp} view={Q.current_view()}")
        return False
    say(f"CHECK {tag} respawned at {found['x']:.2f},{found['y']:.2f} after {time.time() - t0:.1f} s, lives {lives0}->{lv}, health {hp}, view={Q.current_view()}")
    time.sleep(2.0); shot(f"{tag}_d_found")
    Q.set_view(view, settle=1.0); shot(f"{tag}_e_found_view")
    D.hold("Up", 2.0); time.sleep(0.5); shot(f"{tag}_f_walked")
    s2 = D.wait_state(); say(f"MARK {tag} after the walk: {Q.words(s2)}")
    return True


Q.start("swapdeath " + os.environ.get("SWAP_LEVEL", "wil"))
s = D.wait_state(); say(f"MARK start {Q.words(s)} lives/health={last_mission()}")
ok = []
for rnd, view in enumerate(os.environ.get("SD_VIEWS", "third first").split()):
    try:
        ok.append(one_death(rnd, view))
    except Exception as e:
        say(f"MARK round {rnd} failed: {e!r}"); ok.append(False)
Q.report("swapdeath", rounds=len(ok), respawned=sum(ok))
import a3_lib as A
A.finish()
open("/out/.keys_done", "w").close()
