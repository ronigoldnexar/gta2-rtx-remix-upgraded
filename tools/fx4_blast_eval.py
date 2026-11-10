#!/usr/bin/env python3
"""FIX-FX-4: the worst flash share of a forced blast's frames (runs of linux/docker/keys_fx4_blast.sh).
Shot qa_d_blast_NNN.png was taken NNN/10 s after the runner wrote force_blast; the trigger line is logged at the
first re-read after that (within 0.5 s, taken as 0.25 s), so a shot's log time is trigger - 0.25 + NNN/10. Frames
0..1.6 s after the 'explosions: blast' line are scored: the share of the picture (HUD rows cut) that is flash
(luminance > 200, or hot orange R > 220 and G > 150), as tools/fx3_blast_eval.py does.
Usage: fx4_blast_eval.py <run dir>..."""
import glob, os, re, sys
from PIL import Image
import numpy as np

def flash(f):
    a = np.asarray(Image.open(f).convert('RGB')).astype(float)[90:630]
    lum = a.mean(2)
    return float(((lum > 200) | ((a[:, :, 0] > 220) & (a[:, :, 1] > 150))).mean())

def secs(t):
    h, m, s = t.split(':'); return int(h) * 3600 + int(m) * 60 + float(s)

for r in sys.argv[1:]:
    log = open(r + '/gta2dx9.log', errors='replace').read() if os.path.exists(r + '/gta2dx9.log') else ''
    trig = re.search(r'\[(\d\d:\d\d:\d\d\.\d+)\] devtools: force_blast \d+: car .*?, ([\d.]+) blocks from the player', log)
    bl = re.search(r'\[(\d\d:\d\d:\d\d\.\d+)\] explosions: blast', log)
    if not trig or not bl:
        print(r, 'no trigger' if not trig else 'no blast'); continue
    t0 = secs(trig.group(1)) - 0.25; tb = secs(bl.group(1))
    vals = []
    for f in sorted(glob.glob(r + '/qa_d_blast_*.png')):
        n = int(re.search(r'_(\d+)\.png$', f).group(1))
        dt = t0 + n / 10.0 - tb
        if -0.1 <= dt <= 1.6: vals.append((os.path.basename(f), dt, flash(f)))
    if not vals: print(r, 'no frames in 0-1.6 s'); continue
    w = max(vals, key=lambda v: v[2])
    print('%s | car %s blocks off | %d frames in 0-1.6 s | worst %s (+%.1f s) flash %.2f | not flash %.0f %%' % (
        os.path.basename(r), trig.group(2), len(vals), w[0], w[1], w[2], 100 * (1 - w[2])))
