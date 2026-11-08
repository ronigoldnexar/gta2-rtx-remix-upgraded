#!/usr/bin/env python3
"""Frames of a Remix run at its marks, and contact sheets from chosen frames.
  remix_frames.py dump  <run dir> <run seconds> <outdir> [label regex] [offset s]
      one PNG per mark (game.mp4 at mark time + offset): <outdir>/<nn>_<label>.png
  remix_frames.py sheet <out.png> <cols> <cell width> <png>=<caption> ...
      a captioned grid of the given frames
The recording starts when the container starts it (game.mp4's mtime minus the run
length), which is the clock marks.txt is matched against."""
import os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

def dump(run, secs, outdir, rx=".", offset=0.8):
    mp4 = os.path.join(run, "game.mp4"); start = os.stat(mp4).st_mtime - float(secs)
    os.makedirs(outdir, exist_ok=True)
    for i, line in enumerate(open(os.path.join(run, "marks.txt"))):
        t, label = line.split(None, 1); label = label.strip()
        if not re.search(rx, label): continue
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:60]
        out = os.path.join(outdir, f"{i:03d}_{name}.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{float(t) - start + float(offset):.2f}", "-i", mp4,
                        "-frames:v", "1", out], check=False)
        print(out)

def sheet(out, cols, cw, items):
    font = None
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f): font = ImageFont.truetype(f, max(12, cw // 40)); break
    font = font or ImageFont.load_default()
    cells = []
    for it in items:
        p, cap = it.split("=", 1) if "=" in it else (it, "")
        im = Image.open(p).convert("RGB"); im = im.resize((cw, round(im.height * cw / im.width)), Image.LANCZOS)
        cells.append((im, cap))
    ch = max(im.height for im, _ in cells); pad = 6; rows = (len(cells) + cols - 1) // cols
    S = Image.new("RGB", (cols * (cw + pad) + pad, rows * (ch + pad) + pad), (18, 18, 22)); d = ImageDraw.Draw(S)
    for k, (im, cap) in enumerate(cells):
        x = pad + (k % cols) * (cw + pad); y = pad + (k // cols) * (ch + pad)
        S.paste(im, (x, y))
        if cap:
            b = d.textbbox((x + 8, y + 6), cap, font=font); d.rectangle((b[0] - 4, b[1] - 3, b[2] + 4, b[3] + 3), fill=(0, 0, 0))
            d.text((x + 8, y + 6), cap, fill=(255, 255, 255), font=font)
    S.save(out); print(out, S.size)

if __name__ == "__main__":
    if sys.argv[1] == "dump": dump(*sys.argv[2:])
    else: sheet(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:])
