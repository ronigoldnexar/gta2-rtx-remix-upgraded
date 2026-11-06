#!/usr/bin/env python3
"""Material-layer sheet: the same three views from three Remix runs that used
the same key script (marks classic/third/first), columns = runs.
remix_mat_sheet.py <sheet out.png> <label>=<run dir>:<run seconds> ..."""
import os, subprocess, sys
sheet, runs = sys.argv[1], [a.split("=", 1) for a in sys.argv[2:]]
OFFS = [("third", -1.5, "classic top-down"), ("third", 10, "third person"), ("first", 7, "first person")]
tiles, n = [], 0
for label, spec in runs:
    d, secs = spec.rsplit(":", 1); mp4 = os.path.join(d, "game.mp4")
    start = os.stat(mp4).st_mtime - int(secs)
    m = {w: float(t) - start for t, w in (l.split() for l in open(os.path.join(d, "marks.txt")))}
    for mark, off, view in OFFS:
        out = f"/tmp/rms_{n}.png"; n += 1
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{m[mark] + off:.1f}", "-i", mp4, "-frames:v", "1", out], check=True)
        tiles.append((out, f"{label}: {view}"))
cols = len(runs); rows = len(OFFS)
inputs = sum((["-i", t[0]] for t in tiles), [])
fc = "".join(f"[{i}]scale=640:-1,drawtext=text='{lab}':x=8:y=8:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6[t{i}];" for i, (_, lab) in enumerate(tiles))
# tile index = column * rows + row; lay out column-major so each run is a column
layout = "|".join(f"{'w0' if c else '0'}{'+w0' * (c - 1) if c > 1 else ''}_{'h0' if r else '0'}{'+h0' * (r - 1) if r > 1 else ''}" for c in range(cols) for r in range(rows))
fc += "".join(f"[t{c * rows + r}]" for c in range(cols) for r in range(rows)) + f"xstack=inputs={cols * rows}:layout={layout}"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, sheet], check=True)
print("sheet", sheet, len(tiles), "frames")
