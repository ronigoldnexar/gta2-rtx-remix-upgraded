#!/usr/bin/env python3
"""Behaviour counts from a run's `ai:` census (dll/src/city_ai.cpp), per phase of a
scripted session (docs/city-ai.md).

    tools/ai_census.py <out dir> [<out dir> ...]

Each out dir needs gta2dx9.log and marks.txt (epoch seconds + label per line, as the
gamerun runners write). Phases run from one mark to the next. For every phase: the mean
of each census field (peds within census_radius of the player on foot: walk/run/stand/
down/dead/panic/flee; driven cars: moving/stopped/queued/free stop, share of moving cars
within 10 degrees of a street axis, mean speed in blocks/s) and the event counts (flee
onsets, dodges, fire flees, near misses, threat frames). After a "gunfire start" mark:
the peds that started fleeing within 6 game s, by distance from the player when they did.
"""
import collections, datetime, re, sys

LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\] ai: (.*)$")
KV = re.compile(r"(\w+)=([-\w.]+)")


def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def load(out):
    census, events = [], []
    with open(f"{out}/gta2dx9.log", "rb") as f:
        for raw in f:
            m = LINE.match(raw.decode("latin-1").rstrip("\r\n"))
            if not m:
                continue
            t = secs(*m.groups()[:4])
            body = m.group(5)
            if body.startswith("event "):
                kind = body.split()[1]
                kv = dict(KV.findall(body))
                events.append((t, kind, kv))
            elif body.startswith("frame="):
                kv = dict(KV.findall(body))
                census.append((t, kv))
    marks = []
    try:
        for line in open(f"{out}/marks.txt"):
            p = line.split(None, 1)
            if len(p) < 2:
                continue
            dt = datetime.datetime.fromtimestamp(float(p[0]), datetime.timezone.utc)
            label = re.sub(r" game=\d+s$", "", p[1].strip())
            marks.append((dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6, label))
    except OSError:
        pass
    return census, events, marks


FIELDS = ["fps", "peds", "walk", "run", "stand", "down", "dead", "panic", "flee", "cars", "moving", "stopped", "queued",
          "freestop", "axis", "speed"]
COUNTS = ["threat", "onsets", "dodges", "fireflees", "nearmiss", "dodgeclear", "dodgedown"]


def phase_table(census, events, marks):
    bounds = marks + [(1e9, "end")]
    rows = []
    for (t0, label), (t1, _) in zip(bounds, bounds[1:]):
        c = [kv for t, kv in census if t0 <= t < t1]
        if not c:
            continue
        mean = {k: sum(float(kv.get(k, 0)) for kv in c) / len(c) for k in FIELDS if k != "fps"}
        tot = {k: sum(int(kv.get(k, 0)) for kv in c) for k in COUNTS}
        street = sum(1 for kv in c if kv.get("view") == "street")
        tt = [t for t, kv in census if t0 <= t < t1]
        ff = [int(kv["frame"]) for t, kv in census if t0 <= t < t1]
        fps = (ff[-1] - ff[0]) / (tt[-1] - tt[0]) if len(ff) > 1 and tt[-1] > tt[0] else 0.0
        mean["fps"] = fps
        rows.append((label, t1 - t0 if t1 < 1e9 else len(c), len(c), street, mean, tot))
    return rows


def gunfire(events, marks, census):
    starts = [t for t, l in marks if l.startswith("gunfire start")]
    out = []
    for t0 in starts:
        # the window is 6 game seconds (180 frames), whatever the wall clock did
        f0 = next((int(kv["frame"]) for t, kv in census if t >= t0), None)
        ft = [(t, int(kv["frame"])) for t, kv in census]
        t_end = next((t for t, f in ft if f0 is not None and f >= f0 + 180), t0 + 6.0)
        bands = collections.Counter()
        ids = set()
        for t, kind, kv in events:
            if kind == "flee" and t0 <= t < t_end and kv.get("id") not in ids:
                ids.add(kv.get("id"))
                d = float(kv.get("d", 0))
                bands["0-4" if d < 4 else "4-8" if d < 8 else "8-12" if d < 12 else "12-20" if d < 20 else "20+"] += 1
        out.append((t0, len(ids), bands))
    return out


def main():
    for out in sys.argv[1:]:
        census, events, marks = load(out)
        print(f"== {out}: {len(census)} census lines, {len(events)} events, {len(marks)} marks")
        print(f"{'phase':<16}{'s':>5}{'n':>4}{'st':>4} " + " ".join(f"{k:>7}" for k in FIELDS) + " | " +
              " ".join(f"{k:>8}" for k in COUNTS))
        for label, dur, n, street, mean, tot in phase_table(census, events, marks):
            print(f"{label[:15]:<16}{dur:5.0f}{n:4d}{street:4d} " + " ".join(f"{mean[k]:7.2f}" for k in FIELDS) + " | " +
                  " ".join(f"{tot[k]:8d}" for k in COUNTS))
        for t0, n, bands in gunfire(events, marks, census):
            print(f"gunfire: {n} peds started fleeing within 6 game s, by distance: " +
                  ", ".join(f"{b}: {bands.get(b, 0)}" for b in ["0-4", "4-8", "8-12", "12-20", "20+"]))
        kinds = collections.Counter(k for _, k, _ in events)
        print("events:", dict(kinds))


if __name__ == "__main__":
    main()
