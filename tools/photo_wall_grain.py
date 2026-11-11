#!/usr/bin/env python3
"""Puts the stone grain of a wall tile back into its street-view photo copy (qav7, FIX-WORLD-19).

qav7 (ste 90.5,170.5, noon) filed the shaded faces of the green stone buildings as near-black
featureless slabs. A one-grey probe (every ste tile one mid grey, private stage) read the shaded
wall at 82 against the sunlit wall at 127, 65 % in display luma: the plain renderer's light on
vertical faces is right. FIX-WORLD-13 had lifted the photo copies of the dark green stone (ste
103/105/109) to a mean luma of ~68 (tools/photo_albedo_floor.py), so the slab is no longer black,
but it stayed featureless: the game's 64 px stone (105, and the wall around the windows of 103/109)
is a speckled green stone with lighter grey flecks, and the upscalers (HD and photo sets alike)
smoothed it into one flat green. A whole first-person frame of that reads as a painted slab.

Here the grain is rebuilt, the tone is not changed:
  1. Wall mask: pixels of the 64 px art whose colour sits inside the stone palette of the reference
     tile (--ref, the plain stone tile: Mahalanobis distance to its mean colour), opened to drop
     single pixels, upsampled and softened; window frames, sills, pilasters and glass stay as the
     photo copy has them.
  2. The art's own speckle: the 64 px tile minus its blur, upscaled bicubically (the art's fleck
     layout, as classic shows it), plus a fine two-octave value noise (2-4 px grains at 512) so the
     grain is crisp at one block instead of 8 px soft blobs.
  3. Under the mask the photo copy is replaced by its own low frequencies (its tone and shading
     gradient) plus that grain, scaled so the grain's contrast matches the art's speckle times the
     photo's tone gain; the tile's mean luma is restored to the source photo's (WORLD-13's floor).

Street set only (assets/textures_hd/photo/<style>/): classic draws the HD set and a Remix device
never loads photo/, so neither changes. Writes a new file (os.replace), never through a hard link.

    photo_wall_grain.py <64 px dump dir> <photo style dir> <out dir> --tiles 103,105,109 [--ref 105]
                        [--grain 1.0] [--stone-mean 70] [--sheet png]
"""
import argparse, os, sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_textures_dds import dds_header, encode_level  # noqa: E402


def lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def value_noise(size, cells, seed):
    rng = np.random.default_rng(seed)
    g = rng.standard_normal((cells, cells)).astype(np.float32)
    g = np.tile(g, (3, 3))  # wrap so the tile stays seamless
    big = np.asarray(Image.fromarray(g, 'F').resize((size * 3, size * 3), Image.BICUBIC))
    return big[size:2 * size, size:2 * size]


def stone_palette(o):
    px = o.reshape(-1, 3)
    mu = px.mean(axis=0)
    cov = np.cov(px.T) + np.eye(3) * 4.0
    return mu, np.linalg.inv(cov)


def wall_mask64(o, mu, icov, thr):
    d = o - mu
    m2 = np.einsum('...i,ij,...j->...', d, icov, d)
    m = m2 < thr * thr
    m = ndimage.binary_opening(m, structure=np.ones((2, 2)))
    return m


def regrain(o64, photo, mu, icov, thr, grain, seed):
    size = photo.shape[0]
    k = size // o64.shape[0]
    m64 = wall_mask64(o64, mu, icov, thr).astype(np.float32)
    m = np.asarray(Image.fromarray(m64, 'F').resize((size, size), Image.BILINEAR))
    m = ndimage.gaussian_filter(m, k * 0.35)
    m = np.clip((m - 0.35) / 0.4, 0.0, 1.0)            # pull the soft edge in off the frames
    # and only where the photo copy itself is stone-coloured: the dark glass is close to the
    # stone's green at 64 px, its photo copy is not
    pb = ndimage.gaussian_filter(photo, (1.5, 1.5, 0))
    pw = np.median(pb[m > 0.9], axis=0) if (m > 0.9).any() else pb.reshape(-1, 3).mean(axis=0)
    # by hue with a loose luma window, so the window shadows baked on the stone take grain too
    lp, lw = lum(pb), float(lum(pw[None, :])[0])
    dist = np.sqrt(((pb / np.maximum(lp, 1.0)[..., None] - pw / max(lw, 1.0)) ** 2).sum(axis=2)) * lw
    ratio = lp / max(lw, 1.0)
    m *= np.clip((22.0 - dist) / 10.0, 0.0, 1.0) * np.clip((ratio - 0.45) / 0.15, 0.0, 1.0) \
        * np.clip((1.45 - ratio) / 0.15, 0.0, 1.0)
    m = ndimage.grey_erosion(m, size=(3, 3))
    # the art's speckle, wall pixels only (elsewhere the blur would bleed frame colours in)
    w = m64 > 0.5
    fill = o64.copy()
    fill[~w] = mu
    det64 = fill - ndimage.gaussian_filter(fill, (1.5, 1.5, 0))
    det64[~w] = 0.0
    det = np.stack([np.asarray(Image.fromarray(det64[..., c].astype(np.float32), 'F')
                               .resize((size, size), Image.BICUBIC)) for c in range(3)], axis=2)
    fine = value_noise(size, size // 2, seed) + 0.7 * value_noise(size, size // 4, seed + 1)
    fine /= max(1e-6, fine.std())
    # the art's light grey flecks: sparse, 2-3 px, a neutral lift
    fl = value_noise(size, size // 3, seed + 2)
    fleck = np.clip((fl - 1.9) / 0.6, 0.0, 1.0)
    # contrast: the art's speckle (luma std over the wall) times the photo's tone gain
    art_sd = float(lum(det64)[w].std()) if w.any() else 0.0
    gain_tone = float(lum(photo)[m > 0.5].mean() / max(1.0, lum(o64)[w].mean())) if (m > 0.5).any() else 1.0
    target = art_sd * gain_tone * grain
    det_l = lum(det)
    det_sd = float(det_l[m > 0.5].std()) if (m > 0.5).any() else 1.0
    det *= (0.4 * target / max(1e-6, det_sd))
    chroma = mu / max(1.0, lum(mu[None, :])[0])           # fine grain carries the stone's hue
    grainf = fine[..., None] * (0.9 * target) * chroma[None, None, :]
    grainf += fleck[..., None] * (3.0 * target)
    base = ndimage.gaussian_filter(photo, (k * 0.75, k * 0.75, 0))
    new = base + det + grainf
    out = photo * (1.0 - m[..., None]) + new * m[..., None]
    return out, m


def write_dds(path, rgb, alpha, fmt):
    img = Image.fromarray(np.concatenate([rgb, alpha], axis=2).astype(np.uint8), 'RGBA')
    levels, size, cur = [], img.size[0], img
    while True:
        levels.append(encode_level(cur, fmt))
        if size == 1:
            break
        size //= 2
        cur = img.resize((size, size), Image.LANCZOS)
    with open(path + '.tmp', 'wb') as f:
        f.write(dds_header(img.size[0], img.size[1], len(levels), fmt.encode(), len(levels[0])))
        for lv in levels:
            f.write(lv)
    os.replace(path + '.tmp', path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('orig'); ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--tiles', required=True)
    ap.add_argument('--ref', type=int, default=105, help='the plain stone tile that defines the palette')
    ap.add_argument('--thr', type=float, default=2.6, help='palette distance (Mahalanobis) for the wall mask')
    ap.add_argument('--grain', type=float, default=1.0, help='grain contrast relative to the art')
    ap.add_argument('--stone-mean', type=float, default=0.0,
                    help='scale each tile so its stone reaches this mean luma (0 = keep the tile mean)')
    ap.add_argument('--max-gain', type=float, default=1.6)
    ap.add_argument('--sheet')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ref = np.asarray(Image.open(os.path.join(a.orig, 'tile_%04d.tga' % a.ref)).convert('RGB')).astype(np.float32)
    mu, icov = stone_palette(ref)
    sheet = []
    for t in [int(v) for v in a.tiles.split(',')]:
        name = 'tile_%04d.dds' % t
        raw = open(os.path.join(a.src, name), 'rb').read(128)
        fmt = 'DXT5' if raw[84:88] == b'DXT5' else 'DXT1'
        arr = np.asarray(Image.open(os.path.join(a.src, name)).convert('RGBA')).astype(np.float32)
        rgb, alpha = arr[..., :3], arr[..., 3:]
        o64 = np.asarray(Image.open(os.path.join(a.orig, 'tile_%04d.tga' % t)).convert('RGB')).astype(np.float32)
        out, m = regrain(o64, rgb, mu, icov, a.thr, a.grain, seed=t)
        if (m > 0.5).mean() < 0.10:
            print('%s: stone under 10 %% of the tile, left alone' % name)
            continue
        op = alpha[..., 0] > 127
        m0, m1 = float(lum(rgb)[op].mean()), float(lum(out)[op].mean())
        if a.stone_mean > 0 and (m > 0.5).any():
            # one stone tone over the family: scale the tile so the stone under the mask reaches it
            # (a tile-mean floor leaves the stone of a window-heavy tile brighter than the plain one)
            g = min(a.max_gain, a.stone_mean / max(1.0, float(lum(out)[m > 0.5].mean())))
        else:
            g = m0 / max(1.0, m1)
        out = np.clip(out * g, 0, 255)
        m1 = float(lum(out)[op].mean())
        write_dds(os.path.join(a.out, name), out, alpha, fmt)
        print('%s: %s wall %.0f %% of the tile, mean luma %.1f -> %.1f, stone %.1f, high-pass sd %.1f -> %.1f' % (
            name, fmt, 100.0 * m.mean(), m0, m1, float(lum(out)[m > 0.5].mean()) if (m > 0.5).any() else 0,
            float((lum(rgb) - ndimage.gaussian_filter(lum(rgb), 4))[m > 0.5].std()) if (m > 0.5).any() else 0,
            float((lum(out) - ndimage.gaussian_filter(lum(out), 4))[m > 0.5].std()) if (m > 0.5).any() else 0))
        sheet.append((rgb, out))
    if a.sheet and sheet:
        c = 384
        s = Image.new('RGB', (c * len(sheet), 2 * c))
        for i, (b, n) in enumerate(sheet):
            s.paste(Image.fromarray(b.astype(np.uint8)).resize((c, c), Image.LANCZOS), (i * c, 0))
            s.paste(Image.fromarray(n.astype(np.uint8)).resize((c, c), Image.LANCZOS), (i * c, c))
        s.save(a.sheet)


if __name__ == '__main__':
    main()
