#!/usr/bin/env python3
"""pm6: a crisp arched double door for the photo/ tile set (FIX-WORLD-8).

The game's own 64 px art of the arched street door (wil tile 538, the Altamount hotel
block) is a blurred navy-blue double door with streaks of light; the HD upscale and the
photo pass both keep that blur faithfully, so in the street views the main street-level
landmark reads as a smeared ghost beside crisp windows. This redraws only the opening
inside the arch, at 1024 px, in the art's own layout and colours: a dark reveal along
the arch, a navy painted frame, a fanlight with radial glazing bars over a transom, two
leaves split down the middle (glazed upper panels with a sky reflection, raised lower
panels, brass pull handles at the meeting stiles), and the art's own threshold step.
Everything outside the arch (the wall, cornice, mouldings) is the photo tile itself,
upscaled. The shipped textures_hd DDS are never touched (Remix keys them by hash); the
result goes into gta2dx9_textures_hd/photo/<style>/, bound only in the street views.

    arch_door_tile.py <photo tile_0538.dds> <out tile_0538.dds> [--cc0 dir] [--preview out.png]

Paint grain: the luminance high-pass of ambientCG Wood067 (CC0, the photoreal_tiles.py
material set; `photoreal_tiles.py fetch <cc0 dir>`), run vertically along the leaves.
"""
import argparse, os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = 1024          # output size
SS = 2              # supersampling of the drawn shapes
# the arch, in the 512 px source tile's texels (measured on wil 538's photo tile)
CX, CY, RX, RY = 257.0, 262.0, 233.0, 174.0     # elliptical head: centre, half width, rise
X0, X1, YB = 24.0, 490.0, 494.0                # straight jambs and the sill (threshold below)
REVEAL, FRAME = 14.0, 12.0                      # widths of the dark reveal and the painted frame
TRANSOM = (232.0, 250.0)                        # top/bottom of the transom bar
MID = 372.0, 392.0                              # middle rail of each leaf
BOT = 462.0                                     # bottom rail top

NAVY = np.array([43, 53, 80], np.float32) / 255     # the art's grey-blue, a touch deeper
NAVY_DK = np.array([24, 31, 50], np.float32) / 255
BRASS = np.array([196, 156, 72], np.float32) / 255


def arch_mask(X, Y, inset):
    """inside the arch shrunk by `inset` texels (ellipse head over straight jambs)"""
    rx, ry = RX - inset, RY - inset
    head = ((X - CX) / rx) ** 2 + ((Y - CY) / ry) ** 2 <= 1.0
    jamb = (X >= X0 + inset) & (X <= X1 - inset) & (Y >= CY)
    return (head | jamb) & (Y <= YB)


def build(src, size=OUT, cc0=""):
    base = Image.open(src).convert("RGBA")
    n = size * SS
    big = np.asarray(base.convert("RGB").resize((n, n), Image.LANCZOS)).astype(np.float32) / 255
    k = 512.0 / n                                   # drawn texel -> source texel
    Y, X = np.mgrid[0:n, 0:n].astype(np.float32) * k + 0.5 * k
    rng = np.random.default_rng(538)
    grain = np.asarray(Image.fromarray(rng.normal(0, 1, (n // 4, n // 16)).astype(np.float32)).resize((n, n), Image.BICUBIC))
    if cc0:
        w = Image.open(os.path.join(cc0, "Wood067", "Wood067_2K-JPG_Color.jpg")).convert("L")
        w = np.asarray(w.resize((n, n), Image.LANCZOS)).astype(np.float32) / 255
        from scipy.ndimage import gaussian_filter
        hp = w - gaussian_filter(w, 6 * SS); hp /= max(hp.std(), 1e-4)
        if abs(np.diff(w, axis=0)).mean() > abs(np.diff(w, axis=1)).mean(): hp = hp.T   # grain runs vertically
        grain = 0.4 * grain + 0.9 * hp
    # grime: darker toward the foot of the leaves and in the reveal's corners
    grime = 1 - 0.10 * np.clip((Y - 400) / 94, 0, 1) ** 1.5
    out = big.copy()

    a0 = arch_mask(X, Y, 0); a1 = arch_mask(X, Y, REVEAL); a2 = arch_mask(X, Y, REVEAL + FRAME)
    # reveal: the arch's depth in shadow, darker toward the crown, a lit inner arris
    t = np.clip((Y - 88) / 400, 0, 1)
    rev = np.stack([0.11 + 0.06 * t, 0.11 + 0.06 * t, 0.13 + 0.06 * t], -1)
    sel = a0 & ~a1; out[sel] = rev[sel]
    # painted frame
    paint = NAVY[None, None] * ((1 + 0.035 * grain) * grime)[..., None]
    sel = a1 & ~a2; out[sel] = paint[sel]
    edge = a1 & ~arch_mask(X, Y, REVEAL + 2.0); out[edge] = np.clip(paint[edge] * 1.35, 0, 1)

    def glass(sel, y0, y1):
        g = np.clip((Y - y0) / max(y1 - y0, 1), 0, 1)
        sky = (1 - g)[..., None] * np.array([0.33, 0.42, 0.56], np.float32) + g[..., None] * np.array([0.15, 0.19, 0.27], np.float32)
        sheen = np.exp(-(((X - Y * 0.55) - 60) / 26) ** 2) * 0.10 + np.exp(-(((X - Y * 0.55) - 300) / 14) ** 2) * 0.06
        col = np.clip(sky + sheen[..., None], 0, 1)
        out[sel] = col[sel]

    def bar(sel, shade=1.0):
        out[sel] = np.clip(paint[sel] * shade, 0, 1)

    inner = a2
    # fanlight over the transom: glass with radial glazing bars and a hub
    fan = inner & (Y < TRANSOM[0])
    glass(fan, 100, TRANSOM[0])
    ang = np.degrees(np.arctan2(TRANSOM[0] - Y, X - CX))
    r = np.hypot(X - CX, (Y - TRANSOM[0]) * RX / RY)
    for a in (30, 60, 90, 120, 150):
        d = np.abs(np.radians(ang - a)) * r
        bar(fan & (d < 3.2) & (r > 40), 0.95)
    hub = fan & (r < 44); bar(hub, 1.0)
    bar(fan & (np.abs(r - 44) < 3), 1.3)
    # transom bar, lit on top
    tr = inner & (Y >= TRANSOM[0]) & (Y < TRANSOM[1]); bar(tr)
    bar(inner & (Y >= TRANSOM[0]) & (Y < TRANSOM[0] + 2.5), 1.45)
    bar(inner & (Y >= TRANSOM[1] - 2.5) & (Y < TRANSOM[1]), 0.6)
    # two leaves
    lx0, lx1 = X0 + REVEAL + FRAME, X1 - REVEAL - FRAME
    leaves = inner & (Y >= TRANSOM[1])
    bar(leaves)
    for (a, b) in ((lx0, CX - 1.5), (CX + 1.5, lx1)):
        st = 20.0
        up = leaves & (X > a + st) & (X < b - st) & (Y > TRANSOM[1] + 20) & (Y < MID[0])
        glass(up, TRANSOM[1] + 20, MID[0])
        # glazing bars: one upright, one cross bar
        bar(up & (np.abs(X - (a + b) / 2) < 2.6), 0.95)
        bar(up & (np.abs(Y - (TRANSOM[1] + 20 + MID[0]) / 2) < 2.6), 0.95)
        # putty shadow inside the top/left of the glass, lit sill under it
        bar(up & (Y < TRANSOM[1] + 23), 0.55); bar(up & (X < a + st + 3), 0.6)
        bar(leaves & (X > a + st) & (X < b - st) & (Y >= MID[0]) & (Y < MID[0] + 3), 1.45)
        # raised lower panel with bevels (light from above-left)
        px0, px1, py0, py1 = a + st + 4, b - st - 4, MID[1] + 6, BOT - 6
        pan = leaves & (X > px0) & (X < px1) & (Y > py0) & (Y < py1)
        bv = 7.0
        dl, dr, dt, db = X - px0, px1 - X, Y - py0, py1 - Y
        m = np.minimum(np.minimum(dl, dr), np.minimum(dt, db))
        field = pan & (m >= bv)
        bar(pan, 1.0)
        bar(pan & (m < bv) & ((dt <= np.minimum(dl, dr)) & (dt < bv)), 1.4)
        bar(pan & (m < bv) & ((dl < bv) & (dl < dt) & (dl <= db)), 1.2)
        bar(pan & (m < bv) & ((db < bv) & (db <= np.minimum(dl, dr))), 0.62)
        bar(pan & (m < bv) & ((dr < bv) & (dr < db) & (dr <= dt)), 0.75)
        bar(field, 1.08)
        # kick rail shadow line
        bar(leaves & (X > a) & (X < b) & (Y >= BOT) & (Y < BOT + 2.5), 0.55)
    # meeting stiles: a dark gap and an astragal
    bar(leaves & (np.abs(X - CX) < 1.6), 0.35)
    bar(leaves & (np.abs(X - CX - 3.5) < 1.2), 1.4)
    # brass pull handles on each leaf by the meeting stile, with mounts
    for sx in (CX - 13, CX + 13):
        h = leaves & (np.abs(X - sx) < 2.4) & (Y > 292) & (Y < 352)
        lit = np.clip(1.15 - np.abs(X - sx + 0.8) / 2.4 * 0.6, 0.5, 1.2)
        out[h] = np.clip(BRASS[None, None] * lit[..., None], 0, 1)[h]
        for my in (292, 352):
            mt = leaves & (np.abs(X - sx) < 3.6) & (np.abs(Y - my) < 3.2)
            out[mt] = (BRASS * 0.7)[None]
    # keep the art's threshold step and everything outside the arch exactly
    out[~a0] = big[~a0]
    img = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).resize((size, size), Image.BOX)
    alpha = base.getchannel("A").resize((size, size), Image.BOX)
    rgba = np.dstack([np.asarray(img), np.asarray(alpha)]).astype(np.float32) / 255
    return rgba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--preview", default=""); ap.add_argument("--cc0", default="/mnt/gta2/ab_work/cc0")
    a = ap.parse_args()
    rgba = build(a.src, cc0=a.cc0 if os.path.isdir(a.cc0) else "")
    from photoreal_tiles import write_dds
    write_dds(a.dst, rgba)
    if a.preview:
        Image.fromarray((rgba[..., :3] * 255 + 0.5).astype(np.uint8)).save(a.preview)
    print("wrote", a.dst, rgba.shape[0], "px")


if __name__ == "__main__":
    main()
