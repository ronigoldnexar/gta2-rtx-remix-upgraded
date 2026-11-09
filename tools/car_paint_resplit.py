#!/usr/bin/env python3
"""FIX-CAR-IDENTITY (pm17 / pf18 / pm22, rank 2g): re-split a generated car's baked texture into paint and the rest,
by the body's own colour, and normalise the paint to a neutral shading.

Why: tools/import_assets.py split each image-to-3D car's texture by a colour distance to the manifest's paint_rgb
(the default sprite's paint). The bodies the generator made are rarely that colour (the 082 Jagular's body is teal,
its paint_rgb orange), so the paint half caught a few panels and the body stayed in the untinted half: the 3D car
kept the generator's colour whatever the sprite showed (orange in classic, teal in third person). The identity
record's tint (identity.cpp DeriveVehicle: live / ModelOwnPaint) can only recolour the paint half.

What: for every pair <tex>.tga / <tex>_paint.tga of a generated car (an authored body's atlas, fully opaque paint,
is left alone):
  1. the body's dominant hue: the peak of the hue histogram of the saturated, lit texels of both halves;
  2. the paint: the texels of either half within --hue-tol of that hue, coloured and not black (glass, tyres,
     chrome, lamps and the unused atlas stay in the rest; an old paint texel of another hue goes back to it).
     A body with too few coloured texels (white, silver, grey, black) keeps its split;
  3. the paint texels are made neutral: their luminance, scaled so the brighter half's mean is --level (the
     authored bodies' convention, painted neutral). The live tint then sets the hue and the brightness: the body
     is the sprite's measured paint, with the generator's shading.
Writes to --out (default: in place; a file is unlinked before it is written, assets/models shares inodes with
stages). Deterministic: same input, same output. Prints one line a pair; --dry-run writes nothing.

  python3 tools/car_paint_resplit.py assets/models [--out DIR] [--only 044,082] [--dry-run]
"""
import argparse, glob, os, struct, sys
import numpy as np
from PIL import Image


def hsv(rgb):
    mx = rgb.max(-1); mn = rgb.min(-1); dl = np.maximum(mx - mn, 1e-6)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h = np.where(mx == r, ((g - b) / dl) % 6, np.where(mx == g, (b - r) / dl + 2, (r - g) / dl + 4)) * 60.0
    return h, (mx - mn) / np.maximum(mx, 1.0), mx


def read(path):
    im = Image.open(path).convert("RGBA")
    return np.asarray(im).astype(np.float32)


def write_tga(arr, path):
    """32-bit uncompressed TGA, bottom-up (as tools/import_assets.py writes them)."""
    if os.path.lexists(path):
        os.unlink(path)   # never write through a hard link into a stage
    px = np.clip(arr + 0.5, 0, 255).astype(np.uint8)[::-1][..., [2, 1, 0, 3]]
    h, w = px.shape[:2]
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(px.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--hue-tol", type=float, default=30.0)
    ap.add_argument("--min-sat", type=float, default=0.10)
    ap.add_argument("--min-colour", type=float, default=0.30, help="below this share of coloured lit texels the body is neutral: kept")
    ap.add_argument("--min-max", type=float, default=26.0)
    ap.add_argument("--level", type=float, default=215.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = a.out or a.models
    only = {s.strip().zfill(3) for s in a.only.split(",") if s.strip()}
    # The livery models are drawn untinted (identity.cpp Livery): their paint keeps its colours.
    livery = {4, 11, 12, 17, 22, 23, 24, 25, 26, 27, 34, 51, 52, 54, 56, 59, 60, 61, 67, 84, 85, 86}
    pairs = sorted(glob.glob(os.path.join(a.models, "[0-9][0-9][0-9]_*_paint.tga")))
    n = 0
    for pp in pairs:
        base = os.path.basename(pp)
        if only and base[:3] not in only:
            continue
        if int(base[:3]) in livery:
            print(f"skip {base}: a livery (drawn untinted)"); continue
        rp = pp[: -len("_paint.tga")] + ".tga"
        if not os.path.exists(rp):
            continue
        P, R = read(pp), read(rp)
        if P.shape != R.shape:
            print(f"skip {base}: sizes differ"); continue
        pm = P[..., 3] >= 128
        if pm.mean() > 0.9:
            print(f"skip {base}: authored atlas (paint opaque everywhere)"); continue
        if pm.any() and float(np.abs(P[pm][:, 0] - P[pm][:, 2]).mean()) < 1.0 and float(np.abs(P[pm][:, 0] - P[pm][:, 1]).mean()) < 1.0:
            print(f"skip {base}: paint already neutral (re-split before)"); continue
        rm = (R[..., 3] >= 128) & ~pm
        rgb = np.where(pm[..., None], P[..., :3], R[..., :3])
        h, s, mx = hsv(rgb)
        used = (pm | rm) & (mx >= 50)            # lit texels of either half (the unused atlas is black)
        lit = used & (s >= a.min_sat)
        if lit.sum() < max(500, a.min_colour * used.sum()):
            print(f"keep {base}: neutral body ({int(lit.sum())} of {int(used.sum())} lit texels coloured), split unchanged"); continue
        hist, _ = np.histogram(h[lit], bins=36, range=(0, 360))
        sm = hist + 0.5 * (np.roll(hist, 1) + np.roll(hist, -1))
        peak = (int(np.argmax(sm)) + 0.5) * 10.0
        dh = np.abs((h - peak + 180.0) % 360.0 - 180.0)
        # The paint: every texel of the body's hue, from either half (the old paint texels of another hue,
        # a whitewall or a lamp the old split took, go back to the rest and keep their colour).
        mask = (pm | rm) & (dh < a.hue_tol) & (s >= a.min_sat) & (mx >= a.min_max)
        add = mask & ~pm
        lum = 0.30 * rgb[..., 0] + 0.59 * rgb[..., 1] + 0.11 * rgb[..., 2]
        lv = lum[mask]
        top = lv[lv >= np.median(lv)].mean() if lv.size else 1.0
        k = a.level / max(top, 1.0)
        grey = np.clip(lum * k, 0, 255)
        newP = P.copy(); newR = R.copy()
        for c in range(3):
            newP[..., c] = np.where(mask, grey, P[..., c])
        newP[..., 3] = np.where(mask, 255, 0)
        newR[..., :3] = np.where(pm[..., None] & ~mask[..., None], P[..., :3], R[..., :3])   # old paint texels back in the rest
        newR[..., 3] = np.where(mask, 0, np.where((R[..., 3] >= 128) | pm, 255, R[..., 3]))
        print(f"{base}: body hue {peak:.0f}, paint {int(pm.sum())} -> {int(mask.sum())} texels (+{int(add.sum())} from the rest, -{int((pm & ~mask).sum())} back), "
              f"brighter half {top:.0f} -> {a.level:.0f} (x{k:.2f}), neutral")
        n += 1
        if a.dry_run:
            continue
        os.makedirs(out, exist_ok=True)
        write_tga(newP, os.path.join(out, base))
        write_tga(newR, os.path.join(out, os.path.basename(rp)))
    print(f"{n} pairs {'checked' if a.dry_run else 'written to ' + out}")


if __name__ == "__main__":
    main()
