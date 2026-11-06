#!/usr/bin/env python3
"""QA helpers on top of drive_lib: named screenshots, view switching that knows
which view it is in (from the renderer's log), and log checks for faults,
locator loss and frame-time summaries."""
import os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D

say, tap, hold = D.say, D.tap, D.hold
LOG = D.LOG
OUT = "/out"
VIEWS = ["classic", "third", "first"]
_last_view_line = re.compile(r"\] view: (Classic \(top down\)|Third person|First person)$")


def shot(label):
    path = f"{OUT}/qa_{label}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720",
                    "-i", ":99", "-frames:v", "1", path])
    say("shot", label)
    return path


def log_text(tail_bytes=None):
    try:
        with open(LOG, "rb") as f:
            if tail_bytes:
                f.seek(0, 2); size = f.tell(); f.seek(max(0, size - tail_bytes))
            return f.read().decode("latin-1")
    except OSError:
        return ""


def current_view():
    """the last view the renderer logged, or 'classic' before any switch"""
    found = "classic"
    for line in log_text(400000).splitlines():
        m = _last_view_line.search(line)
        if m:
            found = {"Classic (top down)": "classic", "Third person": "third", "First person": "first"}[m.group(1)]
    return found


def set_view(target, settle=2.0):
    """taps V until the renderer reports the wanted view (V cycles classic -> third -> first)"""
    for _ in range(4):
        now = current_view()
        if now == target:
            time.sleep(settle)
            return True
        tap("v", 0.25)
        time.sleep(0.6)
    say("set_view: could not reach", target, "from", current_view())
    return False


def counts():
    t = log_text()
    return dict(fault=t.count("FAULT"),
                waiting=t.count("view: waiting for the player"),
                lost=t.count("no longer holds a pedestrian"),
                hitch=t.count("hitch @"),
                frames=len(re.findall(r"frame times, avg/worst", t)))


def frame_summaries():
    out = []
    for line in log_text().splitlines():
        if "frame times, avg/worst" in line:
            out.append(line.split("] ", 1)[1])
    return out


def report(label, **extra):
    c = counts(); c.update(extra)
    say(f"CHECK {label}: " + " ".join(f"{k}={v}" for k, v in c.items()))
    return c


def start(name):
    say("scenario", name)
    D.start()
    s = D.wait_state(40)
    if not s:
        say("no player state"); sys.exit(1)
    D.calibrate_turn()
    return D.wait_state()


def words(s):
    return (f"state={s['state']} sub={s['sub']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} "
            f"{'DRIVING' if s['driving'] else 'on foot'} view={current_view()}")


def get_in_car(attempts=3):
    """F10 brings a parked car to scene_xy with the player at its door; Return gets in."""
    for attempt in range(1, attempts + 1):
        tap("F10", 0.3); time.sleep(1.2)
        s = D.wait_state(); say(f"after F10 ({attempt}): {words(s)} parked d={s['pd']:.2f}")
        tap("Return", 0.3)
        t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]:
                say("in the car:", words(s)); return s
            time.sleep(0.4)
    return None


def leave_car():
    tap("Return", 0.3)
    t0 = time.time()
    while time.time() - t0 < 6:
        s = D.wait_state()
        if not s["driving"] and s["state"] not in (4, 7):
            say("out of the car:", words(s)); return s
        time.sleep(0.4)
    return D.wait_state()


def turn_360(view, label):
    secs = 6.2832 / max(D.rate, 0.3)
    for q in range(4):
        hold("Left", secs / 4); time.sleep(0.3)
        shot(f"{label}_{view}_turn{q+1}")
