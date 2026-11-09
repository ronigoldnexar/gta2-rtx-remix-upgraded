#!/usr/bin/env python3
"""VEHICLE-PHYSICS telemetry: the player car's body motion per manoeuvre of a vphys take.
    vphys_telemetry.py <run dir> [--csv out.csv] [--json out.json]
Reads <run>/gta2dx9.log (GTA2DX9_LOG_VEHICLE_FEEL=1: 'vehicle feel: player car ...' and
'vehicle physics: player car ...' every 3 frames, 'vehicle physics: impact ...') and
<run>/marks.txt (gamerun/vphys_take.py), and prints for each variant (before = the first
VEHICLE-FEEL springs, after = VEHICLE-PHYSICS):
  brake : peak nose dive (deg), peak decel, overshoot after the stop, settling time
          (the stop to |pitch| staying under 0.3 deg), front/rear tyre use, slip
  corner: peak roll (deg), peak lateral accel, outside/inside load, tyre use, settling
  crash : impacts (dv, corner, damage), peak pitch/roll kick, settling, corner damage
Log times are the container's clock (UTC); marks are epoch seconds."""
import json, re, sys, datetime as dt

run = sys.argv[1].rstrip("/")
args = sys.argv[2:]


def opt(name):
    return args[args.index(name) + 1] if name in args else None


marks = []
for line in open(f"{run}/marks.txt"):
    t, what = line.split(" ", 1)
    marks.append((float(t), what.strip()))
day0 = dt.datetime.fromtimestamp(marks[0][0], dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

rows, phys, impacts = [], [], []
num = r"(-?[\d.]+)"
for line in open(f"{run}/gta2dx9.log", errors="ignore"):
    m = re.match(r"\[(\d+):(\d+):([\d.]+)\] (.*)", line)
    if not m:
        continue
    t = day0 + int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    body = m.group(4)
    if t < marks[0][0] - 3600:
        t += 86400
    if body.startswith("vehicle feel: player car v="):
        d = {k: float(v) for k, v in re.findall(r"(\w+)=" + num, body)}
        d["t"] = t
        rows.append(d)
    elif body.startswith("vehicle physics: player car"):
        d = {"t": t}
        for k in ("load", "use", "slip", "lift", "camber", "corners"):
            mm = re.search(k + r"=([-\d. ]+?)(?= \w+=|$)", body)
            if mm:
                d[k] = [float(x) for x in mm.group(1).split()]
        mm = re.search(r"carried=" + num + "," + num, body)
        if mm:
            d["carried"] = (float(mm.group(1)), float(mm.group(2)))
        mm = re.search(r"shove=" + num + "," + num, body)
        if mm:
            d["shove"] = (float(mm.group(1)), float(mm.group(2)))
        phys.append(d)
    elif body.startswith("vehicle physics: impact"):
        mm = re.search(r"dv=" + num + r".*along " + num + r", across " + num + r"\) at corner (\d), damage \+(\d+) -> (\d+), corners (.*)", body)
        if mm:
            impacts.append({"t": t, "dv": float(mm.group(1)), "along": float(mm.group(2)), "across": float(mm.group(3)),
                            "corner": int(mm.group(4)), "ddamage": int(mm.group(5)), "damage": int(mm.group(6)),
                            "corners": [float(x) for x in mm.group(7).split()], "player": "(player)" in body})


def mark_t(what):
    for t, w in marks:
        if w == what:
            return t
    return None


def window(a, b):
    return [r for r in rows if a <= r["t"] <= b], [p for p in phys if a <= p["t"] <= b]


def settle(rs, key, t_from, thresh=0.3):
    """Seconds from t_from until |key| stays under thresh (deg) for the rest of the window."""
    after = [r for r in rs if r["t"] >= t_from]
    last_bad = None
    for r in after:
        if abs(r[key]) >= thresh:
            last_bad = r["t"]
    if not after:
        return None
    return 0.0 if last_bad is None else round(last_bad - t_from + 0.1, 2)


out = {}
for tag in ("before", "after"):
    res = {}
    tb, te = mark_t(f"{tag} brake"), mark_t(f"{tag} brake end")
    if tb and te:
        rs, ps = window(tb - 0.2, te)
        if rs:
            pk = max(rs, key=lambda r: r["pitch"])
            # the stop: the first row after the peak with |v| < 0.15
            stop = next((r["t"] for r in rs if r["t"] > pk["t"] and abs(r["v"]) < 0.15), pk["t"])
            post = [r["pitch"] for r in rs if r["t"] > stop]
            res["brake"] = {
                "peak_dive_deg": pk["pitch"], "peak_decel_blocks_s2": -min(r["aF"] for r in rs),
                "speed_at_brake": max(abs(r["v"]) for r in rs[:4]),
                "rebound_deg": min(post) if post else None,
                "settle_s_after_stop": settle(rs, "pitch", stop),
                "front_use_max": max((max(p["use"][0:2]) for p in ps if "use" in p), default=None),
                "rear_use_max": max((max(p["use"][2:4]) for p in ps if "use" in p), default=None),
                "slip_max": max((max(p["slip"]) for p in ps if "slip" in p), default=None),
                "front_load_max": max((p["load"][0] + p["load"][1] for p in ps if "load" in p), default=None),
            }
    tc, te = mark_t(f"{tag} corner"), mark_t(f"{tag} corner end")
    if tc and te:
        rs, ps = window(tc - 0.2, te)
        if rs:
            pk = max(rs, key=lambda r: abs(r["roll"]))
            res["corner"] = {
                "peak_roll_deg": pk["roll"], "peak_lat_blocks_s2": max(abs(r["aL"]) for r in rs),
                "speed": max(abs(r["v"]) for r in rs),
                "steer_max": max(abs(r["steer"]) for r in rs),
                "settle_s_after_turn": settle(rs, "roll", tc + 1.6 + 0.3),
                "outside_load_max": max((max(p["load"][0] + p["load"][2], p["load"][1] + p["load"][3]) for p in ps if "load" in p), default=None),
                "tyre_use_max": max((max(p["use"]) for p in ps if "use" in p), default=None),
                "slip_max": max((max(p["slip"]) for p in ps if "slip" in p), default=None),
            }
    tk, te = mark_t(f"{tag} crash run"), mark_t(f"{tag} crash end")
    if tk and te:
        rs, ps = window(tk, te)
        imp = [i for i in impacts if tk <= i["t"] <= te and i["player"]]
        if rs:
            res["crash"] = {
                "impacts": [{k: i[k] for k in ("dv", "along", "across", "corner", "ddamage", "damage")} for i in imp],
                "max_jolt": max(r["jolt"] for r in rs),
                "peak_pitch_deg": max(rs, key=lambda r: abs(r["pitch"]))["pitch"],
                "peak_roll_deg": max(rs, key=lambda r: abs(r["roll"]))["roll"],
                "damage_end": rs[-1]["dmg"],
                "corners_end": ps[-1]["corners"] if ps and "corners" in ps[-1] else None,
                "shove_max": max((max(abs(p["shove"][0]), abs(p["shove"][1])) for p in ps if "shove" in p), default=None),
                "settle_s_after_first_hit": settle(rs, "pitch", imp[0]["t"]) if imp else None,
            }
    out[tag] = res

print(json.dumps(out, indent=1))
if opt("--json"):
    json.dump(out, open(opt("--json"), "w"), indent=1)
if opt("--csv"):
    with open(opt("--csv"), "w") as f:
        f.write("t,v,aF,aL,roll,pitch,heave,steer,jolt,dmg\n")
        for r in rows:
            f.write(",".join(str(r.get(k, "")) for k in ("t", "v", "aF", "aL", "roll", "pitch", "heave", "steer", "jolt", "dmg")) + "\n")
