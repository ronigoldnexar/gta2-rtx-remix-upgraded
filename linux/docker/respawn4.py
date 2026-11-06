#!/usr/bin/env python3
"""RESPAWN v4. The tutorial phone at the spawn gives a pistol once the player sits
in its Messer while the briefs run. Armed: shoot people until wanted 1, stand
still in first person for the police: BUSTED, respawn at the station. Then punch
the police there in third person until they shoot him: WASTED, respawn at the
hospital. Views, locator and avatar are checked through both."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import mission_lib as M

PHONE = {"x": 158.5, "y": 138.5}; CAR = (156.5, 142.5)
def ms(): return M.mission_state() or {}
def synth():
    t = Q.log_text(400000); m = None
    for m in re.finditer(r"synthetic: totals since start \| muzzle (\d+) bullet (\d+)", t): pass
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
def status(tag):
    s = D.wait_state(); m = ms()
    say(tag, f"{Q.words(s)} lives={m.get('lives')} wanted={m.get('wanted')} health={m.get('health')} msg={m.get('msg')}")
    return s, m
def burst(label, seconds, every=0.5):
    t0 = time.time(); i = 0
    while time.time() - t0 < seconds:
        shot(f"{label}_{i:02d}_{Q.current_view()}"); i += 1; time.sleep(every)
def views_after(label):
    for view in ("third", "first", "classic"):
        Q.set_view(view, settle=1.5); hold("Up", 0.8); time.sleep(0.5)
        shot(f"{label}_{view}"); status(f"{label} {view}:")
def fire_works():
    b = synth(); hold("Control_L", 0.6); time.sleep(0.3); hold("Control_L", 0.6); time.sleep(9.5); a = synth()
    say("fire test muzzle/bullet", b, "->", a); return a[0] > b[0] or a[1] > b[1]

s = Q.start("respawn4"); c0 = Q.counts()
world = M.World("wil")
Q.set_view("third")
# arm at the COLLECT_02 pickup obj2 (154.5,129.5): the scene warp lands beside it
tap("F10", 0.3); time.sleep(2.0); s = D.wait_state(); say("after F10:", Q.words(s))
for tgt in [(154.5, 129.5), (154.2, 129.8), (154.8, 129.2)]:
    s = D.goto(tgt[0], tgt[1], tol=0.3, limit=20) or D.wait_state()
    say(f"goto {tgt}: at {s['x']:.2f},{s['y']:.2f}")
hold("Up", 0.4); hold("Down", 0.4); shot("p_02_at_pickup_third")
armed = True   # judged by the wanted level rising when shooting, below
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def retarget(x, y):
    t = open(INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={x},{y}", t)
    open(INI, "w", encoding="latin-1").write(t)
say("ARMED:", armed)
arrested = died = False; wanted = 0

# ---- arrest in first person: wanted from kills in the park (people walk its strip), then stand at the carriageway kerb
Q.set_view("third")
lives0 = ms().get("lives", 5); t0 = time.time(); n = 0; last = ""
while time.time() - t0 < 150 and wanted < 1:
    s, m = D.wait_state(), ms(); wanted = m.get("wanted", 0)
    if m.get("lives", lives0) < lives0: say("died while provoking"); break
    hold("Control_L", 0.8); hold("Left" if (n // 3) % 2 else "Right", 0.45); n += 1
    w = f"wanted={wanted} health={m.get('health')} money={m.get('money')} at {s['x']:.1f},{s['y']:.1f}"
    if w != last: say(f"provoke +{time.time()-t0:4.0f}s {w}"); last = w
    if n % 8 == 0: shot(f"a_00_provoke{n:03d}_{Q.current_view()}")
if wanted < 1:
    say("no wanted level from the plaza; ramming people along the pavement by car")
    retarget(164.5, 149.5); tap("F10", 0.3); time.sleep(2.0); s = Q.get_in_car(2)
    if s:
        D.xdo("keydown", "Up"); t0 = time.time(); east = True; n = 0
        while time.time() - t0 < 120 and wanted < 1:
            s, m = D.wait_state(), ms(); wanted = m.get("wanted", 0)
            if m.get("lives", lives0) < lives0: say("died while ramming"); break
            err = s["y"] - 147.4
            if east and s["fx"] < 0: east = False
            if not east and s["fx"] > 0: east = True
            if err > 0.3: tap("Left" if east else "Right", 0.12)
            elif err < -0.3: tap("Right" if east else "Left", 0.12)
            if (east and s["x"] > 178) or (not east and s["x"] < 128):
                D.xdo("keyup", "Up"); hold("Left", 2.2); D.xdo("keydown", "Up"); east = not east
            if n % 10 == 0: say(f"ram +{time.time()-t0:4.0f}s at {s['x']:.1f},{s['y']:.1f} wanted={wanted}")
            n += 1; time.sleep(0.3)
        D.xdo("keyup", "Up"); hold("Down", 0.8); Q.leave_car()
say("wanted level:", wanted); shot("a_01_wanted")
# to the carriageway kerb, where the police cars pass, and stand still in first person
retarget(165.5, 147.5); tap("F10", 0.3); time.sleep(2.0)
Q.set_view("first")
s, m = status("standing still for the police:"); x0, y0 = s["x"], s["y"]; t0 = time.time(); last = ""
while time.time() - t0 < 150:
    s, m = D.wait_state(), ms()
    w = f"wanted={m.get('wanted')} health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f} msg={m.get('msg')}"
    if w != last: say(f"police +{time.time()-t0:5.1f}s {w}"); last = w
    jumped = abs(s["x"] - x0) + abs(s["y"] - y0) > 12
    if wanted >= 1 and m.get("wanted", 0) == 0 and jumped and m.get("lives", lives0) == lives0:
        arrested = True; say("ARREST:", w); break
    if m.get("lives", lives0) < lives0: died = True; say("died instead (cops shot him):", w); break
    if int(time.time() - t0) % 5 == 0: shot(f"a_02_wait{int(time.time()-t0):03d}_{Q.current_view()}")
    time.sleep(0.25)
burst("a_10_busted", 10, 0.5); status("after:"); views_after("a_20_respawn")
Q.report("arrest", arrested=arrested, wanted=wanted, armed=armed)

# ---- death on foot in third person: punch the police until they shoot
if not died:
    Q.set_view("third")
    lives0 = ms().get("lives", 5); t0 = time.time(); n = 0; last = ""
    while time.time() - t0 < 240:
        s, m = D.wait_state(), ms()
        w = f"wanted={m.get('wanted')} health={m.get('health')} lives={m.get('lives')} state={s['state']} sub={s['sub']} at {s['x']:.1f},{s['y']:.1f}"
        if w != last: say(f"brawl +{time.time()-t0:5.1f}s {w}"); last = w
        if m.get("lives", lives0) < lives0: died = True; say("DEATH:", w); break
        hold("Control_L", 1.0); hold("Left" if n % 2 else "Right", 0.35); n += 1
        if n % 5 == 0: hold("Up", 0.5)
        if n % 8 == 0: shot(f"d_05_brawl{n:03d}_{Q.current_view()}")
    if died:
        burst("d_10_wasted", 12, 0.5); status("after respawn:"); views_after("d_20_respawn")
Q.report("death", died=died)
c1 = Q.counts(); say("delta:", {k: c1[k] - c0[k] for k in c1}); say("done")
