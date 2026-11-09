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
GROUND_GAIN = {"road": (0.2, 0.5), "pave": (0.45, 0.7)}   # (structure, grain) gain

def analyse(rgba, wrap=True, kind="tile", seed="", windows=False, structure_gain=1.0, ground=None):
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
    Hn = (k_s * Hs * np.where(flat, 0.25, 1.0) + k_g * Hg * np.where(glass, 0.15, 1.0)) * visf
    nx, ny = grad(Hn, wrap)
    # slope in "units of texels", keep the tilt sane
    n = np.stack([-nx, ny, np.ones_like(nx)], -1)  # DirectX tangent space (+V down the image)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)

    # --- height for displacement ------------------------------------------------------
    rel = 1.0 - float((paint | glass | veg | dark).mean())     # the share of the tile that is a surface with relief
    signish = float((paint & vis).mean())
    height = None; displace = 0.0
    if kind in ("tile", "prop") and ground is None and panes == 0 and signish < 0.08 and rel > 0.6 and struct_amp > 0.45:
        H = 0.5 + 0.5 * (0.85 * Hs + 0.15 * Hg * 2)
        H = np.clip(gauss(H, 0.5 * S + 0.2, wrap), 0, 1)
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
