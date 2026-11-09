#!/usr/bin/env python3
"""ARMORED CAR CLASH! (Downtown, the Zaibatsu red phone 181.5,94.5 on a roof, wil_zh1.mis): destroy the two
Yakuza Miuras (bulletproof, rocketproof, flameproof, locked, Dr Cubana inside) within 360 s.
Skill destroy_vehicle (skills/destroy_vehicle.py): the cars take no bullets, so it falls back to the shared
ramming (mission_lib.ram_target, which follows the job's vehicle arrows). MISSIONS-BATCH4, Wave M.

The script (assets-src/missions/wil_m/wil_zh1.mis): title 1987, brief 1701, arrows on both Miuras
(created at 124.5,104.5 and 124.5,100.5, aggressive drivers), a 360 s timer; each wreck 1703; both
wrecked 1702, 1124, $60,000; timer out 1705 / 1125.

Developer aid (marked in /out/marks.txt): skills mb3_respect.exe sets the Zaibatsu (gang 1 in wil.mis) respect
to 100 (the red phone wants 4 bars; a fresh game has 0).

Run (keys script missions/keys_armored_car_clash.sh):
  GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 gamerun/entry_grun.sh <name> 1500 missions/keys_armored_car_clash.sh -e WARP_OK=0 -e GTA2DX9_STATE_EVERY=5
Summary /out/acc_result.json; frames /out/m_acc_*.png.
"""
import json, math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["MISSIONS"] = " "
os.environ.setdefault("WARP_OK", "0")
import drive_lib as D
import mission_lib as M
import mission_play_wil as P
from skills import destroy_vehicle as DV
from skills import rooftop_access as RA

say = D.say
world = P.world
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, say
JOB = "wil_zh1"
TITLE = {"1987", "1701"}
DONE = {"1124", "1702"}
FAIL = {"1125", "1705"}
BUSTED = {"6155", "6158", "6159"}
RESULT = dict(stage="start", events=[])
SEEN = []; LOG_OFF = [0]; LIVES0 = [None]


class Over(Exception):
    pass


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); say(what)


def poll():
    try:
        with open(D.LOG, "rb") as f:
            f.seek(LOG_OFF[0]); data = f.read(); LOG_OFF[0] += len(data)
    except OSError:
        return SEEN
    for k in re.findall(r"view: mission [^\n]*?msg=(\S+)", data.decode("latin-1")):
        if not SEEN or SEEN[-1] != k: SEEN.append(k)
    return SEEN


def seen(keys):
    poll(); return any(k in keys for k in SEEN)


def over():
    poll()
    if any(k in DONE for k in SEEN): return "complete"
    if any(k in FAIL for k in SEEN): return "failed"
    if any(k in BUSTED for k in SEEN): return "busted"
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def respect(gang, value):
    out = ""
    for args in ([str(gang), str(value)], []):
        try:
            out = subprocess.run(["wine", "/work/missions/mb3_respect.exe"] + args, capture_output=True, text=True, timeout=40).stdout.strip()
        except Exception as e:
            out = f"mb3_respect failed: {e}"
        say(f"mb3_respect {args}: {out}")
    M.mark(f"DEV AID: gang respect {gang} {value} ({' | '.join(out.splitlines()[-4:])})")


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: ARMORED CAR CLASH! (missions/armored_car_clash.py, skills/destroy_vehicle.py)")
    poll()
    respect(1, 100)
    info = {}
    for k in range(3):
        ok, ms, info = RA.answer_roof_phone(world, entry, P.answer)
        if ok or seen(TITLE) or info.get("reached"): break
    t0 = time.time()
    while time.time() - t0 < 6 and not seen(TITLE): time.sleep(0.3)
    if not seen(TITLE): return f"phone: no title ({SEEN[-5:]}, {({k: v for k, v in info.items() if k != 'path'})})"
    ms = M.mission_state() or {}
    LIVES0[0] = ms.get("lives"); M.LIVES0[0] = LIVES0[0]
    money0 = ms.get("money", 0)
    ev(f"phone answered: ARMORED CAR CLASH! ({SEEN[-4:]}), money {money0}")
    P.set_view("third"); M.shot("m_acc_phone")
    if "launch" in info:
        lx, ly, ll = info["launch"]
        M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
        M.cruise_to(lx + 0.5, ly + 0.5, tol=0.45, secs=8)
        RA.descend(world, toward=(124.5, 104.5), budget=300)
        M.set_avoid_phones(world, keep=None)
    check(); M.shot("m_acc_down")
    r = M.ram_target(world, money0, secs=float(os.environ.get("ACC_SECS", "400")), view_switch=P.view_switch)
    ev(f"ram_target: {r}")
    t0 = time.time()
    while time.time() - t0 < 15 and not over(): time.sleep(0.5)
    if seen(DONE):
        for i in range(4): M.shot(f"m_acc_complete_{i}"); time.sleep(0.5)
        return "complete"
    return over() or r


def main():
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    ms = M.mission_state() or {}
    ev(f"mission {JOB}: {r} money {ms.get('money')} lives {ms.get('lives')} health {ms.get('health')} msg {ms.get('msg')}")
    time.sleep(2.0); M.shot("m_acc_end")
    RESULT["result"] = r; RESULT["messages"] = SEEN[-40:]
    with open("/out/acc_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", JOB, r)
    M.mark(f"done armored_car_clash={r}")


if __name__ == "__main__":
    main()
