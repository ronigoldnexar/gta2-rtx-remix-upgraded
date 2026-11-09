#!/usr/bin/env python3
"""Helpers shared by the MISSIONS-BATCH2 runners (b2_*.py, Wave M, 9 Nov 2026).

Nothing here changes the frozen runner libraries (mission_lib, drive_lib); it reads the game's
messages incrementally, sets a gang's respect through skills/gang_respect.exe (a developer aid,
always marked), and writes a JSON summary per session."""
import json, re, subprocess, time
import drive_lib as D
import mission_lib as M

say = D.say


class Msgs:
    """every change of the mission line's msg key since construction, read from the log
    incrementally (a brief can be overwritten within a second; the last line alone misses it)"""
    RX = re.compile(r"view: mission money=(-?\d+) .*?msg=(\S*) ")

    def __init__(self):
        self.off = M.log_size(); self.last = None; self.seen = []; self.buf = ""

    def poll(self):
        try:
            with open(D.LOG, "rb") as f:
                f.seek(self.off); data = f.read(); self.off += len(data)
        except OSError:
            return self.seen
        text = self.buf + data.decode("latin-1"); cut = text.rfind("\n")
        self.buf = text[cut + 1:] if cut >= 0 else text
        for m in self.RX.finditer(text[:cut + 1] if cut >= 0 else ""):
            k = m.group(2)
            if k != self.last:
                self.last = k; self.seen.append((time.time(), k))
                say(f"message {k}")
        return self.seen

    def keys(self):
        self.poll(); return [k for _, k in self.seen]

    def saw(self, keys):
        return any(k in keys for k in self.keys())


def respect(gang, value=None):
    """gang: a name fragment or the gang index (b2_respect.exe takes both)"""
    args = ["wine", "/work/missions/b2_respect.exe"] + ([gang, str(value)] if value is not None else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    for line in out.splitlines(): say(line)
    return out


class Result:
    def __init__(self, path):
        self.path = path; self.d = dict(stage="start", events=[])

    def ev(self, what):
        self.d["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); self.save()

    def save(self):
        try:
            with open(self.path, "w") as f: json.dump(self.d, f, indent=1)
        except OSError:
            pass


def shots(prefix, n=3, gap=0.6):
    for i in range(n):
        M.shot(f"{prefix}_{i}"); time.sleep(gap)


# cars a runner may borrow (the script's model enum, skills/steal_car.MODELS): no police, army, fire,
# medic, bank or SWAT vehicles, no train parts, trucks, tanks or bikes
NO_BORROW = {3, 4, 6, 12, 17, 21, 22, 34, 52, 54, 55, 59, 60, 61, 63, 64, 65, 66, 69}
BORROW = set(range(0, 71)) - NO_BORROW


def any_car(world, toward=None, budget=240, view_switch=None):
    """a car by any means: the shared any_car2 for a short while (a parked car, a car stopping at the
    kerb), then the steal-car skill on any civilian model (b2_gcb5 stood 4 minutes at a kerb
    waiting for a car to stop beside him)"""
    import math
    from skills import steal_car as SC
    s = D.wait_state()
    if s["driving"]: return s
    s = M.any_car2(world, budget=35)
    if s and s["driving"]: return s
    s = D.wait_state()
    search = [toward] if toward else None
    s2 = SC.steal_car(world, sorted(BORROW), search=search, budget=budget, view_switch=view_switch)
    return s2 or D.wait_state()
