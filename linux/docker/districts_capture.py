#!/usr/bin/env python3
"""DISTRICTS-POC capture (inside a game container; keys_districts.sh). For each point of DK_POINTS (JSON from
tools/districts/frame_plan.py): a developer warp to the street in front of the building, then by day and by
night: the camera move from the classic view (a burst of frames), the third- and first-person views facing
the building, and fixed poses (GTA2DX9_REGRESS_CAM, dll/src/regress_cam.cpp) - each with the facade kit on and
off ([devtools] district_kit_show, polled live), so before/after are the same frame. Frames /out/dk_*.png,
one line per frame in /out/dk.jsonl."""
import json, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
import a3_lib as A

say = D.say
POINTS = json.loads(os.environ["DK_POINTS"])
CAM = os.environ.get("VREG_CAM", "/tmp/vreg_cam.txt")
W, H = os.environ.get("SCREEN_W", "1280"), os.environ.get("SCREEN_H", "720")
out = open("/out/dk.jsonl", "a")
T0 = time.time()


def grab(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", f"{W}x{H}", "-i", ":99", "-frames:v", "1", f"/out/dk_{name}.png"])


def burst(name, secs=2.0, fps=8):
    subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps), "-video_size", f"{W}x{H}", "-i", ":99",
                      "-t", str(secs), f"/out/dk_{name}_%02d.png"])


def move_in(name):
    """from the settled classic view into third person, frames through the whole move (ffmpeg warms up first)"""
    burst(name, 5.0, 6); time.sleep(1.2)
    T.mark(f"{name} V")
    for _ in range(3):
        D.tap("v", 0.25); time.sleep(0.5)
        if Q.current_view() != "classic": break
    say("move: view now", Q.current_view())
    time.sleep(3.6)


def face_building(p):
    """a standing ped's logged facing comes from his sprite and can be half a turn off, so turning on the spot is
    unreliable: walk from the warp point toward the wall (frame_plan's approach point); he ends facing it"""
    s = D.goto(p["approach"][0], p["approach"][1], tol=0.35, limit=12)
    say("faced:", T.words(s) if s else "no state")
    return s


def cam(line):
    with open(CAM + ".tmp", "w") as f: f.write(line + "\n")
    os.replace(CAM + ".tmp", CAM)


def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t): t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else: t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)


def ini_sec(section, key, val):
    """set key=val inside [section] only (several sections share key names: enabled=, ...)"""
    lines = open(T.INI, encoding="latin-1").read().split("\n")
    cur, done = None, False
    for i, l in enumerate(lines):
        m = re.match(r"^\[([^\]]+)\]", l)
        if m:
            if cur == section and not done:
                lines.insert(i, f"{key}={val}"); done = True; break
            cur = m.group(1).strip().lower()
            continue
        if cur == section and re.match(rf"^{key}=", l):
            lines[i] = f"{key}={val}" + ("\r" if l.endswith("\r") else ""); done = True; break
    open(T.INI, "w", encoding="latin-1").write("\n".join(lines))


def clock(tod):
    """day: the renderer's own fixed sun (the [weather] clock off, as shipped); night: the [weather] time of day on,
    dry and clear, the clock held at 22:30 (lamps, neon and lit windows on)"""
    if tod == "day":
        ini_sec("weather", "enabled", 0)
    else:
        for k, v in (("rain_percent", 0), ("cloud_percent", 0), ("fog_percent", 0), ("wet_percent", 0), ("time_of_day", 1),
                     ("hour_hhmm", 2230), ("clock_paused", 1), ("enabled", 1)):
            ini_sec("weather", k, v)
    time.sleep(3.0)


def kit(on):
    n0 = len(Q.log_text())
    ini_set("district_kit_show", 1 if on else 0)
    t = time.time()
    while time.time() - t < 4.0:
        if f"district_kit_show {1 if on else 0}" in Q.log_text()[n0:]: break
        time.sleep(0.1)
    time.sleep(0.5)


def record(name, **kw):
    s = D.state()
    rec = dict(shot=name, t=round(time.time() - T0, 1), view=Q.current_view(), at=[round(s["x"], 2), round(s["y"], 2), round(s["z"], 2)] if s else None, **kw)
    out.write(json.dumps(rec) + "\n"); out.flush()


def ab(name):
    kit(True); grab(f"{name}_on"); record(f"{name}_on")
    kit(False); grab(f"{name}_off"); record(f"{name}_off")
    kit(True)


def pose_line(p, pose):
    e, a = pose["eye"], pose["at"]
    return "cam " + " ".join(f"{v:.3f}" for v in (p["x"] + e[0], p["y"] + e[1], p["z"] + e[2], p["x"] + a[0], p["y"] + a[1], p["z"] + a[2])) + f" {pose.get('fov', 60)}"


def main():
  cam("off")
  D.start()
  s = D.wait_state(40)
  say("start:", T.words(s) if s else "no state")
  for p in POINTS:
      for tod, hhmm in (("day", 1230), ("night", 2230)):
          clock(tod)
          T.warp(p["x"], p["y"], int(p["z"]), why=f"districts {p['name']}")
          time.sleep(2.0)
          Q.set_view("classic", settle=1.5)
          kit(True)
          grab(f"{p['name']}_{tod}_classic_on"); record(f"{p['name']}_{tod}_classic_on")
          kit(False); grab(f"{p['name']}_{tod}_classic_off"); record(f"{p['name']}_{tod}_classic_off"); kit(True)
          # the move from the classic view into third person, kit on: a burst through the 1.4 s move
          move_in(f"{p['name']}_{tod}_move")
          Q.set_view("third", settle=1.0)
          face_building(p); time.sleep(1.5)
          ab(f"{p['name']}_{tod}_third")
          Q.set_view("first", settle=1.5)
          ab(f"{p['name']}_{tod}_first")
          Q.set_view("third", settle=1.5)
          for pose in p["poses"]:
              n0 = len(Q.log_text())
              cam(pose_line(p, pose)); time.sleep(2.0)
              ab(f"{p['name']}_{tod}_{pose['name']}")
          if os.environ.get("DK_PERF") and tod == "day":
              # frame-time A/B: the same pose held with the kit on, then off, twice (the frame log averages 256 frames)
              pose = [q for q in p["poses"] if q["name"] == os.environ["DK_PERF"]][0]
              cam(pose_line(p, pose)); time.sleep(2.0)
              for rnd in range(2):
                  for on in (True, False):
                      kit(on); T.mark(f"perf {'on' if on else 'off'} start"); time.sleep(20.0); T.mark(f"perf {'on' if on else 'off'} end")
              kit(True)
          cam("off"); time.sleep(0.5)
          # back to classic: the move out, kit on (it must fade, not pop)
          Q.set_view("first", settle=1.0)
          burst(f"{p['name']}_{tod}_moveout", 5.0, 6); time.sleep(1.2); D.tap("v", 0.25); time.sleep(4.2)
          Q.set_view("classic", settle=1.0)
  say("districts capture: done in", round(time.time() - T0), "s")
  open("/out/.dk_done", "w").write("ok\n")


if __name__ == "__main__":
    main()
