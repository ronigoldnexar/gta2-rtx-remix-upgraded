#!/usr/bin/env python3
"""BEV parity runner (inside the game container). One session, three parts:

 1. Switch moments: the player stands still and the views are cycled classic -> third
    -> first -> classic. A frame of each, plus one taken 0.3 s after the switch to third
    person, while the (lengthened) camera move is still at the classic camera: the 3D
    view's content drawn from the top-down camera. The log's player/cars/peds lines
    (every 2 frames) give every object's position at each frame's time.
 2. Same input, every view: the same walk (Up, a turn, Up) in classic, third and first
    person with the game's own keys (GTA2_DIRECT_KEYS=1), for per-frame speed and turn.
 3. Memory: bev_mem.py diffs the live gta2.exe code against the file on disk in each
    view, and reads the view rectangle the game spawns and culls from.

Events (with the log offset at each) go to /out/bev_events.json for tools/bev_parity.py.
Env: BEV_TRANSITION (seconds the camera move takes in this run, from the settings file),
BEV_SCENE_KEY (the run's [devtools] scene_key: brings a parked car and the player to scene_xy
before anything is measured, for a road with traffic and a car in the frame)."""
import json, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D

LOG, OUT = D.LOG, "/out"
T = float(os.environ.get("BEV_TRANSITION", "12"))
EVENTS = []
say = D.say


def mark(name, **kw):
    try:
        size = os.path.getsize(LOG)
    except OSError:
        size = -1
    EVENTS.append(dict(name=name, t=time.time(), log=size, **kw))
    with open(f"{OUT}/bev_events.json", "w") as f:
        json.dump(dict(transition=T, events=EVENTS), f, indent=1)


def shot(name, **kw):
    path = f"{OUT}/bev_{name}.png"
    kw["t_before"] = time.time()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720",
                    "-i", ":99", "-frames:v", "1", path])
    mark("shot", label=name, **kw)
    say("shot", name)


def mem(label):
    r = subprocess.run(["python3", "/work/bev_mem.py", label, OUT], capture_output=True, text=True)
    say((r.stdout or r.stderr).strip()[-300:])
    mark("mem", label=label)


def tap(key, t=0.25):
    D.xdo("keydown", key); time.sleep(t); D.xdo("keyup", key)


def tail(n=200000):
    with open(LOG, "rb") as f:
        f.seek(0, 2); s = f.tell(); f.seek(max(0, s - n)); return f.read().decode("latin-1")


VIEW = {"now": "classic", "off": 0}
VIEW_LINE = re.compile(r"\] view: (Classic \(top down\)|Third person|First person)\r?\n")


def current_view():
    """the last view the renderer logged, read forward through the whole log (a tail window
    loses the line when the per-frame object lines are on: run bev_parity2)"""
    try:
        with open(LOG, "rb") as f:
            f.seek(VIEW["off"]); data = f.read().decode("latin-1")
    except OSError:
        return VIEW["now"]
    cut = data.rfind("\n") + 1
    for m in VIEW_LINE.finditer(data[:cut]):
        VIEW["now"] = {"Classic (top down)": "classic", "Third person": "third", "First person": "first"}[m.group(1)]
    VIEW["off"] += len(data[:cut].encode("latin-1"))
    return VIEW["now"]


def to_view(target):
    for _ in range(4):
        if current_view() == target:
            return True
        tap("v"); time.sleep(0.6)
    ok = current_view() == target
    mark("to_view", target=target, ok=ok)
    return ok


def switch_moment(tag):
    """GTA2 has no pause reachable by key here (p, Pause and Escape all left the world
    running, run bev_parity1), so 'the same moment' is the frame before the switch and
    the frame 0.3 s after it, with every object compared at its own logged position for
    each frame's time. The player stands still throughout (no key held)."""
    to_view("classic")
    time.sleep(3.0)   # a camera extent line (every 64 frames) and a still classic camera
    mark("moment_start", moment=tag)
    shot(f"{tag}0_classic", view="classic")
    mark("switch", moment=tag, to="third")
    tap("v", 0.1); time.sleep(0.2)
    shot(f"{tag}1_3d_at_classic_camera", view="third_from_classic")
    mem(f"{tag}_switching")   # just after the switch; after the pair: the probe takes ~0.5 s and the traffic moves on (run bev_parity3)
    time.sleep(T + 1.5)
    shot(f"{tag}2_third", view="third"); mem(f"{tag}_third")
    mark("switch", moment=tag, to="first")
    tap("v"); time.sleep(T + 1.5)
    shot(f"{tag}3_first", view="first"); mem(f"{tag}_first")
    mark("switch", moment=tag, to="classic")
    tap("v"); time.sleep(T + 3.0)
    shot(f"{tag}4_classic_again", view="classic"); mem(f"{tag}_classic_again")
    mark("moment_end", moment=tag, view=current_view())


def walk(view):
    """the same keys in each view: Up 2 s, Left 0.5 s, Up 1.5 s, Right 0.5 s"""
    mark("walk_start", view=view, logged_view=current_view())
    for key, secs in (("Up", 2.0), ("Left", 0.5), ("Up", 1.5), ("Right", 0.5)):
        mark("key_down", key=key, view=view)
        D.hold(key, secs)
        mark("key_up", key=key, view=view)
        time.sleep(0.6)
    mark("walk_end", view=view)


def main():
    mark("start", view=current_view())
    time.sleep(2)
    scene = os.environ.get("BEV_SCENE_KEY")   # [devtools] scene_key: a parked car to the road at scene_xy, before measuring
    if scene:
        tap(scene); time.sleep(3); mark("scene_warp", key=scene)
    time.sleep(1)
    mem("start_classic")
    switch_moment("A")
    time.sleep(1.5)
    walk("classic")
    to_view("third"); time.sleep(T + 1.5); mem("walk_third")
    walk("third")
    to_view("first"); time.sleep(T + 1.5)
    walk("first")
    to_view("classic"); time.sleep(T + 2.5)
    walk("classic2")
    switch_moment("B")
    mark("end")
    say("bev_parity: done")


if __name__ == "__main__":
    main()
