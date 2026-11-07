#!/usr/bin/env python3
"""The day/night sheet of the Remix master demo:
remix_daynight_sheet.py <run dir> <run seconds> <sheet out.png> [clip out.mp4]
Rows: classic | third person | first person | at the wheel, columns: the earliest
(day/dusk) and the latest (night) frame of each, from the marks final_demo2.py writes."""
import os, subprocess, sys
d, secs, sheet = sys.argv[1], int(sys.argv[2]), sys.argv[3]
clip = sys.argv[4] if len(sys.argv) > 4 else None
mp4 = os.path.join(d, "game.mp4"); end = os.stat(mp4).st_mtime; start = end - secs
marks = [(float(t) - start, w) for t, w in (l.split() for l in open(os.path.join(d, "marks.txt")))]
def at(label, nth=0, offset=4):
    hits = [t for t, w in marks if w == label]
    return hits[nth] + offset if len(hits) > nth else None
def frame(t, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.1f}", "-i", mp4, "-frames:v", "1", out], check=True)
labels = [w for _, w in marks]
print("marks:", [(w, round(t, 1)) for t, w in marks])
# first/last occurrence of each view mark
wanted = [("classic", "on_pavement", "drive_classic"), ("third person", "to_third", "foot_third"), ("first person", "to_first", "drive_first")]
cells = []
for title, early, late in wanted:
    e = at(early, 0, 6); l = at(late, 0, 6) if late in labels else at(early, -1, 6)
    cells.append((title, e, l))
tiles = []
for i, (title, e, l) in enumerate(cells):
    for j, t in enumerate((e, l)):
        out = f"/tmp/dn_{i}_{j}.png"
        if t is None: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720", "-frames:v", "1", out], check=True)
        else: frame(t, out)
        tiles.append((out, f"{title}, {'early' if j == 0 else 'late'} in the take"))
args = ["ffmpeg", "-y", "-loglevel", "error"]
for p, _ in tiles: args += ["-i", p]
fc = "".join(f"[{k}]drawtext=text='{t}':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[t{k}];" for k, (_, t) in enumerate(tiles))
fc += "".join(f"[t{k}]" for k in range(len(tiles))) + f"xstack=inputs={len(tiles)}:layout=0_0|w0_0|0_h0|w0_h0|0_h0+h2|w0_h0+h2"
subprocess.run(args + ["-filter_complex", fc, sheet], check=True)
if clip:
    a = at("level", 0, -1) or 0; b = marks[-1][0]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.1f}", "-to", f"{b:.1f}", "-i", mp4, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", clip], check=True)
    print("clip", round(b - a, 1), "s")
