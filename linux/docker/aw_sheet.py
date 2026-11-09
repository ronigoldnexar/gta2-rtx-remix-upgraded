#!/usr/bin/env python3
"""ANIM-WEAPONS contact sheets from an aw_rig_probe run.
  aw_sheet.py <run dir> stills <out.png> [crop]      every aw_*_y*.png still, labelled
  aw_sheet.py <run dir> burst <label> <out.png> [n]  n frames (default 10) evenly through b_<label>.mp4
crop: x,y,w,h of the 1280x720 frame (default the middle 640x500: the figure)."""
import os, subprocess, sys, glob
from PIL import Image, ImageDraw

def crop_box(arg):
    return tuple(int(v) for v in arg.split(",")) if arg else (380, 120, 520, 520)

def tile(images, labels, out, cols):
    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 18)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (im, lb) in enumerate(zip(images, labels)):
        x, y = (i % cols) * w, (i // cols) * (h + 18)
        sheet.paste(im, (x, y + 18))
        d.text((x + 4, y + 3), lb, fill=(255, 255, 0))
    sheet.save(out)
    print(out, sheet.size)

run, kind = sys.argv[1], sys.argv[2]
if kind == "stills":
    out = sys.argv[3]; box = crop_box(sys.argv[4] if len(sys.argv) > 4 else "")
    files = sorted(glob.glob(os.path.join(run, "qa_aw_*_y*.png")), key=os.path.getmtime)
    ims = [Image.open(f).convert("RGB").crop((box[0], box[1], box[0] + box[2], box[1] + box[3])) for f in files]
    tile(ims, [os.path.basename(f)[6:-4] for f in files], out, 4)
else:
    label, out = sys.argv[3], sys.argv[4]
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 10
    box = crop_box(sys.argv[6] if len(sys.argv) > 6 else "")
    mp4 = os.path.join(run, f"b_{label}.mp4")
    tmp = f"/tmp/aw_frames_{os.getpid()}"
    os.makedirs(tmp, exist_ok=True)
    subprocess.run(["nice", "-n", "15", "ffmpeg", "-loglevel", "error", "-y", "-i", mp4, f"{tmp}/f_%03d.png"], check=True)
    frames = sorted(glob.glob(f"{tmp}/f_*.png"))
    pick = [frames[int(i * (len(frames) - 1) / max(1, n - 1))] for i in range(n)] if frames else []
    ims = [Image.open(f).convert("RGB").crop((box[0], box[1], box[0] + box[2], box[1] + box[3])) for f in pick]
    tile(ims, [f"{label} {os.path.basename(f)[2:5]}" for f in pick], out, min(n, 5))
    for f in frames: os.unlink(f)
    os.rmdir(tmp)
