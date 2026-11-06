#!/usr/bin/env python3
"""(e2) Die and get arrested, then continue in every view. The weapon pickup east of
the spawn arms the player; shooting people brings the police (wanted level in the
renderer's `view: mission` line), who shoot back or arrest. Death and arrest are read
from lives / death / wanted of that line, so neither is inferred from a position jump."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import mission_lib as M

s = Q.start("death2")
Q.set_view("third")
# Arm: the pickup east of the spawn (qa_pickups walked there before).
# The weapon pickup (base-4 frames 26-33) sits at map 166.5,139.5 behind a wall of the
# plaza, so the devtools scene warp (F10, scene_xy set by qa_run's QA_SED) puts the
# player on it; walking over a pickup collects it.
tap("F10", 0.3); time.sleep(1.5); s = D.wait_state(); say("after warp:", Q.words(s))
hold("Up", 0.5); hold("Down", 0.5); hold("Left", 0.4); hold("Up", 0.5)
ms0 = M.mission_state() or {}
say("armed? lives/wanted/health:", ms0)
shot("d2_00_third_armed")
tap("z", 0.2); time.sleep(0.3)            # next weapon (Z is slot 7 = next weapon in the registry)
start_lives = ms0.get("lives", -1); start_money = ms0.get("money", 0)
t0 = time.time(); died = False; arrested = False; last = ""; n = 0; max_wanted = 0
# Shoot at whoever is around on the plaza; the police come; keep shooting them.
while time.time() - t0 < 240 and not (died and arrested):
    s = D.wait_state(); ms = M.mission_state() or {}
    w = Q.words(s) + f" lives={ms.get('lives')} wanted={ms.get('wanted')} health={ms.get('health')} death={ms.get('death')}"
    if w != last: say(f"+{time.time()-t0:5.1f}s {w}"); last = w
    max_wanted = max(max_wanted, ms.get("wanted", 0))
    if not died and (ms.get("death", 0) != 0 or (start_lives >= 0 and ms.get("lives", start_lives) < start_lives)):
        died = True; say("DEATH detected:", w); shot(f"d2_10_death_{Q.current_view()}")
        time.sleep(6.0); shot(f"d2_11_respawn_{Q.current_view()}")
        for view in ("first", "classic", "third"):
            Q.set_view(view); hold("Up", 1.0); shot(f"d2_12_after_death_{view}")
            say(f"after death {view}: {Q.words(D.wait_state())}")
        Q.set_view("third")
        # re-arm for the arrest half
        tap("F10", 0.3); time.sleep(1.5); hold("Up", 0.5); hold("Down", 0.5); tap("z", 0.2)
    if not arrested and s["state"] in (12, 13) or (not arrested and "BUSTED" in Q.log_text(30000)):
        arrested = True; say("ARREST detected:", w); shot(f"d2_20_arrest_{Q.current_view()}")
        time.sleep(6.0); shot(f"d2_21_after_arrest_{Q.current_view()}")
        for view in ("first", "classic", "third"):
            Q.set_view(view); hold("Up", 1.0); shot(f"d2_22_after_arrest_{view}")
            say(f"after arrest {view}: {Q.words(D.wait_state())}")
        Q.set_view("third")
    # fire a burst, turn a bit, step a bit; when wanted, stop running so the cops reach us
    hold("Control_L", 1.2); time.sleep(0.2)   # a held burst: the pistol fires on hold
    n += 1
    if ms.get("wanted", 0) == 0 and n % 3 == 0:
        hold("Up", 0.4)
    hold("Left" if n % 2 else "Right", 0.35)
    if n % 8 == 0: shot(f"d2_05_loop{n:03d}_{Q.current_view()}")
shot(f"d2_30_end_{Q.current_view()}")
Q.report("death2", died=died, arrested=arrested, max_wanted=max_wanted)
say("done")
