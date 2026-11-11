#!/usr/bin/env python3
"""VEHICLE-ART-28: kit glass pane medians from a VA6_SETS A/B run (keys_va6_own.sh): the glass = the pixels the lift changes
between the first two sets.  glass_measure.py <run dir> g0,g1[,g2] side,front34 050,001 ..."""
import sys; import numpy as np; from PIL import Image
d=sys.argv[1]; sets=sys.argv[2].split(','); poses=sys.argv[3].split(','); models=sys.argv[4].split(',')
for p in poses:
  for m in models:
    A=[np.asarray(Image.open(f'{d}/own_{p}_{m}_{s}.png').convert('RGB')).astype(float) for s in sets]
    diff=np.abs(A[1]-A[0]).sum(-1); mask=diff>12; mask[:,:200]=False; mask[:60]=False   # glass = what the lift changed (HUD out)
    out=[f'{p} {m} glass px {mask.sum():6d}']
    for s,a in zip(sets,A):
        out.append(f'{s} {np.median(a[mask],0).round().astype(int).tolist() if mask.any() else None}')
    print('  '.join(out))
