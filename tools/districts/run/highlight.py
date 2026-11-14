#!/usr/bin/env python3
"""highlight.py <run dir> <out.mp4> [seconds] [segments]: a highlight cut of a round-5 city drive: equal pieces from
the first legs into differently styled districts (marks "leg ... to <district> (<row>: <name>)"), each labelled with
its district and row, H.264, faststart. The video's start is placed from recording.txt (its length) and the drive's
end mark (the run ends a 3 s tail after it)."""
import os, re, subprocess, sys
run, out = sys.argv[1:3]
total = float(sys.argv[3]) if len(sys.argv) > 3 else 75.0
nseg = int(sys.argv[4]) if len(sys.argv) > 4 else 5
marks = [l.split(" ", 1) for l in open(os.path.join(run, "marks.txt")).read().splitlines() if " " in l]
dur = float(re.search(r"game.mp4 ([0-9.]+) s", open(os.path.join(run, "recording.txt")).read()).group(1))
end = [float(t) for t, w in marks if w.startswith("drive end") or w.startswith("MARK drive end")]
end = end[-1] if end else float(marks[-1][0])
t0 = end + 3.5 - dur
legs, seen = [], set()
for t, w in marks:
    m = re.match(r"leg \d+ to (\S+) \(([^:]+): (.*)\)", w)
    if m and m.group(2) not in seen:
        seen.add(m.group(2)); legs.append((float(t) - t0 + 4.0, m.group(1), m.group(2), m.group(3)))
legs = legs[:nseg]
seg = total / max(1, len(legs))
font = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf") if os.path.exists(f)), None)
parts = []
for k, (st, key, row, name) in enumerate(legs):
    st = max(0.0, min(st, dur - seg))
    p = f"/tmp/hl_{os.getpid()}_{k}.mp4"
    label = f"{name} - {row}".replace(":", " ").replace("'", "")
    vf = f"drawtext=fontfile={font}:text='{label}':x=20:y=h-50:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.5" if font else "null"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{st:.2f}", "-i", os.path.join(run, "game.mp4"), "-t", f"{seg:.2f}",
                    "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", p], check=True)
    parts.append(p)
lst = f"/tmp/hl_{os.getpid()}.txt"
open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out], check=True)
for p in parts + [lst]: os.remove(p)
print(out, [(round(l[0], 1), l[2]) for l in legs])
