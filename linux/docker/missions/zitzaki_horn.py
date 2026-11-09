#!/usr/bin/env python3
"""GET ZITZAKI! (Downtown, wil_ye1) with its horn stop played by the horn pick-up skill
(gamerun/skills/horn_pickup.py, SKILL-HORN).

The job runner is SKILL-DELIVER's missions/get_zitzaki.py, imported unchanged: phone, Miura,
deliver_intact into the hospital's 3 x 1 box, the J-Lab garage. Only its horn step
(`horn_for_doctor`) is replaced, in this process, by `horn_pickup.pickup` on a Stop that says
what the script (assets-src/missions/wil_m/wil_ye1.mis) wants:
  * the box: LOCATE_CHARACTER_BY_CAR (p1, 50.5, 178.5, 2.0, 3.0, 1.0) in the Miura (a 3 x 1 strip:
    `narrow`, entered with deliver_intact's open-side creep); out of it, 1648 and the arrow back;
  * the horn: IS_CHAR_PRESSING_HORN with the car in that strip; the script answers with no brief,
    it creates Dr ZitZaki (remap 13) at 47.5,178.5: `horned` = he is in the peds line there;
  * aboard: ENTER_CAR_AS_PASSENGER; IS_CHAR_OBJECTIVE_PASSED -> brief 1639 / the arrow on the
    garage (`get_zitzaki.doctor_aboard`); the car must stay in the strip while he walks
    (`move=False`: leaving it says 1648 and the doctor waits).

    python3 /work/missions/zitzaki_horn.py      (keys script missions/keys_zitzaki_horn.sh)
Marks /out/marks.txt (`horn: ...`), frames /out/m_zz_*.png and /out/m_horn_doctor_*.png.
"""
import math, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import missions.get_zitzaki as GZ
from skills import horn_pickup as H

DOCTOR_AT = (48.0, 178.5)


def doctor_out():
    """the horn was taken: the script created him (remap 13) by the hospital door"""
    return any(p["remap"] == 13 and M.ped_alive(p) and math.hypot(p["x"] - DOCTOR_AT[0], p["y"] - DOCTOR_AT[1]) < 3.0
               for p in M.peds())


def horn_by_skill(world, secs=150):
    stop = H.Stop("doctor", GZ.HOSPITAL[0], GZ.HOSPITAL[1], GZ.HOSPITAL[2], GZ.HOSPITAL[3],
                  aboard=GZ.doctor_aboard, horned=doctor_out, man=(47.5, 178.5), count=1,
                  pick=lambda p: p["remap"] == 13, need_box_brief=False, move=False)
    msgs = H.Msgs()
    M.mark("horn: GET ZITZAKI's doctor by skills/horn_pickup.py")
    r = H.pickup(world, stop, msgs, car=GZ.CAR0, check=GZ.check, view_switch=None, budget=secs + 120)
    M.mark(f"horn: doctor stop -> {r}")
    for t, e in H.EVENTS: D.say(f"horn event {time.strftime('%H:%M:%S', time.localtime(t))}: {e}")
    if r in ("complete", "failed", "dead"): raise GZ.Over(r)
    return r == "aboard"


GZ.horn_for_doctor = horn_by_skill

if __name__ == "__main__":
    GZ.main()
