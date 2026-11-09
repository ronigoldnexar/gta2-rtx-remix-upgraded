#!/usr/bin/env python3
"""Before/after frame sheet of a feel_probe burst with the logged body angles under each frame.

    tools/body_motion_sheet.py <out.png> <burst> <frames,comma> <crop x,y,w,h> <run> [<run> ...]

One row per run (out/<run>/b_<burst>.mp4, numbered at 30 fps from the burst's start), one column
per frame; each tile is labelled with the run, the frame and the nearest `vehicle feel: player
car` roll / pitch from out/<run>/body_motion.json (tools/body_motion_telemetry.py first).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    out, burst, frames, crop = sys.argv[1], sys.argv[2], [int(f) for f in sys.argv[3].split(",")], [int(v) for v in sys.argv[4].split(",")]
    runs = [Path(r) for r in sys.argv[5:]]
    x, y, w, h = crop
    scale = 300 / w
    tw, th = int(w * scale), int(h * scale)
    sheet = Image.new("RGB", (tw * len(frames), (th + 18) * len(runs)), "black")
    for ri, run in enumerate(runs):
        tele = {}
        jf = run / "body_motion.json"
        if jf.exists():
            tele = {r["frame"]: r for r in json.loads(jf.read_text()).get(burst, {}).get("frames", [])}
        with tempfile.TemporaryDirectory() as td:
            sel = "+".join(f"eq(n\\,{f})" for f in frames)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(run / f"b_{burst}.mp4"), "-vf", f"select={sel},crop={w}:{h}:{x}:{y}",
                            "-vsync", "0", f"{td}/f_%03d.png"], check=True)
            for ci, f in enumerate(frames):
                p = Path(td) / f"f_{ci + 1:03d}.png"
                if not p.exists():
                    continue
                im = Image.open(p).resize((tw, th))
                sheet.paste(im, (ci * tw, ri * (th + 18) + 18))
                label = f"{run.name} f{f}"
                if tele:
                    k = min(tele, key=lambda t: abs(t - f))
                    if abs(k - f) <= 3:
                        label += f" p{tele[k]['pitch']:+.1f} r{tele[k]['roll']:+.1f}"
                ImageDraw.Draw(sheet).text((ci * tw + 3, ri * (th + 18) + 3), label, fill="yellow")
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main()
