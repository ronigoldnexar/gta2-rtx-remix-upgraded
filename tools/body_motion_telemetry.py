#!/usr/bin/env python3
"""The player's car body motion per burst frame, from a feel_probe run's renderer log.

    tools/body_motion_telemetry.py out/<run> [burst ...]   (default: drive_third drive_first crash_third)

Needs the run made with -e GTA2DX9_LOG_VEHICLE_FEEL=1 (a `vehicle feel: player car` line every
3 game frames: the drawn roll and pitch in degrees, heave in blocks). Each burst's frames are
numbered from its mark in marks.txt (30 fps), so the rows line up with frames cut from
b_<burst>.mp4. Prints, per burst: the per-frame table (every logged line) and the peaks of the
launch, brake, turn and impact windows; writes out/<run>/body_motion.json.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d{3})\] vehicle feel: player car v=(\S+) lat=(\S+) yawr=(\S+) aF=(\S+) aL=(\S+) "
                  r"jolt=(\S+) roll=(\S+) pitch=(\S+) heave=(\S+)")
SHAKE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d{3})\] view: car impact (\S+) blocks/s lost, camera shake (\S+)")


def day_seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def main():
    run = Path(sys.argv[1])
    bursts = sys.argv[2:] or ["drive_third", "drive_first", "crash_third"]
    marks = {}
    for ln in (run / "marks.txt").read_text().splitlines():
        t, _, w = ln.partition(" ")
        if w.startswith("burst "):
            parts = w.split()
            marks[parts[1]] = (float(t), float(parts[2]))
    rows, shakes = [], []
    for ln in (run / "gta2dx9.log").read_text(errors="replace").splitlines():
        m = LINE.match(ln)
        if m:
            g = m.groups()
            rows.append((day_seconds(*g[:4]), *[float(x) for x in g[4:]]))
            continue
        m = SHAKE.match(ln)
        if m:
            g = m.groups()
            shakes.append((day_seconds(*g[:4]), float(g[4]), float(g[5])))
    out = {}
    for b in bursts:
        if b not in marks:
            print(f"{b}: no mark")
            continue
        t0, secs = marks[b]
        d = datetime.fromtimestamp(t0, timezone.utc)
        s0 = d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
        sel = [r for r in rows if s0 - 0.2 <= r[0] <= s0 + secs + 0.2]
        print(f"== {b} ({len(sel)} log lines over {secs} s)")
        print(" frame    v     aF     aL   roll  pitch  heave")
        table = []
        for r in sel:
            f = round((r[0] - s0) * 30)
            v, lat, yawr, aF, aL, jolt, roll, pitch, heave = r[1:]
            table.append({"frame": f, "v": v, "aF": aF, "aL": aL, "roll": roll, "pitch": pitch, "heave": heave})
            print(f"{f:6d} {v:5.2f} {aF:6.1f} {aL:6.1f} {roll:6.2f} {pitch:6.2f} {heave:6.3f}")
        sh = [{"frame": round((s[0] - s0) * 30), "lost": s[1], "shake": s[2]} for s in shakes if s0 <= s[0] <= s0 + secs]
        for s in sh:
            print(f"  camera shake at f{s['frame']}: {s['lost']:.2f} blocks/s lost -> {s['shake']:.2f}")
        peaks = {}
        if table:
            peaks["max_pitch_nose_down"] = max(t["pitch"] for t in table)
            peaks["max_pitch_nose_up"] = min(t["pitch"] for t in table)
            peaks["max_abs_roll"] = max(abs(t["roll"]) for t in table)
            peaks["max_abs_heave"] = max(abs(t["heave"]) for t in table)
            print("  peaks: nose down %.2f deg, nose up %.2f deg, |roll| %.2f deg, |heave| %.3f" %
                  (peaks["max_pitch_nose_down"], peaks["max_pitch_nose_up"], peaks["max_abs_roll"], peaks["max_abs_heave"]))
        out[b] = {"frames": table, "shakes": sh, "peaks": peaks}
    (run / "body_motion.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
