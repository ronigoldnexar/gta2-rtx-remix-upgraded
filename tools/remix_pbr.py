#!/usr/bin/env python3
"""Full PBR maps from a single albedo, for the gta2hd RTX Remix layer (VISUALS-REMIX).

The 1999 tiles and the car/prop textures come as colour only. This derives, per
texel, everything AperturePBR_Opacity reads:

* height and normal, detail-aware: the luminance is split into a *structure*
  band (brick courses and mortar, panel seams, slats, cobbles, window frames:
  difference of Gaussians at ~1/40 of the texture, normalised by its local
  contrast and pushed through tanh so a brick face is a plateau and a mortar
  joint a groove) and a *grain* band (the fine texture inside a face: aggregate,
  weathering, wood fibre). The normal is the slope of structure x a strong
  weight + grain x a weak one, so a wall has deep joints and a fine surface
  instead of the single noisy relief of a Sobel on the albedo. Road paint and
  colour edges with no luminance step do not become steps.
* roughness from a material class per texel (glass, metal, painted/sign,
  brick, stone/concrete, asphalt, vegetation, ceramic) modulated by local grain
  (busier = rougher) and grime (darker than its neighbourhood = rougher).
* metallic only where the texel is neutral, in a strongly oriented,
  finely periodic neighbourhood (corrugated sheet, ribbed panels, girders,
  pipes, rails); bright thin highlights there are chrome-like.
* height for Remix's parallax displacement, only on tiles whose structure is a
  relief (brick, block, cobble, corrugated metal) and that hold no windows or
  signs; displace_in scales with how much relief the tile has.
* (windows=True only, off by default) glass and emissive night windows: dark,
  smooth, rectangular panes inside a brighter frame, about half of them lit in a
  warm or cool tint. Not used for the shipped layer: on a random sample of 180
  tiles every tile it lit was a false positive (blue-grey wall panels, roof
  plates), so the night emission stays the curated signs of remix_emissive.py.
* a wet variant of the roughness: everything glossier, puddles (mirror-smooth)
  in the low areas of ground-like tiles and water in the joints.

Pure numpy (FFT Gaussians; wrap-around for tiles, mirrored edges for atlases).
remix_materials.py (tiles) and remix_model_materials.py (cars, props) call
analyse(); `remix_pbr.py preview <out.png> <texture> ...` shows the maps.
"""
import hashlib, os, sys
import numpy as np

# ----------------------------------------------------------------- filters --
def _gauss_tf(h, w, s):
    fy = np.fft.fftfreq(h)[:, None]; fx = np.fft.rfftfreq(w)[None, :]
    return np.exp(-2 * (np.pi * s) ** 2 * (fx * fx + fy * fy)).astype(np.float32)

_TF = {}
def gauss(a, s, wrap=True):
    """Gaussian blur, sigma s texels: periodic for a tile, mirrored edges for an atlas."""
    if s <= 0: return a
    if not wrap:
        p = int(min(3 * s + 2, min(a.shape[:2]) - 1))
        b = np.pad(a, ((p, p), (p, p)) + ((0, 0),) * (a.ndim - 2), mode="reflect")
        return gauss(b, s, True)[p:-p, p:-p]
    h, w = a.shape[:2]
    key = (h, w, round(s, 3))
    if key not in _TF: _TF[key] = _gauss_tf(h, w, s)
    tf = _TF[key] if a.ndim == 2 else _TF[key][..., None]
    return np.fft.irfft2(np.fft.rfft2(a, axes=(0, 1)) * tf, s=(h, w), axes=(0, 1)).astype(np.float32)

def grad(a, wrap=True):
    if wrap:
        gx = (np.roll(a, -1, 1) - np.roll(a, 1, 1)) * 0.5
        gy = (np.roll(a, -1, 0) - np.roll(a, 1, 0)) * 0.5
    else:
        gy, gx = np.gradient(a)
    return gx.astype(np.float32), gy.astype(np.float32)

def hsv(rgb):
    mx = rgb.max(-1); mn = rgb.min(-1); c = mx - mn
    sat = np.where(mx > 1e-4, c / np.maximum(mx, 1e-4), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    cc = np.maximum(c, 1e-6)
    hue = np.where(mx == r, ((g - b) / cc) % 6, np.where(mx == g, (b - r) / cc + 2, (r - g) / cc + 4)) * 60.0
    return np.where(c > 1e-4, hue, 0), sat, mx

def components(mask):
    """4-connected labels of a small boolean image (python flood fill; used at <= 128 px)."""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32); n = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]: continue
        n += 1; lab[y0, x0] = n; st = [(y0, x0)]
        while st:
            y, x = st.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n; st.append((yy, xx))
    return lab, n

def resize_f(a, size):
    """area/bilinear resize of a float map (PIL 'F' mode) to size x size"""
    from PIL import Image
    if a.shape[0] == size and a.shape[1] == size: return a
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((size, size), Image.BILINEAR), np.float32)

# ---------------------------------------------------------------- analysis --
# roughness and metallic per class (base values; grain and grime modulate roughness)
CLASS_ROUGH = {"asphalt": 0.86, "stone": 0.78, "brick": 0.84, "veg": 0.92, "paint": 0.42,
               "ceramic": 0.55, "glass": 0.05, "metal": 0.38, "chrome": 0.2, "wood": 0.7, "dark": 0.6}
WARM = [(1.0, 0.72, 0.42), (1.0, 0.82, 0.55), (1.0, 0.62, 0.32), (0.75, 0.85, 1.0), (1.0, 0.9, 0.75)]

# REMIX-MATERIALS (9 Nov 2026): what a tile is used for in the maps (tile_class in
# remix_materials.py, from the .gmp lids), because luminance alone cannot tell road paint
# from a raised kerb or a paving joint from a brick wall's mortar. Seen from eye height at a
# grazing angle under path tracing, the wall-strength relief and the parallax displacement
# turned road paint into raised clay (pt-remix-road-paint-embossed-clay-relief) and the
# paving of the plazas into torn bark (pt-remix-rail-track-tile-extreme-normal-relief).
#   road: lids of road blocks. Paint (texels clearly brighter than the asphalt, white or
#         yellow) is flat, the asphalt keeps a fine grain, the structure relief is a fifth,
#         no parallax height.
#   pave: lids of pavement / field blocks (paving, plazas, roofs). Structure relief at 45 %,
#         grain at 70 %, no parallax height: a lid is seen at grazing angles where the
#         runtime's parallax tears and swims.
#   flat (FIX-REMIX-MATERIALS-3, 10 Nov 2026): painted walls and murals, where the luminance is
#         paint, not depth: the tan/grey plank and rendered facades of ste (the painted shadow of
#         an arch, faint wavy plank lines from the upscaler) and the mosaic/graffiti murals.
#         The local-contrast normalisation of the structure band turned their faint lines into
#         full grooves and plateaus: path traced as melted driftwood strata with black cracks
#         (pt-remix-building-arched-facade-carved-wood-strata-relief) and as white wax lumps
#         (pt-remix-graffiti-mural-wax-blob-relief). Structure at 12 %, grain at 35 %, no
#         parallax height: shallow grooves on a flat painted surface. Tiles: FLAT_WALL below
#         plus every wall tile mural_like() finds (several saturated hues: murals, signs).
#   mural: the same gains, but only inside the painted region of the tile (texels within a few
#         texels of saturated paint, which takes in the white patches of a mosaic); the wall
#         around a mural keeps its brick relief. No parallax on the tile.
GROUND_GAIN = {"road": (0.2, 0.5), "pave": (0.45, 0.7), "flat": (0.12, 0.35)}   # (structure, grain) gain
MICRO_GAIN = 0.28    # FIX-REMIX-MATERIALS-4: slope per texel of the scan height (std 1) at 512 px
FLAT_WALL = {"wil": set(), "bil": set(), "ste": set(range(160, 179)) - {163}}
MURAL_WALL = {"wil": {175}, "bil": set(), "ste": {355, 759, 760, 761, 762}}
# FIX-REMIX-MATERIALS-5: inside a mural's painted region the relief is 5 % / 15 % (was the flat class's 12 % / 35 %):
# at arm's length (ste 760, out/fm5_ste1) the mosaic's painted stains still read as a crusty raised skin.
MURAL_GAIN = (0.05, 0.15)

# FIX-REMIX-MATERIALS-4 (ptrmx17-remix-ste-iron-fence-slats-read-as-chrome-mirror-and-clay-by-side): the
# railing and fence tiles (cut-outs of bars, rails, finials, gates) are painted iron. analyse() took the
# bars' long bright stripes (the upscaler's baked cylinder highlight) for oriented metal and chrome
# (ste 52: metal 0.45 / chrome 0.75 at roughness 0.2-0.38), so path traced the slats mirrored the sky in
# shade and the baked highlight read as cream clay in sun. Class "iron": dielectric paint (no metallic
# map), roughness 0.52-0.72 from the paint's grain, the albedo's luminance compressed round a dark mean
# (iron_albedo) so the baked highlight goes and the real light shapes the bar. Curated from a sheet of
# the cut-out tiles the detector calls metal (signs, siding and trellises stay as they were).
IRON_RAIL = {"wil": {217, 623},
             "bil": {25, 382, 421, 422, 623, 850, 859, 869},
             "ste": {47, 52, 77, 408, 457, 510, 909, 987}}

def iron_albedo(rgba, mean=0.17, relief=0.05, desat=0.6):
    """Painted iron from a railing tile: each opaque texel's sRGB luminance becomes
    mean + relief * its clipped z-score (the bars' baked highlight and shadow shrink to a faint
    modulation), its chroma kept at `desat` of the tile's own (smoothed) hue, never brighter than
    the tile was. Alpha untouched."""
    a = rgba[..., 3] >= 128
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    L = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    if not a.any(): return rgba
    mu, sd = float(L[a].mean()), float(L[a].std()) or 1.0
    m = min(mean, mu)
    Lt = np.clip(m + relief * np.clip((L - mu) / sd, -2.0, 2.0), 0.03, 0.6)
    w = a.astype(np.float32)
    chroma = np.stack([gauss(rgb[..., c] * w, 3.0) for c in range(3)], -1) / np.maximum(gauss(L * w, 3.0), 1e-3)[..., None]
    chroma = 1.0 + desat * (np.clip(chroma, 0.5, 1.6) - 1.0)
    out = rgba.copy()
    out[..., :3] = np.where(a[..., None], np.clip(chroma * Lt[..., None] * 255.0, 0, 255), rgba[..., :3]).astype(np.uint8)
    return out

# FIX-REMIX-MATERIALS-4 (ptrmx17-remix-ste-sidewalk-featureless-custard-plane-no-tile-no-normal): ~150
# ground lids' HD art is smooth (the upscaler wiped the grain: ste 516, the ste pavement, is an olive-to-sand
# gradient with grain RMS 0.002 against a median 0.02), so analyse() had nothing to make a normal or a
# roughness variation from and path traced they were one painted plane. For these lids the layer takes
# the micro-surface of the CC0 scan the photo pass picked for the tile (tools/photoreal_tiles.py MATERIALS,
# ambientCG, at its real size on a 4 m block): its colour grain into the albedo (luminance only, the
# tile's own colours stay), its displacement as height into the normal, and both into the roughness.
# The tile -> material list is tools/remix_micro_tiles.json.
def micro_surface(cc0, cls, size, amp=1.0):
    """(albedo gain, height, grime) at `size` for one photo-pass class, or None: gain is a per-texel
    luminance factor around 1, height the displacement high-pass (std ~1), grime the scan's mid band
    (darker patches > 0)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import photoreal_tiles as pt, glob
    from PIL import Image
    mid, metres, ga, ra = pt.MATERIALS.get(cls, (None, 0, 0, 0))
    if mid is None or not glob.glob(os.path.join(cc0, mid, "*_Color.jpg")): return None
    g, hgt = pt.material(cc0, mid, metres, size)
    reps = max(1, int(round(pt.BLOCK_M / metres))); cell = size // reps
    col = Image.open(glob.glob(os.path.join(cc0, mid, "*_Color.jpg"))[0]).convert("L").resize((cell, cell), Image.LANCZOS)
    Lc = np.tile(np.asarray(col).astype(np.float32) / 255.0, (reps, reps))
    if Lc.shape[0] != size: Lc = resize_f(Lc, size)
    mb = gauss(Lc, size / 64.0) - gauss(Lc, size / 8.0)          # ~6 cm .. 50 cm patches: stains, wear
    grime = np.clip(-mb / (mb.std() + 1e-4), -2.5, 2.5) / 2.5
    gain = np.exp(amp * (0.09 * ga * g - 0.08 * grime))
    return gain.astype(np.float32), (amp * ra * hgt).astype(np.float32), (amp * grime).astype(np.float32)

# FIX-REMIX-MATERIALS-9 (prxr1-remix-wil-day-third-first-lawn-slabs-read-as-corrugated-green-roof...): wil 108
# is not a lawn: it is the green box-profile steel roof of the industrial sheds (lids at levels 4-6, many on
# roof slopes, inside grey parapet rims; its neighbours 107-124 are roof panels; field-typed, like many roofs).
# The game's 64 px art is 11 ribs across the tile (~36 cm pitch on a 4 m block): dark 2-3 px bands (the ribs)
# between 3-4 px pans, with rust drips under the fixings. The upscaler drew each rib as a pair of thin black
# lines, and analyse() made those lines grooves, so path traced the roof was a field of black hairlines with a
# dark groove shading each (the filer's "corrugated sheet / ploughed field"). Class "corr": the albedo is the
# paint (the hairlines closed, the baked rib shading divided out, the drips and smudges kept), the ribs are
# real geometry in the normal (raised trapezoids where the art has its dark bands, CORR_GAIN), painted steel
# roughness (satin, rougher in grime), no metal map (paint is a dielectric).
CORRUGATED = {"wil": {108, 121}, "bil": set(), "ste": set()}   # 111/123 are mostly black gutter: no ribs found
CORR_GAIN = 0.9      # rib height (0..1) to slope per texel at 512 px: ~40 deg flanks over ~6 texels

def corrugated(rgba):
    """(albedo uint8 RGBA, rib height float 0..1) for a box-profile roof tile whose ribs run along v."""
    h, w = rgba.shape[:2]
    S = max(h, w) / 512.0
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    Wl = np.array([0.2126, 0.7152, 0.0722], np.float32)
    lum = rgb @ Wl
    hue, sat, val = hsv(rgb)
    sheet = ((hue >= 65) & (hue < 170) & (sat > 0.2) & (lum > 0.04)).astype(np.float32)   # the green sheet, not black gutters
    sheet = (gauss(sheet, 6.0 * S) > 0.5).astype(np.float32)        # its black hairlines and specks belong to it
    # the hairlines: thin dark columns. A horizontal grey closing (max then min over ~9 texels) fills them.
    r = int(round(9 * S)) or 1                    # a rib's line pair spans up to ~16 texels
    def hmax(a): return np.max(np.stack([np.roll(a, i, 1) for i in range(-r, r + 1)]), 0)
    def hmin(a): return np.min(np.stack([np.roll(a, i, 1) for i in range(-r, r + 1)]), 0)
    closed = np.stack([hmin(hmax(rgb[..., c])) for c in range(3)], -1)
    # never keep the closing's own over-brightening: no texel brighter than the unclosed paint around it
    ref = np.stack([gauss(rgb[..., c], 6.0 * S) for c in range(3)], -1)
    closed = np.minimum(closed, np.maximum(ref * 1.15, rgb))
    closed = np.where(sheet[..., None] > 0, closed, rgb)
    cl = closed @ Wl
    # the ribs: where the art's (smoothed) column profile is darker than its median, over sheet columns
    colw = sheet.sum(0) + 1e-3
    col = (lum * sheet).sum(0) / colw
    k = np.exp(-0.5 * (np.arange(-16, 17) / (4.0 * S)) ** 2); k /= k.sum()
    colp = np.concatenate([col[-16:], col, col[:16]])
    sm = np.convolve(colp, k, "same")[16:-16]
    ribc = (sm < np.median(sm) - 0.004).astype(np.float32) * (sheet.mean(0) > 0.3)
    # trapezoid: soften the flanks to ~6 texels, flat crown and pan
    kk = np.exp(-0.5 * (np.arange(-16, 17) / (2.2 * S)) ** 2); kk /= kk.sum()
    rp = np.concatenate([ribc[-16:], ribc, ribc[:16]])
    ribh = np.clip(np.convolve(rp, kk, "same")[16:-16], 0, 1)
    rib = np.tile(ribh[None, :], (h, 1)) * gauss(sheet, 1.5 * S + 0.5)
    # the baked rib shading out of the paint: luminance over its column profile (the drips are not columnar)
    cc = (cl * sheet).sum(0) / colw
    ccs = np.convolve(np.concatenate([cc[-16:], cc, cc[:16]]), k, "same")[16:-16]
    flat = float(np.median(ccs))
    gain = np.where(sheet > 0, flat / np.maximum(ccs[None, :], 1e-3), 1.0)
    # the upscaler's faint leaf-vein smudges: halve the 2..12 texel band of the luminance
    L2 = cl * gain
    band = gauss(L2, 2.0 * S) - gauss(L2, 12.0 * S)
    L3 = np.clip(L2 - 0.5 * band * sheet, 0, 1)
    out_rgb = closed * (L3 / np.maximum(cl, 1e-3))[..., None]
    out = rgba.copy()
    out[..., :3] = np.clip(np.rint(out_rgb * 255), 0, 255).astype(np.uint8)
    return out, rib.astype(np.float32)

def mural_like(rgba):
    """True for a wall tile that is mostly paint of several hues (murals, mosaics, painted
    signs): at least 12 % saturated, bright texels spread over three or more 30-degree hue bins."""
    a = np.asarray(rgba)
    step = max(1, a.shape[0] // 64)
    a = a[::step, ::step]
    if (a[..., 3] < 128).mean() > 0.05: return False
    hue, sat, val = hsv(a[..., :3].astype(np.float32) / 255.0)
    s = (sat > 0.4) & (val > 0.3)
    bins = np.bincount((hue[s] // 30).astype(int) % 12, minlength=12) / s.size
    return bool(s.mean() > 0.12 and (bins > 0.02).sum() >= 3)

def analyse(rgba, wrap=True, kind="tile", seed="", windows=False, structure_gain=1.0, ground=None, micro=None, glass_mask=None, corr=None):
    """Maps for one texture (uint8 RGBA, any size). Returns a dict:
    normal (h, w, 3 float, DirectX tangent space), rough / rough_wet / metal / height
    (uint8 h, w; metal and height None when the texture has none), displace (float,
    displace_in for the material), emissive (uint8 RGBA or None), cls (class shares)."""
    h, w = rgba.shape[:2]
    S = max(h, w) / 512.0                        # texel scale vs a 512 px tile
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    vis = rgba[..., 3] >= 128
    visf = vis.astype(np.float32)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    if not vis.all():                            # fill the cut-out with the visible mean so its edge is not a cliff
        m = gauss(lum * visf, 4 * S + 1, wrap) / np.maximum(gauss(visf, 4 * S + 1, wrap), 1e-3)
        lum = np.where(vis, lum, m)
    hue, sat, val = hsv(rgb)

    # --- height: structure band (shapes) and grain band (surface) ---------------
    s_lo, s_hi = max(0.9 * S, 0.6), max(13.0 * S, 2.5)
    d = gauss(lum, s_lo, wrap) - gauss(lum, s_hi, wrap)
    loc = np.sqrt(np.maximum(gauss(d * d, s_hi * 1.5, wrap), 0)) + 0.035
    Hs = np.tanh(1.4 * d / loc)                   # plateaus and grooves, -1..1
    g = lum - gauss(lum, max(1.1 * S, 0.6), wrap)
    gs = np.sqrt(np.maximum(gauss(g * g, 6 * S + 1, wrap), 0)) + 1e-3
    Hg = np.clip(g / (np.sqrt(np.mean(g * g)) + 1e-3), -3, 3) / 3.0
    struct_amp = float(np.clip(np.sqrt(np.mean(d * d)) / 0.06, 0.25, 1.0))   # flat tiles get little relief

    # --- orientation (corrugation, slats, girders) -------------------------------
    gx, gy = grad(gauss(lum, 0.8 * S + 0.3, wrap), wrap)
    so = 5 * S + 1
    jxx, jyy, jxy = gauss(gx * gx, so, wrap), gauss(gy * gy, so, wrap), gauss(gx * gy, so, wrap)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (np.maximum(jxx + jyy, 0) + 1e-5)
    energy = np.sqrt(np.maximum(jxx + jyy, 0))                   # local edge energy

    # --- classes -----------------------------------------------------------------
    neutral = sat < 0.16
    redb = ((hue < 38) | (hue > 340)) & (sat > 0.25) & (sat < 0.8) & (val > 0.15) & (val < 0.75)
    wood = (hue >= 18) & (hue < 50) & (sat > 0.28) & (val < 0.5) & (coh > 0.45)
    veg = (hue >= 65) & (hue < 170) & (sat > 0.22) & (val < 0.7)
    paint = (sat > 0.5) & (val > 0.35) & ~redb & ~veg
    fine_e = gauss(np.abs(Hg), 3 * S + 1, wrap)
    smooth = gs < 0.018
    metal = neutral & (coh > 0.75) & (energy > 0.03) & (val > 0.18) & (val < 0.75) & (fine_e > 0.2)
    metal = gauss(metal.astype(np.float32), 2 * S + 0.5, wrap) > 0.5     # coherent patches, not lone edges
    if kind == "car" or (metal & vis).mean() < 0.04: metal &= False   # the car tool classifies trim itself; a few
                                                  # oriented stone edges on a facade are not a metal surface
    chrome = metal & (lum > 0.62) & (lum > gauss(lum, 3 * S + 1, wrap) + 0.08)
    ceramic = smooth & (val > 0.55) & ~paint & (gs < 0.008)
    dark = val < 0.12
    asphalt = neutral & (val < 0.42) & ~metal & ~dark
    stone = neutral & (val >= 0.42) & ~metal & ~ceramic

    # glass: dark-ish, smooth, fairly neutral or blue-grey rectangles inside a brighter frame
    glass = np.zeros((h, w), bool); emissive = None; panes = 0
    if windows and kind in ("tile", "prop"):
        n = 128 if max(h, w) >= 128 else max(h, w)
        small_l = resize_f(lum, n); small_sat = resize_f(sat, n); small_v = resize_f(visf, n)
        small_b = resize_f(rgb[..., 2] - rgb[..., 0], n)
        # a pane: a smooth (few edges), not saturated patch, darker than or bluer than its
        # surroundings, or framed by strong edges; kept below only when it is a filled
        # rectangle of window size whose ring is much busier than its inside
        around = gauss(small_l, 6.0, wrap)
        e_s = resize_f(energy, n)
        e_ref = float(np.percentile(e_s, 70)) + 1e-4
        cand = (small_v > 0.5) & (small_sat < 0.4) & (e_s < 0.45 * e_ref)
        cand &= (small_l < around + 0.03) | (small_b > 0.03)
        lab, nl = components(cand)
        keep = np.zeros(nl + 1, bool); lit = np.zeros(nl + 1, np.int32) - 1
        for k in range(1, nl + 1):
            ys, xs = np.nonzero(lab == k)
            a = len(ys)
            if a < 0.004 * n * n or a > 0.16 * n * n: continue
            bh, bw = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
            if a < 0.75 * bh * bw or max(bh, bw) > 4 * min(bh, bw) or min(bh, bw) < 5: continue
            y0, y1, x0, x1 = max(ys.min() - 3, 0), min(ys.max() + 4, n), max(xs.min() - 3, 0), min(xs.max() + 4, n)
            if ys.min() == 0 and ys.max() == n - 1 or xs.min() == 0 and xs.max() == n - 1: continue   # wall running through
            cy = (ys.min() + ys.max()) / 2 / n
            if bh < 0.08 * n or bh < 0.6 * bw or not 0.12 < cy < 0.88: continue   # sills, cornices, shadow bands: wide and thin, at the tile's edge
            box = small_l[y0:y1, x0:x1]; inner = lab[y0:y1, x0:x1] == k; ebox = e_s[y0:y1, x0:x1]
            if box[~inner].size == 0: continue
            framed = ebox[~inner].mean() > 2.5 * (ebox[inner].mean() + 1e-4)
            darker = box[~inner].mean() - small_l[ys, xs].mean() > 0.05
            if not (framed and (darker or small_b[ys, xs].mean() > 0.03)): continue
            keep[k] = True
            hsh = int(hashlib.md5(f"{seed}:{ys.min()}:{xs.min()}".encode()).hexdigest()[:8], 16)
            if hsh % 100 < 48: lit[k] = hsh % len(WARM)
        if keep.any():
            pane = keep[lab]
            glass = resize_f(pane.astype(np.float32), max(h, w))[:h, :w] > 0.5 if h == w else glass
            panes = int(keep.sum())
            litmap = lit[lab]
            if (litmap >= 0).any() and h == w:
                em = np.zeros((n, n, 3), np.float32)
                for c in range(len(WARM)):
                    em[litmap == c] = WARM[c]
                # a soft falloff inside the pane (curtains, room depth), from its own texture
                em_big = np.stack([resize_f(em[..., i], h) for i in range(3)], -1)
                shade = np.clip(0.55 + 0.45 * (1 - lum / max(lum.max(), 1e-3)), 0, 1)[..., None]
                em_big = em_big * shade * glass[..., None]
                emissive = np.zeros((h, w, 4), np.uint8); emissive[..., 3] = 255
                emissive[..., :3] = np.clip(em_big * 255, 0, 255).astype(np.uint8)
    if glass_mask is not None:                     # FIX-REMIX-MATERIALS-6: curated panes (tools/fix_window_glass.py)
        glass = glass | (np.asarray(glass_mask, bool)[:h, :w] if glass_mask.shape[:2] == (h, w)
                         else resize_f(np.asarray(glass_mask, np.float32), max(h, w))[:h, :w] > 0.5)
    glass &= vis

    # --- roughness ---------------------------------------------------------------
    rough = np.full((h, w), CLASS_ROUGH["stone"] - 0.03, np.float32)
    for m, key in ((asphalt, "asphalt"), (stone, "stone"), (redb, "brick"), (wood, "wood"), (veg, "veg"),
                   (dark, "dark"), (paint, "paint"), (ceramic, "ceramic"), (metal, "metal"), (chrome, "chrome"), (glass, "glass")):
        rough[m] = CLASS_ROUGH[key]
    grime = np.clip((gauss(lum, 10 * S + 1, wrap) - gauss(lum, 2 * S + 0.5, wrap)) * 3.0, -0.15, 0.15)   # darker than around: grime, rougher
    busy = np.clip(gs / 0.05, 0, 1)
    rough = rough + 0.12 * (busy - 0.4) + grime
    rough = np.where(glass, CLASS_ROUGH["glass"] + 0.04 * busy, rough)
    rough = gauss(rough, 0.6 * S + 0.2, wrap)
    rough = np.clip(rough, 0.03, 0.98)

    # wet: everything glossier; puddles in the low areas of ground-like tiles, water in joints
    groundish = float((asphalt | stone | redb).mean()) > 0.55 and panes == 0 and float(paint.mean()) < 0.15
    groundish = groundish or ground == "road"            # FIX-REMIX-MATERIALS-6: every road lid takes the rain (the class said so already)
    wet = rough * 0.5 + 0.02
    if groundish:
        rng = np.random.default_rng(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))
        noise = gauss(rng.standard_normal((h, w)).astype(np.float32), 22 * S + 2, wrap)
        noise /= np.abs(noise).max() + 1e-6
        low = gauss(lum, 8 * S + 1, wrap); low = (low - low.mean()) / (low.std() + 1e-3)
        pud = np.clip((0.35 - (0.75 * noise + 0.25 * np.tanh(low))) * 4.0, 0, 1)      # 0 dry .. 1 puddle
        wet = wet * (1 - pud) + 0.025 * pud
        wet = np.where(Hs < -0.55, np.minimum(wet, 0.08), wet)
    wet = np.clip(np.where(glass, rough, wet), 0.02, 0.98)

    # --- metallic ----------------------------------------------------------------
    metal_map = None
    if (metal & vis).mean() > 0.01:
        mm = np.zeros((h, w), np.float32); mm[metal] = 0.45; mm[chrome] = 0.75
        metal_map = (np.clip(gauss(mm, 0.6 * S + 0.2, wrap), 0, 1) * 255).astype(np.uint8)

    # --- normal --------------------------------------------------------------------
    k_s = 2.6 * struct_amp * structure_gain / S   # structure slope per texel at 512 px
    k_g = 0.9 / S
    flat = paint & (sat > 0.6)                     # signs and road paint: a painted surface, no relief
    if ground in GROUND_GAIN:
        k_s *= GROUND_GAIN[ground][0]; k_g *= GROUND_GAIN[ground][1]
    if ground == "road":
        # road paint: brighter than the asphalt around it by a clear step (white, or yellow);
        # flat, and its edge does not become a step (the paint mask is grown by a few texels)
        base = gauss(lum, 24 * S + 2, wrap)
        rp = (lum > base + 0.12) & ((sat < 0.3) | ((hue >= 30) & (hue < 65)))
        rp = gauss(rp.astype(np.float32), 2.5 * S + 0.5, wrap) > 0.05
        flat = flat | rp
        rough = np.where(rp, np.clip(rough - 0.08, 0.3, 0.98), rough)   # paint a little smoother than asphalt
    if ground == "road":
        # FIX-REMIX-MATERIALS-3: a road lid is asphalt and paint, never a glossy stone: the pale
        # teal ste roads fell in no class (tinted, not neutral) and kept 0.69-0.75, which at the
        # grazing morning sun gave the paint and the hatching a sky sheen and a speckle of glints
        # (pt-remix-plaza-paving-posterised-patches-sky-streak-reflection, ...-firefly-speck-clouds).
        rough = np.where(rp, np.maximum(rough, 0.62), np.maximum(rough, 0.86))
    elif ground == "pave":
        rough = np.where(metal | chrome | glass, rough, np.maximum(rough, 0.74))
    if micro is not None:                          # FIX-REMIX-MATERIALS-4: scan micro-surface (micro_surface)
        mh, mg = micro
        rough = np.clip(rough + 0.07 * mg - 0.025 * np.clip(mh, -2, 2), 0.55, 0.98)   # grime rougher, worn tops smoother
    if ground == "corr":                           # FIX-REMIX-MATERIALS-9: painted steel roof, never metal or chrome
        metal &= False; chrome &= False; metal_map = None
        rough = gauss(np.clip(0.50 + 0.10 * (busy - 0.4) + 0.8 * grime, 0.40, 0.72), 0.6 * S + 0.2, wrap)
    if ground == "iron":                           # FIX-REMIX-MATERIALS-4: painted iron, never metal or chrome
        metal &= False; chrome &= False
        rough = gauss(np.clip(0.62 + 0.12 * (busy - 0.4) + 0.6 * grime, 0.52, 0.72), 0.6 * S + 0.2, wrap)
    w_s = np.where(flat, 0.25, 1.0); w_g = np.where(glass, 0.15, 1.0)
    if glass_mask is not None:                     # a curated pane is a flat sheet: no structure or grain relief
        w_s = np.where(glass, 0.0, w_s); w_g = np.where(glass, 0.0, w_g)
    if ground == "mural":
        colourful = ((sat > 0.25) & (val > 0.25)).astype(np.float32)
        region = gauss(colourful, 16 * S + 1, wrap) > 0.06
        region = gauss(region.astype(np.float32), 1.5 * S + 0.5, wrap)          # soft edge, 0..1
        w_s = w_s * (1 - region * (1 - MURAL_GAIN[0]))
        w_g = w_g * (1 - region * (1 - MURAL_GAIN[1]))
    if ground == "corr":                           # the ribs are geometry; the paint has only a faint grain
        k_s = 0.0; k_g *= 0.25
    Hn = (k_s * Hs * w_s + k_g * Hg * w_g) * visf
    if corr is not None:
        Hn = Hn + CORR_GAIN / S * corr * 6.0 * visf
    if micro is not None:
        Hn = Hn + MICRO_GAIN / S * micro[0] * visf
    nx, ny = grad(Hn, wrap)
    # slope in "units of texels", keep the tilt sane
    n = np.stack([-nx, ny, np.ones_like(nx)], -1)  # DirectX tangent space (+V down the image)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)

    # --- height for displacement ------------------------------------------------------
    rel = 1.0 - float((paint | glass | veg | dark).mean())     # the share of the tile that is a surface with relief
    if glass_mask is not None:                     # curated panes are recessed in the height map, not a reason to drop it
        rel = 1.0 - float(((paint | veg | dark) & ~glass).mean())
    signish = float((paint & vis).mean())
    height = None; displace = 0.0
    if kind in ("tile", "prop") and ground is None and panes == 0 and signish < 0.08 and rel > 0.6 and struct_amp > 0.45:
        H = 0.5 + 0.5 * (0.85 * Hs + 0.15 * Hg * 2)
        H = np.clip(gauss(H, 0.5 * S + 0.2, wrap), 0, 1)
        if glass_mask is not None and glass.any():  # FIX-REMIX-MATERIALS-6: a flat pane set back behind its frame
            H = np.where(gauss(glass.astype(np.float32), 1.0 * S + 0.3, wrap) > 0.5, min(float(np.percentile(H, 3)), 0.25), H)
        height = (H * 255).astype(np.uint8)
        displace = round(0.006 + 0.012 * struct_amp, 4)

    vn = max(int(vis.sum()), 1)
    cls = {k: round(float((m & vis).sum()) / vn, 3) for k, m in
           (("asphalt", asphalt), ("stone", stone), ("brick", redb), ("wood", wood), ("veg", veg), ("paint", paint),
            ("ceramic", ceramic), ("metal", metal), ("chrome", chrome), ("glass", glass))}
    cls["panes"] = panes; cls["struct"] = round(struct_amp, 2)
    return {"normal": n, "rough": (rough * 255).astype(np.uint8), "rough_wet": (wet * 255).astype(np.uint8),
            "metal": metal_map, "height": height, "displace": displace, "emissive": emissive, "cls": cls,
            "groundish": groundish}

def mural_albedo(rgba, keep=0.4, pale_min=0.68):
    """FIX-REMIX-MATERIALS-5 (pt-remix-graffiti-mural-wax-blob-relief, residual at arm's length): the upscaler
    painted bumps, specks and soft shadows into a mosaic's pale pieces (ste 760: the cream patches), which path
    traced as raised white lumps even with the mural class's flat normals. Inside the painted region (as analyse()
    finds it), a pale low-chroma texel's luminance is pulled to the smooth luminance of the pale texels around
    it (sigma 1.5 texels per 64 px), `keep` of its own detail left; its hue is kept, the dark grout and the
    coloured pieces are not touched. Only the layer's albedo copy changes (the HD tile is the texture key)."""
    a = rgba[..., :3].astype(np.float32) / 255.0
    mx, mn = a.max(-1), a.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-3)
    S = rgba.shape[0] / 64.0
    colourful = ((sat > 0.25) & (mx > 0.25)).astype(np.float32)
    region = gauss(colourful, 16 * S + 1) > 0.06
    pale = region & (sat < 0.3) & (mx > pale_min)
    if not pale.any(): return rgba
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    w = pale.astype(np.float32)
    smooth = gauss(lum * w, 1.5 * S) / np.maximum(gauss(w, 1.5 * S), 1e-3)
    target = keep * lum + (1 - keep) * smooth
    ratio = np.where(pale, target / np.maximum(lum, 1e-3), 1.0)
    out = rgba.copy()
    out[..., :3] = np.clip(a * ratio[..., None] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def deband(rgba, low=0.018, high=0.05):
    """FIX-REMIX-MATERIALS-3: the upscaler posterised the flat road tiles into contour-map
    patches (stepped low-contrast bands, ghost lettering). The mid band of the colour (between
    ~1.5 and ~24 texels at 512 px) is soft-thresholded: steps under `low` go, steps over `high`
    (a kerb, a lane line, a crack) stay whole; then a faint seeded grain. Alpha untouched."""
    h, w = rgba.shape[:2]
    S = max(h, w) / 512.0
    x = rgba[..., :3].astype(np.float32) / 255.0
    lo_ = np.stack([gauss(x[..., c], 24 * S + 2) for c in range(3)], -1)
    fine = np.stack([gauss(x[..., c], 1.5 * S + 0.3) for c in range(3)], -1)
    mid = fine - lo_
    mag = np.abs(mid).max(-1, keepdims=True)
    keep = np.clip((mag - low) / (high - low), 0, 1)
    y = lo_ + mid * keep + (x - fine)
    rng = np.random.default_rng(12345)
    g = gauss(rng.standard_normal((h, w)).astype(np.float32), 0.7 * S + 0.2)
    y = y + (0.012 / (g.std() + 1e-6)) * g[..., None] * np.clip(y, 0.05, 1)
    out = rgba.copy()
    out[..., :3] = np.clip(np.rint(y * 255), 0, 255).astype(np.uint8)
    return out

def road_paint_mask(a):
    """FIX-REMIX-MATERIALS-6: the painted / built parts of a road lid (lane dashes, kerb tops, yellow
    lines, kerb shadows), as a 0..1 float mask, from sRGB floats: bright (luminance > 0.55), saturated,
    under half the tile's median luminance, or over 0.14 from the tile's median colour (a grey kerb)."""
    mx, mn = a.max(-1), a.min(-1)
    L = a.mean(-1)
    med = np.median(a.reshape(-1, 3), 0)
    far = np.abs(a - med).max(-1) > 0.14
    return ((L > 0.55) | ((mx - mn) > 0.25) | (L < 0.5 * np.median(L)) | far).astype(np.float32)


def road_detail_albedo(rgba, donor, donor_plain, detail_sigma=40.0):
    """FIX-REMIX-MATERIALS-6 (ptrmx26-remix-wil-day-third-road-lids-alternate-...-checkerboard): the
    re-authored road paint (assets/textures_hd/roads/<style>) exists only for the dashed lids, so a
    road alternated rows of mottled, cracked asphalt (276/278 on wil) and the upscaler's smooth plane
    (275/277). A road lid without re-authored art takes its asphalt from a sibling that has it (the
    donor: same style, closest plain tile): the donor's paint (dashes it has and this lid has not) is
    filled from the donor's own asphalt a quarter-tile away, the lid's asphalt keeps its own low
    frequencies shifted to the donor's mean asphalt colour and takes the donor's detail (cracks,
    mottling: the ratio to its blur, sigma `detail_sigma` texels at 512 px); the lid's own paint and
    kerbs are kept. Layer albedo only (the HD tile stays the texture key). rgba / donor uint8 RGBA
    at the same size; donor_plain the donor's plain HD tile (where its paint is)."""
    h, w = rgba.shape[:2]
    S = h / 512.0
    a = rgba[..., :3].astype(np.float32) / 255.0
    d = donor[..., :3].astype(np.float32) / 255.0
    dp = road_paint_mask(donor_plain[..., :3].astype(np.float32) / 255.0)
    dp = np.maximum(dp, road_paint_mask(d))
    dp = (gauss(dp, 5 * S + 1) > 0.02).astype(np.float32)
    sig = detail_sigma * S
    wd = 1.0 - dp                                        # the donor's asphalt only, so a dash leaves no halo
    dlo = np.stack([gauss(d[..., c] * wd, sig) for c in range(3)], -1) / np.maximum(gauss(wd, sig), 1e-3)[..., None]
    detail = d / np.maximum(dlo, 1e-3)
    hole = dp > 0.5                                      # the dashes: detail from the donor's asphalt elsewhere
    for sh in ((h // 4, 0), (-h // 4, 0), (h // 2, 0), (0, w // 4), (0, -w // 4), (h // 2, w // 2),
               (h // 4, w // 4), (-h // 4, -w // 4), (3 * h // 8, w // 3)):
        if not hole.any(): break
        src = np.roll(detail, sh, (0, 1)); ok = ~np.roll(dp > 0.5, sh, (0, 1))
        put = hole & ok; detail[put] = src[put]; hole &= ~put
    if hole.any(): detail[hole] = 1.0
    detail = np.clip(detail, 0.5, 1.6)
    dmean = d[dp < 0.5].mean(0) if (dp < 0.5).any() else d.reshape(-1, 3).mean(0)
    own = road_paint_mask(a)
    own = np.clip(gauss(own, 1.5 * S + 0.5) * 1.6, 0, 1)
    asph = own < 0.5
    if asph.sum() < 16: return rgba
    wa = 1.0 - own                                       # the lid's own low frequencies from its asphalt only
    olo = np.stack([gauss(a[..., c] * wa, sig) for c in range(3)], -1) / np.maximum(gauss(wa, sig), 1e-3)[..., None]
    shift = dmean / np.maximum(a[asph].mean(0), 1e-3)
    y = np.clip(olo * shift * detail, 0, 1)
    y = own[..., None] * a + (1 - own[..., None]) * y
    out = rgba.copy()
    out[..., :3] = np.clip(np.rint(y * 255), 0, 255).astype(np.uint8)
    return out

# ------------------------------------------------------------ leaf albedo --
def veg_dark(rgba):
    """True for a vegetation tile (hedge, bush, lawn) whose leaves are too dark to path
    trace: at least half its visible texels leaf-coloured and their mean sRGB luminance
    under 0.2 (linear albedo under ~0.03; a real leaf is 0.08-0.15)."""
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    vis = rgba[..., 3] >= 128
    if vis.mean() < 0.05: return False
    hue, sat, val = hsv(rgb[vis][None])
    veg = ((hue >= 65) & (hue < 170) & (sat > 0.22))[0]
    lum = rgb[vis] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return bool(veg.mean() > 0.5 and lum.mean() < 0.2)

LEAF = np.array([0.30, 0.42, 0.16], np.float32)    # sRGB leaf green (linear albedo ~0.13)
# The foliage tiles (hedges, bushes, lawns, the cut-out tree and shrub sprites) whose leaves
# veg_dark() finds too dark, reviewed on a sheet: Industrial's green-painted metal panels
# (ste 320-381) and window frames (ste 90/91) and bil 580 (pipework) pass veg_dark() but are
# not leaves, so the lift is a curated list, not the detector alone.
VEG_LIFT = {"wil": {108, 477, 837, 841, 849, 854, 856, 860, 862},
            "bil": {219, 220, 695, 696, 854},
            "ste": {470, 471, 472, 526, 530}}
# Hedge blocks: the same tile on the lid and the sides of a closed block, cut out at 64 %. In
# the plain renderer the holes show the lawn; path traced at dusk they look into the block's
# unlit inside and stay black (rmat_bil1, 17:30: 17 % of the top under 0.03). A hedge is a
# dense mass, so the layer draws these opaque, the holes a darker leaf shade (depth between
# the leaves). The cut-out shrub sprites keep their alpha.
VEG_SOLID = {"bil": {854}, "ste": {470}}

def veg_albedo(rgba, lo=0.14, target=0.30, kmax=4.0, solid=False):
    """REMIX-MATERIALS (pt-remix-hedge-top-black-holes): the Remix albedo of a dark leaf tile.
    The bil/ste hedge tile (854 / 470) has opaque leaves at sRGB (6,14,4): median luminance
    2/255, which path traces as black speckle. The visible texels' sRGB luminance is lifted
    affinely, L' = lo + k (L - Lmin), k so the mean reaches `target` (capped at kmax): the
    leaf structure keeps its order and most of its contrast, nothing stays black. Colour is
    the texel's own chroma where it is bright enough to have one, the tile's leaf hue pulled
    half way to a leaf green where it is near black. The alpha (the cutout) is bit-exact.
    Only the layer's albedo changes: the game's tile and its Remix hash stay as they are."""
    out = rgba.copy()
    W = np.array([0.2126, 0.7152, 0.0722], np.float32)
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    vis = rgba[..., 3] >= 128
    lum = rgb @ W
    v = lum[vis]; lmin = float(np.percentile(v, 1)); mean = float(v.mean())
    k = min(kmax, (target - lo) / max(mean - lmin, 1e-3))
    newl = np.clip(lo + k * (lum - lmin), lo, 0.85)
    chroma = rgb / np.maximum(lum[..., None], 1e-3)                  # colour at unit luminance
    tile_c = np.median(chroma[vis & (lum > 0.03)], axis=0) if (vis & (lum > 0.03)).any() else LEAF / float(LEAF @ W)
    leaf_c = 0.5 * tile_c + 0.5 * LEAF / float(LEAF @ W)
    own = np.clip((lum - 0.02) / 0.06, 0, 1)[..., None] * 0.85       # a near-black texel's own hue is noise
    c = own * np.clip(chroma, 0, 3) + (1 - own) * leaf_c
    c = c / np.maximum(c @ W, 1e-3)[..., None]
    if solid:                                            # the holes: a darker leaf, a little of the neighbours' light
        near = gauss(np.where(vis, newl, 0), 3.0) / np.maximum(gauss(vis.astype(np.float32), 3.0), 1e-3)
        newl = np.where(vis, newl, np.clip(0.8 * near, 0.16, 0.26))
        c = np.where(vis[..., None], c, leaf_c)
        out[..., 3] = 255
    out[..., :3] = np.clip(c * newl[..., None] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out

# ----------------------------------------------------------------- preview --
def shade(rgba, n, light=(-0.6, -0.5, 0.62)):
    """the albedo lit by one raking light through the normal map (+ ambient): a quick look at the relief"""
    L = np.array([light[0], -light[1], light[2]], np.float32); L /= np.linalg.norm(L)
    ndl = np.clip((n * L).sum(-1), 0, 1)
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    return (np.clip(rgb * (0.25 + 1.1 * ndl[..., None]), 0, 1) * 255).astype(np.uint8)

def naive_normal(rgba):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import remix_materials as rm
    return rm.normal_map(rgba[..., :3])

def preview(out, paths, size=256):
    from PIL import Image, ImageDraw
    rows = []
    for p in paths:
        im = Image.open(p).convert("RGBA")
        if im.size[0] != im.size[1] and max(im.size) > 512: im = im.resize((512, 512))
        rgba = np.asarray(im)
        r = analyse(rgba, True, seed=os.path.basename(p), windows=os.environ.get("PBR_WINDOWS") == "1")
        cells = [rgba[..., :3], shade(rgba, naive_normal(rgba)), shade(rgba, r["normal"]),
                 ((r["normal"] * 0.5 + 0.5) * 255).astype(np.uint8)[..., [0, 1, 2]],
                 np.repeat(r["rough"][..., None], 3, -1), np.repeat(r["rough_wet"][..., None], 3, -1),
                 np.repeat((r["metal"] if r["metal"] is not None else np.zeros_like(r["rough"]))[..., None], 3, -1),
                 np.repeat((r["height"] if r["height"] is not None else np.full_like(r["rough"], 40))[..., None], 3, -1),
                 (r["emissive"][..., :3] if r["emissive"] is not None else np.zeros_like(rgba[..., :3]))]
        rows.append(([Image.fromarray(c).resize((size, size)) for c in cells], os.path.basename(p), r))
    heads = ["albedo", "old normal (lit)", "new normal (lit)", "new normal", "roughness", "wet roughness", "metallic", "height", "night windows"]
    W = len(heads) * (size + 4) + 4; H = 22 + len(rows) * (size + 18)
    S = Image.new("RGB", (W, H), (20, 20, 24)); d = ImageDraw.Draw(S)
    for i, t in enumerate(heads): d.text((4 + i * (size + 4), 5), t, fill=(230, 230, 230))
    for j, (cells, name, r) in enumerate(rows):
        y = 22 + j * (size + 18)
        for i, c in enumerate(cells): S.paste(c, (4 + i * (size + 4), y))
        c = r["cls"]; top = sorted(((v, k) for k, v in c.items() if k not in ("panes", "struct")), reverse=True)[:3]
        d.text((4, y + size + 2), f"{name}  disp {r['displace']}  panes {c['panes']}  struct {c['struct']}  " +
               " ".join(f"{k} {v:.2f}" for v, k in top) + ("  ground" if r["groundish"] else ""), fill=(200, 200, 200))
    S.save(out); print(out, S.size)

if __name__ == "__main__":
    if sys.argv[1] == "preview": preview(sys.argv[2], sys.argv[3:])
