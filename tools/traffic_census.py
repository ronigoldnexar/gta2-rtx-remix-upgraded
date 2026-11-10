#!/usr/bin/env python3
"""FIX-TRAFFIC-1: traffic census of a run from the renderer's `ai:` lines (street views only),
split by the probe's marks (/out/marks.txt: stand start/end, drive start/end).

  tools/traffic_census.py out/<run> [out/<run> ...]

Per segment: mean driven cars within the census radius, moving, stopped, queued, free stops
and their causes (fs_ped, fs_gap, fs_cross, fs_junction, fs_mid), shares of the cars, and the
stop events per car-minute (stops, hard stops from over 2.5 blocks/s, stop-start cycles: a stop
under 2 s after the car got going). Also the ambient traffic and cap of the `density:` lines."""
import datetime, os, re, sys

KEYS = ("cars", "moving", "stopped", "queued", "freestop", "fs_ped", "fs_gap", "fs_cross", "fs_junction", "fs_mid", "fresh")
EVENTS = ("stops", "hardstops", "stopstart")


def ts(line, day):
    m = re.match(r"\[(\d+):(\d+):(\d+)\.(\d+)\]", line)
    if not m: return None
    h, mi, s, ms = map(int, m.groups())
    return day + h * 3600 + mi * 60 + s + ms / 1000.0


def segments(run):
    marks = []
    p = os.path.join(run, "marks.txt")
    if os.path.exists(p):
        for l in open(p):
            t, what = l.split(" ", 1)
            marks.append((float(t), what.strip()))
    segs = {}
    starts = {}
    for t, w in marks:
        if w.endswith(" start"): starts[w[:-6]] = t
        elif w.endswith(" end") and w[:-4] in starts: segs[w[:-4]] = (starts[w[:-4]], t)
    return segs


def main():
    for run in sys.argv[1:]:
        log = open(os.path.join(run, "gta2dx9.log"), encoding="latin-1").read().splitlines()
        segs = segments(run)
        # the log's clock is UTC hh:mm:ss; the marks are epoch seconds of the same host clock
        day0 = None
        if segs:
            t = min(a for a, _ in segs.values())
            d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
            day0 = (datetime.datetime(d.year, d.month, d.day) - datetime.datetime(1970, 1, 1)).total_seconds()
        rows = {k: [] for k in list(segs) + ["all"]}
        caps = {k: [] for k in rows}
        for l in log:
            if "ai: frame=" in l and "view=street" in l:
                v = dict(re.findall(r"(\w+)=(-?[\d.]+)", l))
                t = ts(l, day0) if day0 is not None else None
                rows["all"].append(v)
                for k, (a, b) in segs.items():
                    if t is not None and a <= t <= b: rows[k].append(v)
            elif "density: view=street" in l:
                m = re.search(r"traffic=(\d+)/(\d+)", l)
                t = ts(l, day0) if day0 is not None else None
                if m:
                    caps["all"].append((int(m.group(1)), int(m.group(2))))
                    for k, (a, b) in segs.items():
                        if t is not None and a <= t <= b: caps[k].append((int(m.group(1)), int(m.group(2))))
        print(f"== {run}")
        for k, r in rows.items():
            if not r: continue
            n = len(r)
            mean = {key: sum(float(x.get(key, 0)) for x in r) / n for key in KEYS}
            ev = {key: sum(float(x.get(key, 0)) for x in r) for key in EVENTS}
            carmin = mean["cars"] * n / 60.0   # one line a second
            cars = mean["cars"] or 1.0
            c = caps[k]
            capstr = f"traffic {min(a for a,_ in c)}-{max(a for a,_ in c)} cap {min(b for _,b in c)}-{max(b for _,b in c)}" if c else ""
            print(f"  {k:6s} n={n:4d}s cars={mean['cars']:.1f} moving={mean['moving']:.1f} stopped={mean['stopped']:.1f} "
                  f"({mean['stopped']/cars:.0%}) queued={mean['queued']:.1f} freestop={mean['freestop']:.1f} ({mean['freestop']/cars:.0%}) "
                  f"| ped={mean['fs_ped']:.1f} gap={mean['fs_gap']:.1f} cross={mean['fs_cross']:.1f} junction={mean['fs_junction']:.1f} mid={mean['fs_mid']:.1f} fresh={mean['fresh']:.1f} "
                  f"| per car-min: stops={ev['stops']/max(carmin,1e-6):.2f} hard={ev['hardstops']/max(carmin,1e-6):.2f} "
                  f"stopstart={ev['stopstart']/max(carmin,1e-6):.2f} | {capstr}")


if __name__ == "__main__":
    main()
