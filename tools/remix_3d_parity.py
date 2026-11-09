#!/usr/bin/env python3
"""REMIX-3D-PARITY: the classic view against the 3D views under RTX Remix, from one run of
linux/docker/remix3d_take.py (keys_remix3d.sh, gamerun/remixbev_l4.sh or remix_l4.sh).

    python3 tools/remix_3d_parity.py <run dir> <run seconds> [out dir]

Writes into <out dir> (default <run dir>/r3d):
  frames/<label>.png         one frame per mark, cut from game.mp4 (the path-traced picture)
  side_by_side.png           per moment (hour x spot): classic | third | first | classic again
  switch_<moment>.png        the camera move in (M1..M5) and back out (N1..N5)
  report.md / report.json    the checks below

Checks (what "the same world moment" and "no discontinuity" mean here):
  1 objects    BEV-PARITY's switch check (tools/bev_parity.py check_switches): no logged car, ped or
               the player steps more than 0.6 blocks a frame within 3 s of any V press.
  2 lights     the Remix light set frame by frame (GTA2DX9_LOG_LIGHTS_EVERY=2): far-lamp count and
               fade weight through each switch, and the largest change in submitted lights between
               two logged frames in the switch window against the steady state before it.
  3 picture    mean brightness of every recorded frame (HUD corners masked) through each switch:
               the largest frame-to-frame step in the 2.5 s after V against the steady state before
               it, and black frames (mean < 4 of 255).
  4 classic    classic again (E) against classic before (A): same camera (game extent from the log),
               the share of terrain pixels that differ by more than 24 after the cycle.
Python with numpy and Pillow; ffmpeg on the PATH.
"""
import json, math, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bev_parity as BP   # noqa: E402  (log reader, object timeline, switch check)

LIGHTS = re.compile(r"remix lights @(\d+): submitted (\d+), tracked (\d+).*?far (\d+) x([\d.]+)")
SIZE = (1280, 720)
MOVE = (5, 11, 18, 27, 42)   # remix3d_take.py: rendered frames after V of the M/N marks


def marks(run):
    out = []
    for line in open(os.path.join(run, "marks.txt")):
        t, label = line.split(None, 1)
        out.append((float(t), label.strip()))
    return out


def video_start(run, secs):
    """wall time of the recording's first frame: the file's mtime (when the recorder stopped) minus
    its duration as ffprobe reads it; <run seconds> only if ffprobe cannot say (remix_frames.py's
    convention, which is wrong when the recorder was stopped before the session ended)"""
    mp4 = os.path.join(run, "game.mp4")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                       capture_output=True, text=True)
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        dur = float(secs)
    return os.stat(mp4).st_mtime - dur


def cut(mp4, at, path):
    if not os.path.exists(path):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", mp4, "-frames:v", "1", path],
                       check=False)
    return os.path.exists(path)


def luma_track(mp4, t0, t1, fps=15):
    """mean luma per recorded frame between t0 and t1 (seconds into the video), HUD corners masked"""
    w, h = 320, 180
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{t1 - t0:.3f}", "-i", mp4,
           "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h)
    if n == 0: return np.zeros(0), np.zeros(0)
    a = np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    m = np.ones((h, w), bool)
    m[: h // 3, : w // 4] = False          # the health bars
    m[: h // 5, w * 3 // 4:] = False       # money, lives
    m[h * 2 // 3:, : w // 4] = False       # the 3D views' minimap
    vals = a[:, m].mean(axis=1)
    return np.arange(n) / fps + max(0.0, t0), vals


def font(px):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f): return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def grid(rows, path, cw=480, title=None):
    """rows: [[(png or None, caption)]]"""
    F = font(max(12, cw // 34)); pad = 6; ch = round(cw * 9 / 16)
    cols = max(len(r) for r in rows); top = 34 if title else 0
    S = Image.new("RGB", (cols * (cw + pad) + pad, top + len(rows) * (ch + pad) + pad), (18, 18, 22)); d = ImageDraw.Draw(S)
    if title: d.text((pad + 4, 8), title, fill=(255, 255, 255), font=font(18))
    for r, row in enumerate(rows):
        for c, (p, cap) in enumerate(row):
            x = pad + c * (cw + pad); y = top + pad + r * (ch + pad)
            if p and os.path.exists(p):
                S.paste(Image.open(p).convert("RGB").resize((cw, ch), Image.LANCZOS), (x, y))
            if cap:
                b = d.textbbox((x + 6, y + 5), cap, font=F); d.rectangle((b[0] - 3, b[1] - 2, b[2] + 3, b[3] + 2), fill=(0, 0, 0))
                d.text((x + 6, y + 5), cap, fill=(255, 255, 255), font=F)
    S.save(path)
    return path


def main():
    run, secs = sys.argv[1], float(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(run, "r3d")
    fdir = os.path.join(out, "frames"); os.makedirs(fdir, exist_ok=True)
    mp4 = os.path.join(run, "game.mp4"); v0 = video_start(run, secs)
    mk = marks(run)
    ev = json.load(open(os.path.join(run, "bev_events.json"))) if os.path.exists(os.path.join(run, "bev_events.json")) else []
    lines = BP.read_log(run) if os.path.exists(os.path.join(run, "gta2dx9.log")) else []
    rep = {"run": run, "moments": {}, "switches": [], "lights": [], "picture": [], "classic_again": []}

    # frames at the marks (0.15 s after: the mark is written as the moment is reached)
    frames = {}
    for t, label in mk:
        m = re.match(r"(r3_[a-z]+_[a-z0-9]+)_([A-Z]\d?)_", label + "_")
        if not m: continue
        p = os.path.join(fdir, re.sub(r"[^A-Za-z0-9_.-]+", "_", label) + ".png")
        if cut(mp4, t - v0 + 0.15, p): frames.setdefault(m.group(1), {})[m.group(2)] = (p, t)
    moments = sorted(frames, key=lambda k: min(t for _, t in frames[k].values()))

    # side by side: the same moment in every view
    rows = []
    for mo in moments:
        f = frames[mo]
        g = lambda k: f.get(k, (None, 0))[0]
        rows.append([(g("A"), f"{mo[3:]}  classic"), (g("C"), "third person"), (g("D"), "first person"),
                     (g("E"), "classic again")])
    if rows: grid(rows, os.path.join(out, "side_by_side.png"), title=f"{os.path.basename(run)}: the same moment, path traced, in every view")
    for mo in moments:
        f = frames[mo]
        g = lambda k: f.get(k, (None, 0))[0]
        r1 = [(g("A"), "classic")] + [(g(f"M{i}"), f"V +{s} frames") for i, s in zip(range(1, 6), MOVE)] + [(g("C"), "third")]
        r2 = [(g("D"), "first")] + [(g(f"N{i}"), f"V +{s} frames") for i, s in zip(range(1, 6), MOVE)] + [(g("E"), "classic again")]
        grid([r1, r2], os.path.join(out, f"switch_{mo}.png"), cw=320, title=f"{mo}: classic -> third (top), first -> classic (bottom)")

    # 1 objects: BEV-PARITY's check
    if ev and lines:
        tl = BP.timeline(lines)
        evd = [dict(e, t=e["t"]) for e in ev]
        rep["switches"] = BP.check_switches(lines, tl, evd)

    # 2 lights through each switch
    lt = []
    for _, t, s in lines:
        m = LIGHTS.search(s)
        if m: lt.append((t, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), float(m.group(5))))
    for e in (x for x in ev if x["name"] == "switch"):
        ts = BP.day_seconds(e["t"])
        before = [x for x in lt if ts - 2.0 <= x[0] < ts]
        after = [x for x in lt if ts <= x[0] < ts + 3.0]
        def steps(seq):
            return [abs(b[2] - a[2]) / max(1, b[1] - a[1]) * 2 for a, b in zip(seq, seq[1:]) if b[1] > a[1]]
        far_after = [(round(x[0] - ts, 2), x[4], round(x[5], 2)) for x in after]
        # the step across the key press itself: the far lamps' summed weight (count x fade) in the
        # last logged frame before V and the first after it
        jump = (round(before[-1][4] * before[-1][5], 1), round(after[0][4] * after[0][5], 1)) if before and after else None
        rep["lights"].append(dict(moment=e.get("moment"), to=e.get("to"),
                                  submitted_before=int(np.median([x[2] for x in before])) if before else None,
                                  submitted_after=int(np.median([x[2] for x in after[-10:]])) if after else None,
                                  max_step_steady=round(max(steps(before), default=0), 1),
                                  max_step_switch=round(max(steps(after), default=0), 1),
                                  far_first=far_after[:3], far_ramp=[f for f in far_after if 0 < f[2] < 1][:6],
                                  far_ramp_frames=sum(1 for f in far_after if 0 < f[2] < 1),
                                  far_weight_across_key=jump,
                                  submitted_across_key=(before[-1][2], after[0][2]) if before and after else None))

    # 3 the picture through each switch
    for e in (x for x in ev if x["name"] == "switch"):
        tv = e["t"] - v0
        ts_, lum = luma_track(mp4, tv - 2.0, tv + 2.6)
        if len(lum) < 10: continue
        d = np.abs(np.diff(lum)); tt = ts_[1:] - tv
        steady = d[tt < -0.1]; sw = d[(tt >= -0.1) & (tt <= 2.5)]
        rep["picture"].append(dict(moment=e.get("moment"), to=e.get("to"),
                                   luma_before=round(float(lum[ts_ - tv < 0].mean()), 1),
                                   luma_after=round(float(lum[ts_ - tv > 2.0].mean()), 1),
                                   max_step_steady=round(float(steady.max()) if len(steady) else 0, 2),
                                   max_step_switch=round(float(sw.max()) if len(sw) else 0, 2),
                                   at=round(float(tt[(tt >= -0.1) & (tt <= 2.5)][sw.argmax()]), 2) if len(sw) else None,
                                   black_frames=int((lum < 4).sum())))

    # 4 classic again against classic before
    for mo in moments:
        f = frames[mo]
        if "A" not in f or "E" not in f: continue
        a = BP.load(f["A"][0]); b = BP.load(f["E"][0])
        ca = BP.camera_at(lines, BP.day_seconds(f["A"][1])); cb = BP.camera_at(lines, BP.day_seconds(f["E"][1]))
        h, w = a.shape[:2]
        mask = np.ones((h, w), bool); mask[: h // 3, : w // 4] = False; mask[: h // 5, w * 3 // 4:] = False
        diff = np.abs(a - b).max(axis=2)[mask]
        dx, dy, _ = BP.phase_shift(a, b)
        rep["classic_again"].append(dict(moment=mo, camera_same=ca == cb, camera_before=ca, camera_after=cb,
                                         shift_px=(round(float(dx), 1), round(float(dy), 1)),
                                         pixels_over_24=round(float((diff > 24).mean()) * 100, 2),
                                         mean_abs=round(float(diff.mean()), 2)))

    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1, default=str)
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(f"# REMIX-3D-PARITY report: {run}\n\n")
        f.write("## Objects through each V press (BEV-PARITY check 1)\n\n| moment | to | objects | max step | teleports | peds before/after |\n|---|---|---|---|---|---|\n")
        for s in rep["switches"]:
            f.write(f"| {s['moment']} | {s['to']} | {s['objects']} | {s['max_step']} | {len(s['teleports'])} | {s['live_peds_before']}/{s['live_peds_after']} |\n")
        f.write("\n## Remix lights through each V press\n\n| moment | to | submitted before -> after | far lamps x weight across the key press | lights across the key press | far lamps first frames (s, n, weight) | logged frames of fade |\n|---|---|---|---|---|---|---|\n")
        for s in rep["lights"]:
            f.write(f"| {s['moment']} | {s['to']} | {s['submitted_before']} -> {s['submitted_after']} | {s['far_weight_across_key']} | {s['submitted_across_key']} | {s['far_first']} | {s['far_ramp_frames']} |\n")
        f.write("\n## Picture brightness through each V press (mean luma 0-255, HUD masked, 15 fps)\n\n| moment | to | before | after | max step steady | max step in switch (at s) | black frames |\n|---|---|---|---|---|---|---|\n")
        for s in rep["picture"]:
            f.write(f"| {s['moment']} | {s['to']} | {s['luma_before']} | {s['luma_after']} | {s['max_step_steady']} | {s['max_step_switch']} ({s['at']}) | {s['black_frames']} |\n")
        f.write("\n## Classic again after the cycle\n\n| moment | same game camera | shift px | pixels > 24 | mean abs |\n|---|---|---|---|---|\n")
        for s in rep["classic_again"]:
            f.write(f"| {s['moment']} | {s['camera_same']} | {s['shift_px']} | {s['pixels_over_24']} % | {s['mean_abs']} |\n")
    print(open(os.path.join(out, "report.md")).read())


if __name__ == "__main__":
    main()
