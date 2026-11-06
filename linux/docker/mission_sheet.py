#!/usr/bin/env python3
"""Contact sheet of a mission run: one frame per mark (host side).
   mission_sheet.py <run dir> <secs recorded> <out.png>"""
import os, subprocess, sys
run, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
end = os.stat(f"{run}/game.mp4").st_mtime; start = end - secs
marks = [l.split(None, 1) for l in open(f"{run}/marks.txt")]
tiles = []
for i, (t, label) in enumerate(marks):
    off = max(0.0, float(t) - start + 1.5)
    png = f"{run}/mark_{i:02d}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{off:.1f}", "-i", f"{run}/game.mp4", "-frames:v", "1",
                    "-vf", f"scale=640:-1,drawtext=text='{label.strip().replace(chr(39),'').replace(':','')}':x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6", png])
    if os.path.exists(png): tiles.append(png)
cols = 4; rows = (len(tiles) + cols - 1) // cols
subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + sum([["-i", p] for p in tiles], []) +
               ["-filter_complex", f"{''.join(f'[{i}:v]' for i in range(len(tiles)))}xstack=inputs={len(tiles)}:layout=" +
                "|".join(f"{(i%cols)*640}_{(i//cols)*360}" for i in range(len(tiles))) + ":fill=black", out])
print(out, len(tiles), "frames")
