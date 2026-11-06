#!/usr/bin/env python3
"""Cuts the Remix clip and the classic-vs-first-person sheet from a run:
remix_sheet.py <out dir> <run seconds> <clip out.mp4> <sheet out.png>"""
import os, subprocess, sys
d, secs, clip, sheet = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
mp4 = os.path.join(d, "game.mp4"); end = os.stat(mp4).st_mtime; start = end - secs
m = {w: float(t) - start for t, w in (l.split() for l in open(os.path.join(d, "marks.txt")))}
a, b = m["classic"] - 2, m["done"]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.1f}", "-to", f"{b:.1f}", "-i", mp4,
                "-vf", "crop=1024:768:0:0", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", clip], check=True)
def frame(t, out): subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.1f}", "-i", mp4, "-vf", "crop=1024:768:0:0", "-frames:v", "1", out], check=True)
frame(m["classic"] + 4, "/tmp/rs_classic.png"); frame(m["first"] + 14, "/tmp/rs_first.png"); frame(m["third"] + 10, "/tmp/rs_third.png"); frame(m["first"] + 28, "/tmp/rs_first2.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "/tmp/rs_classic.png", "-i", "/tmp/rs_first.png", "-i", "/tmp/rs_third.png", "-i", "/tmp/rs_first2.png",
                "-filter_complex", "[0]drawtext=text='Classic top-down, RTX Remix path traced (L4)':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[a];"
                "[1]drawtext=text='First person, same street, RTX Remix path traced':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[b];"
                "[2]drawtext=text='Third person':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[c];"
                "[3]drawtext=text='First person, toward the street':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[d];"
                "[a][b][c][d]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0", sheet], check=True)
print("clip", round(b - a, 1), "s; marks", {k: round(v, 1) for k, v in m.items()})
