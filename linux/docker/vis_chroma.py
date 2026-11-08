#!/usr/bin/env python3
"""VISUALS-PLAIN acceptance: mean chroma (max(R,G,B) - min(R,G,B), 0..255) of every half second of
a run's game.mp4, below the HUD band, so a palette that greys out over a drive shows as a falling
line.   vis_chroma.py <run dir> [<run dir> ...]  -> <run dir>/chroma.tsv, and a summary line each."""
import os, subprocess, sys
import numpy as np
for run in sys.argv[1:]:
    mp4 = os.path.join(run, "game.mp4")
    raw = subprocess.run(["nice", "-n", "15", "ffmpeg", "-loglevel", "error", "-i", mp4, "-vf", "fps=2,scale=320:180",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 180, 320, 3)[:, 30:, :, :].astype(np.int16)
    ch = (fr.max(axis=3) - fr.min(axis=3)).mean(axis=(1, 2))
    with open(os.path.join(run, "chroma.tsv"), "w") as f:
        f.write("t_s\tchroma\n")
        for i, c in enumerate(ch): f.write(f"{i / 2:.1f}\t{c:.2f}\n")
    q = np.percentile(ch, [5, 50, 95]) if len(ch) else [0, 0, 0]
    print(f"{run}: {len(ch)} samples, chroma p5 {q[0]:.1f} p50 {q[1]:.1f} p95 {q[2]:.1f}, first 10 s {ch[:20].mean():.1f}, last 10 s {ch[-20:].mean():.1f}")
