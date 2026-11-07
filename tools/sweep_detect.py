#!/usr/bin/env python3
"""Looks through a city sweep's frames and logs for defects, without a human.

    sweep_detect.py <out dir with sweep_<district>_<i> folders> <district> <docs md> <sheet png>

Frames come from gamerun/sweep.py run with the magenta clear and the sky off,
so anything the renderer leaves undrawn is magenta (255,0,255). Detectors,
each scoring a frame 0..1:
  hole      magenta below the horizon band in a street view: a hole in the world
            (above the band magenta is the sky and expected)
  black     near-black frame: nothing presented
  flat      a large low-variance region that is not magenta: an untextured face,
            or the camera inside a wall, a prop or a car body
  miss      the warp did not land (no frames)
Per point the renderer's log slice is counted for FAULT, 'waiting for the
player' and hitch lines. The report is a ranked table; the sheet shows the
worst 20 frames with their labels.
"""
import glob, json, os, sys
import numpy as np
from PIL import Image, ImageDraw

HUD_TOP = 0.11        # the HUD rows at the top are ignored
HORIZON = {"t": 0.40, "f": 0.52}   # fraction of the height per view: below it the street view must be solid
                                   # (the chase camera looks down, the eye is level)
VIEW_W, VIEW_H = 1280, 720


def load(path):
    im = Image.open(path).convert("RGB")
    if im.size != (VIEW_W, VIEW_H): im = im.resize((VIEW_W, VIEW_H))
    return np.asarray(im).astype(np.int16)


def magenta_mask(a):
    return (a[..., 0] > 200) & (a[..., 1] < 70) & (a[..., 2] > 200)


def detect(a, view):
    h = a.shape[0]
    top = int(h * HUD_TOP); hz = int(h * HORIZON.get(view, 0.45))
    body = a[top:]
    mag = magenta_mask(body)
    scores = {}
    if view in ("t", "f"):
        below = mag[hz - top:]
        scores["hole"] = float(below.mean())
    else:
        scores["hole"] = float(mag.mean())      # classic: any magenta is a hole
    lum = body.mean(axis=2)
    scores["black"] = float((lum < 12).mean())
    # flat: 32 px cells with a tiny spread, not magenta, grouped: share of the frame
    cs = 32
    ch, cw = body.shape[0] // cs, body.shape[1] // cs
    flat = 0
    for cy in range(ch):
        for cx in range(cw):
            cell = body[cy * cs:(cy + 1) * cs, cx * cs:(cx + 1) * cs]
            if magenta_mask(cell).mean() > 0.2: continue
            if cell.std(axis=(0, 1)).max() < 2.0 and 60 < cell.mean() < 235: flat += 1
    scores["flat"] = flat / float(ch * cw)
    return scores


def log_counts(lines):
    t = "\n".join(lines)
    return dict(fault=t.count("FAULT"), waiting=t.count("view: waiting for the player"), hitch=t.count("hitch @"))


def main():
    out_dir, district, md_path, sheet_path = sys.argv[1:5]
    runs = sorted(glob.glob(os.path.join(out_dir, f"sweep_{district}_*")))
    runs = [r for r in runs if os.path.isdir(r)]
    rows = []           # (score, kind, cell, view, frame, scores, logc)
    points = 0; landed = 0; frames = 0
    per_point = []
    # one record per point across every run (first pass and retries): a landed
    # one wins over a miss, so a point retried later counts once
    recs = {}; logs = {}
    for run in runs:
        jl = os.path.join(run, "sweep.jsonl")
        if not os.path.exists(jl): continue
        logs[run] = open(os.path.join(run, "gta2dx9.log"), encoding="latin-1", errors="replace").read().splitlines() \
            if os.path.exists(os.path.join(run, "gta2dx9.log")) else []
        for line in open(jl):
            rec = json.loads(line); rec["run"] = run
            if rec["name"] not in recs or (rec.get("landed") and not recs[rec["name"]].get("landed")):
                recs[rec["name"]] = rec
    if True:
        for rec in recs.values():
            run = rec["run"]; log = logs[run]
            points += 1
            l0, l1 = rec.get("log_lines", [0, 0])
            logc = log_counts(log[l0:l1])
            name = rec["name"]
            if not rec.get("landed"):
                rows.append((0.5, "miss", name, "-", os.path.join(run, f"t_{name}_miss.png"), {}, logc)); continue
            landed += 1
            worst = 0.0
            for fp in sorted(glob.glob(os.path.join(run, f"t_{name}_[tf]?.png"))):
                view = os.path.basename(fp)[-6]
                sc = detect(load(fp), view); frames += 1
                for det, val in sc.items():
                    thresh = {"hole": 0.004, "black": 0.6, "flat": 0.25}[det]
                    if val >= thresh:
                        rows.append((min(1.0, val / (thresh * 8)), det, name, os.path.basename(fp)[-6:-4], fp, sc, logc))
                        worst = max(worst, val / (thresh * 8))
            if logc["fault"] or logc["waiting"]:
                rows.append((1.0 if logc["fault"] else 0.6, "log", name, "-", "", {}, logc))
            per_point.append((name, worst, logc))
    rows.sort(key=lambda r: -r[0])
    # one row per (kind, cell): the worst frame
    seen = set(); ranked = []
    for r in rows:
        key = (r[1], r[2])
        if key in seen: continue
        seen.add(key); ranked.append(r)
    counts = {}
    for r in ranked: counts[r[1]] = counts.get(r[1], 0) + 1
    with open(md_path, "w") as f:
        f.write(f"# City sweep: {district}\n\n")
        f.write(f"Runs: {len(runs)}; points visited {points}, landed {landed}, frames scored {frames}. "
                f"Generated by `tools/sweep_detect.py` from `gamerun/sweep.py` runs (magenta clear, sky off).\n\n")
        f.write("Defects by detector (one row per cell): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + "\n\n")
        f.write("| rank | cell | view | detector | score | hole | black | flat | fault/wait/hitch | frame |\n|---|---|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(ranked[:60], 1):
            sc = r[5]
            f.write(f"| {i} | {r[2]} | {r[3]} | {r[1]} | {r[0]:.2f} | {sc.get('hole', 0):.3f} | {sc.get('black', 0):.2f} | "
                    f"{sc.get('flat', 0):.2f} | {r[6]['fault']}/{r[6]['waiting']}/{r[6]['hitch']} | `{os.path.relpath(r[4]) if r[4] else ''}` |\n")
        f.write("\nThresholds: hole ≥ 0.4 % of the below-horizon pixels magenta; black ≥ 60 % of pixels under 12/255; "
                "flat ≥ 25 % of 32 px cells with a spread under 2/255 (untextured face or the camera inside something).\n")
    # the sheet
    pick = [r for r in ranked if r[4] and os.path.exists(r[4])][:20]
    cols = 5; tw, th = 480, 270
    sheet = Image.new("RGB", (cols * tw, ((len(pick) + cols - 1) // cols) * (th + 18) or (th + 18)), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    for i, r in enumerate(pick):
        im = Image.open(r[4]).convert("RGB").resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        sheet.paste(im, (x, y + 18))
        dr.text((x + 4, y + 3), f"{i + 1}. {r[2]} {r[3]} {r[1]} {r[0]:.2f}", fill=(255, 255, 160))
    sheet.save(sheet_path)
    print(district, "points", points, "landed", landed, "frames", frames, "defect rows", len(ranked), counts)


if __name__ == "__main__":
    main()
