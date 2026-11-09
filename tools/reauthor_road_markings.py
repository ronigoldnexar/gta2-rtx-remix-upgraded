#!/usr/bin/env python3
"""Re-authors the painted road markings of the HD tiles (quality bar QB-24).

    reauthor_road_markings.py <game/data> <style wil|bil|ste> <64px dump> <hd dds dir> <out dir>
                              [--tiles 264,672] [--sheet PNG] [--min-paint 12] [--jobs N]

The upscalers (Real-ESRGAN, SD1.5 ControlNet Tile, tools/upscale_textures.py and
tools/enhance_textures_sd.py) read the worn, dithered paint of GTA2's 64 px road tiles
as texture and invent structure inside it: zebra bars, STOP letters, double lines and
lane lines came out filled with squiggly black noise and fake cracks at street level.
Here the paint is not upscaled at all but drawn again:

  1. The road tiles are the lids of the map's road blocks (ground type 1 in the
     .gmp DMAP); only those are touched.
  2. Paint is found in the 64 px original: white = brighter than the tile's asphalt
     by 28+ levels and nearly grey, yellow = red well above blue. A kerb band at a
     tile edge (light concrete closed off by its dark shadow line) is excluded.
  3. The paint's intended shape is the mask closed and cleaned at 64 px (the wear
     streaks of the original are gaps in the paint, not part of the shape), then
     upscaled bicubically and steepened to an edge about 2 px wide at 512 px: the
     bars, letters and arrows come out as clean shapes with straight edges and
     round corners.
  4. Under the paint the HD asphalt is rebuilt from the tile's own unpainted asphalt
     (copied in from shifted positions), so the invented noise is gone.
  5. The paint goes on top: one colour per kind (the original's own tint pulled
     toward a road-paint white or yellow), the aggregate showing faintly through,
     and light wear (small chips and thinning from a tileable noise field).

Unpainted tiles are left as they are. The result is written as tile_NNNN.dds in the
same format the packer writes (tools/pack_textures_dds.py: DXT1, DXT5 for cutouts,
Lanczos mips to 1x1), with a before/after --sheet. Changing a tile's pixels changes
its Remix texture hash; see docs/hd-textures.md "Road markings".
"""
import argparse, os, sys
from multiprocessing import Pool

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'linux', 'docker'))
from pack_textures_dds import dds_header, encode_level, soft_alpha  # noqa: E402
import gmp  # noqa: E402

# Road lids reviewed on the before/after sheet and left alone: kerb corners and
# kerb-only tiles whose light concrete or yellow kerb reads as paint, no markings.
# bil 960-991 is the derelict quarter: its paint is cracked and flaking on purpose
# and too broken at 64 px to redraw, the HD keeps the look.
SKIP = {
    'wil': {262, 678, 681, 682, 684},
    'bil': set(range(960, 992)),
    'ste': {70, 80, 693},
}

WHITE_PAINT = np.array([206.0, 207.0, 199.0])
YELLOW_PAINT = np.array([204.0, 160.0, 46.0])


def road_lids(gmp_path):
    blocks, cols = gmp.load(gmp_path)
    count = {}
    for off, idx in cols.values():
        for i in idx:
            b = blocks[i]
            t = b[4] & 1023
            if t and (b[6] & 3) == 1:
                count[t] = count.get(t, 0) + 1
    return count


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def lum(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def kerb_zone(L, yellow=None):
    """Pixels between a tile edge and a dark shadow line (or the yellow kerb line)
    that runs along most of that edge within 9 px: the kerb, which is light
    concrete, not paint."""
    zone = np.zeros_like(L, dtype=bool)
    zone |= _edge_band(L < 52)
    if yellow is not None:
        zone |= _edge_band(yellow > 0.5)
    return zone


def yellow_kerb(yellow, reach=14):
    """A thick yellow band (3+ rows) along most of an edge within `reach` px is a
    painted kerb (the darker-asphalt set), not a line on the road. The upscalers keep a long straight band clean, and its
    worn brick pattern is not a shape to redraw: the band and everything between
    it and the edge are left as the HD tile has them."""
    zone = np.zeros_like(yellow, dtype=bool)
    for rot in range(4):
        y = np.rot90(yellow > 0.5, rot)
        band = y[:reach, :]
        rows = np.where(band.mean(axis=1) >= 0.5)[0]
        if band.any(axis=0).mean() >= 0.8 and rows.size >= 3:
            last = int(rows.max())
            z = np.zeros_like(y)
            z[:last + 3, :] = True
            zone |= np.rot90(z, -rot)
    return zone


def corner_nubs(white, reach=14):
    """Light components that sit entirely in a tile corner are the ends of kerbs
    (the small concrete nubs at a junction), not paint."""
    n = white.shape[0]
    out = np.zeros_like(white, dtype=bool)
    lab, k = ndimage.label(white > 0.3)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        ys, xs = sl
        near_y = ys.start < 2 and ys.stop <= reach or ys.stop > n - 2 and ys.start >= n - reach
        near_x = xs.start < 2 and xs.stop <= reach or xs.stop > n - 2 and xs.start >= n - reach
        if near_y and near_x:
            out |= lab == i
    return out


def _edge_band(line):
    n = line.shape[0]
    zone = np.zeros_like(line, dtype=bool)
    for rot in range(4):
        s = np.rot90(line, rot)
        z = np.zeros_like(s)
        hit = s[:9, :]
        cols = hit.any(axis=0)
        if cols.mean() >= 0.6:
            first = np.where(cols, hit.argmax(axis=0), 0)
            # columns without a shadow pixel take the typical depth
            depth = int(np.median(first[cols]))
            first = np.where(cols, first, depth)
            for x in range(n):
                z[:first[x] + 1, x] = True
        zone |= np.rot90(z, -rot)
    return zone


def paint_masks(o):
    """Soft white and yellow paint coverage of a 64 px RGB tile (floats 0..1)."""
    L = lum(o)
    chroma = o.max(axis=2) - o.min(axis=2)
    base = L[(L < 110) & (L > 52)]
    la = float(np.median(base)) if base.size > 64 else float(np.median(L))
    white = smoothstep(la + 28, la + 55, L) * (1.0 - smoothstep(38, 60, chroma))
    rb = o[..., 0] - o[..., 2]
    yellow = smoothstep(38, 70, rb) * smoothstep(100, 130, o[..., 0])
    kz = kerb_zone(L, yellow) | yellow_kerb(yellow)
    white[kz] = 0.0
    white[corner_nubs(white)] = 0.0
    yellow[yellow_kerb(yellow)] = 0.0
    # coverage as a fraction of the way from this tile's asphalt to its paint, so the
    # 0.5 contour is the half-maximum edge of a soft, low-contrast arrow or letter
    # too (its tips and thin strokes), not a fixed brightness cut
    near_w = ndimage.binary_dilation(white > 0.05, iterations=1) & ~kz
    if (white > 0.8).sum() >= 4:
        pw = float(np.percentile(L[white > 0.8], 90))
        cov = np.clip((L - la) / max(pw - la, 20.0), 0.0, 1.0) * (1.0 - smoothstep(38, 60, chroma))
        white = np.where(near_w, np.maximum(white, cov), 0.0)
    near_y = ndimage.binary_dilation(yellow > 0.05, iterations=1) & ~yellow_kerb(yellow)
    if (yellow > 0.8).sum() >= 4:
        py = float(np.percentile(rb[yellow > 0.8], 90))
        rb0 = float(np.median(rb[(L < 110) & (L > 52)])) if base.size > 64 else 0.0
        cov = np.clip((rb - rb0) / max(py - rb0, 20.0), 0.0, 1.0) * smoothstep(90, 120, o[..., 0])
        yellow = np.where(near_y, np.maximum(yellow, cov), 0.0)
    # the yellow kerb-edge line sits right under the kerb, keep yellow there unless it is
    # inside the concrete band itself
    yellow[kz & (L > la + 40) & (rb < 50)] = 0.0
    return white, yellow, la


def shape(m64):
    """Intended paint shape at 64 px: one-pixel wear streaks bridged (a cross-shaped
    closing, so the counters of O and the notches of W stay open), the dithered edge
    straightened by a light blur, specks dropped."""
    b = m64 > 0.45
    closed = ndimage.binary_closing(b, structure=ndimage.generate_binary_structure(2, 1), border_value=0)
    closed |= b
    # bridge only worn (grey) pixels: a true hole in a letter is bare asphalt (coverage ~0)
    m = np.where(closed & (m64 > 0.12), np.maximum(m64, 0.8), m64)
    m = ndimage.gaussian_filter(m, 0.8, mode='nearest')
    lab, n = ndimage.label(m > 0.5)
    if n:
        sizes = ndimage.sum(np.ones_like(m), lab, index=np.arange(1, n + 1))
        for i, sz in enumerate(sizes, 1):
            if sz < 4:
                m[lab == i] = 0.0
    return m


def upscale_mask(m, size, k=4.0, straighten=False):
    """Bicubic with edge padding (paint continues across into the neighbour tile),
    steepened to a ~2 px edge; `straighten` runs a median over the soft mask first,
    which irons the dither bumps of the original out of a bar's edge."""
    pad = 4
    mp = np.pad(m, pad, mode='edge')
    big = size + 2 * pad * size // m.shape[0]
    im = Image.fromarray((mp * 255).astype(np.float32), mode='F').resize((big, big), Image.BICUBIC)
    a = np.asarray(im) / 255.0
    c = pad * size // m.shape[0]
    a = a[c:c + size, c:c + size]
    if straighten:
        a = ndimage.median_filter(a, size=max(3, size // 96) | 1, mode='nearest')
    return np.clip((a - 0.5) * k + 0.5, 0.0, 1.0)


def value_noise(size, cells, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((cells, cells))
    g = np.pad(g, 2, mode='wrap')
    im = Image.fromarray(g.astype(np.float32), mode='F')
    scale = size / cells
    big = im.resize((int(round((cells + 4) * scale)),) * 2, Image.BICUBIC)
    off = int(round(2 * scale))
    return np.asarray(big)[off:off + size, off:off + size]


def wear_field(size, seed):
    """Small chips only: no low frequency, so a letter never loses a whole stroke."""
    return value_noise(size, 48, seed + 1) * 0.45 + value_noise(size, 160, seed + 2) * 0.55


def fill_asphalt(rgb, region, rng):
    """Replace `region` by the tile's own asphalt from shifted positions that are
    bare asphalt (not paint, kerb, yellow line or a manhole: within 28 levels of the
    tile's asphalt and not yellow)."""
    L = lum(rgb)
    la = float(np.median(L[~region])) if (~region).any() else float(np.median(L))
    bare = (~region) & (np.abs(L - la) < 28) & ((rgb[..., 0] - rgb[..., 2]) < 30)
    bare = ndimage.binary_erosion(bare, iterations=3)
    if bare.mean() < 0.05:
        bare = ~region
    region_src = ~bare
    out = rgb.copy()
    todo = region.copy()
    size = rgb.shape[0]
    for _ in range(40):
        if not todo.any():
            break
        dy, dx = rng.integers(size // 8, size - size // 8, 2)
        src = np.roll(rgb, (dy, dx), axis=(0, 1))
        ok = ~np.roll(region_src, (dy, dx), axis=(0, 1)) & todo
        out[ok] = src[ok]
        todo &= ~ok
    if todo.any():
        out[todo] = np.median(rgb[bare], axis=0)
    # soften the seams of the patchwork a little
    blur = ndimage.uniform_filter(out, size=(3, 3, 1))
    out[region] = 0.5 * out[region] + 0.5 * blur[region]
    return out


def paint_colour(o, m, target, pull):
    sel = m > 0.8
    if sel.sum() < 4:
        return target
    own = np.median(o[sel], axis=0)
    # keep the original's tint, at road-paint brightness
    own = own * (lum(target[None, :])[0] / max(lum(own[None, :])[0], 1.0))
    return np.clip(own * (1 - pull) + target * pull, 0, 255)


def is_asphalt(o):
    """Paint is redrawn only on asphalt: a dark, nearly grey tile (median luminance
    <= 105, median chroma <= 26). Sand, grass, dirt tracks and pavers that the map
    marks as road are left alone."""
    return float(np.median(lum(o))) <= 105 and float(np.median(o.max(axis=2) - o.min(axis=2))) <= 26


def reauthor(o64, hd, size, seed):
    o = o64.astype(np.float64)
    if not is_asphalt(o):
        return None, 0
    white, yellow, _ = paint_masks(o)
    ws, ys = shape(white), shape(yellow)
    painted = int(((ws > 0.5) | (ys > 0.5)).sum())
    aw, ay = upscale_mask(ws, size, straighten=True), upscale_mask(ys, size, straighten=True)
    ay = np.where(ay > aw, ay, 0.0)
    aw = np.where(aw >= ay, aw, 0.0)
    a = np.maximum(aw, ay)
    # where the old paint was (also its soft ESRGAN halo and noise): rebuild asphalt
    old = upscale_mask(np.maximum(ndimage.grey_dilation(np.maximum(white, yellow), size=(3, 3)), np.maximum(ws, ys)),
                       size, k=8.0)
    region = ndimage.binary_dilation((old > 0.02) | (a > 0.0), iterations=max(2, size // 96))
    rng = np.random.default_rng(seed)
    h = hd.astype(np.float64)
    base = fill_asphalt(h, region, rng)
    # paint, aggregate faintly through it, light wear
    agg = lum(base)
    agg = agg / max(float(np.median(agg[~region])) if (~region).any() else float(agg.mean()), 1.0)
    agg = np.clip(agg, 0.6, 1.4)
    cw = paint_colour(o, white, WHITE_PAINT, 0.6)
    cy = paint_colour(o, yellow, YELLOW_PAINT, 0.5)
    tint = 0.9 + 0.1 * agg
    paint = (np.where((aw >= ay)[..., None], cw, cy)) * tint[..., None]
    wear = wear_field(size, seed)
    chips = smoothstep(0.70, 0.75, wear)
    # thinning: the paint is worn more in broad patches (tyre tracks), never fully
    thin = 0.78 + 0.16 * value_noise(size, 6, seed + 7) + 0.04 * value_noise(size, 96, seed + 8)
    alpha = a * (1.0 - 0.7 * chips) * np.clip(thin, 0.0, 0.96)
    out = base * (1 - alpha[..., None]) + paint * alpha[..., None]
    return np.clip(out, 0, 255).astype(np.uint8), painted


def write_dds(path, rgb, alpha, size):
    has_alpha = alpha is not None
    fmt = 'DXT5' if has_alpha else 'DXT1'
    im = Image.fromarray(rgb, 'RGB')
    al = alpha if has_alpha else Image.new('L', (size, size), 255)
    levels = []
    w = size
    cur = im.copy(); cur.putalpha(al)
    while True:
        levels.append(encode_level(cur, fmt))
        if w == 1:
            break
        w = max(1, w // 2)
        cur = im.resize((w, w), Image.LANCZOS)
        cur.putalpha(al.resize((w, w), Image.BOX))
    with open(path, 'wb') as f:
        f.write(dds_header(size, size, len(levels), fmt.encode(), len(levels[0])))
        for lv in levels:
            f.write(lv)


def job(args):
    t, orig_dir, hd_dir, out_dir, min_paint = args
    name = 'tile_%04d' % t
    src = os.path.join(orig_dir, name + '.tga')
    dds = os.path.join(hd_dir, name + '.dds')
    if not (os.path.exists(src) and os.path.exists(dds)):
        return t, None, 0
    o = Image.open(src).convert('RGBA')
    hd = Image.open(dds).convert('RGB')
    size = hd.size[0]
    new, painted = reauthor(np.asarray(o)[..., :3], np.asarray(hd), size, seed=t)
    if new is None or painted < min_paint:
        return t, None, painted
    a64 = o.split()[3]
    alpha = soft_alpha(a64, size) if a64.getextrema()[0] < 255 else None
    write_dds(os.path.join(out_dir, name + '.dds'), new, alpha, size)
    return t, name + '.dds', painted


def sheet(path, style, ids, orig_dir, hd_dir, out_dir, cell=256):
    cols = 3
    rows = len(ids)
    im = Image.new('RGB', (cell * cols, cell * rows), (30, 0, 30))
    for r, t in enumerate(ids):
        name = 'tile_%04d' % t
        im.paste(Image.open(os.path.join(orig_dir, name + '.tga')).convert('RGB').resize((cell, cell), Image.NEAREST), (0, r * cell))
        im.paste(Image.open(os.path.join(hd_dir, name + '.dds')).convert('RGB').resize((cell, cell), Image.LANCZOS), (cell, r * cell))
        im.paste(Image.open(os.path.join(out_dir, name + '.dds')).convert('RGB').resize((cell, cell), Image.LANCZOS), (2 * cell, r * cell))
    im.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data'); ap.add_argument('style'); ap.add_argument('orig'); ap.add_argument('hd'); ap.add_argument('out')
    ap.add_argument('--tiles', help='comma list instead of every road lid')
    ap.add_argument('--skip', default='', help='comma list of road lids to leave alone')
    ap.add_argument('--min-paint', type=int, default=12, help='painted 64 px pixels for a tile to be re-authored')
    ap.add_argument('--sheet'); ap.add_argument('--jobs', type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.tiles:
        ids = [int(x) for x in a.tiles.split(',')]
    else:
        ids = sorted(road_lids(os.path.join(a.data, a.style + '.gmp')))
    skip = {int(x) for x in a.skip.split(',') if x} | (set() if a.tiles else SKIP.get(a.style, set()))
    ids = [t for t in ids if t not in skip]
    with Pool(a.jobs) as p:
        res = p.map(job, [(t, a.orig, a.hd, a.out, a.min_paint) for t in ids])
    done = [t for t, n, _ in res if n]
    for t, n, painted in res:
        print('%s tile %4d painted %4d %s' % (a.style, t, painted, 're-authored' if n else '-'))
    print('%s: %d of %d road lids re-authored' % (a.style, len(done), len(ids)))
    if a.sheet and done:
        sheet(a.sheet, a.style, done, a.orig, a.hd, a.out)


if __name__ == '__main__':
    main()
