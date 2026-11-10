#!/usr/bin/env python3
"""Photo-material pass over GTA2's HD tiles (ASSET-BUILDINGS): buildings, streets and props
get the surface of real, photo-scanned materials while every window, door, cornice, sign,
kerb and road marking stays exactly where the original 64 px art put it.

Why a transfer and not a re-render. SDXL with the SDXL tile ControlNet (strength 0.5 to
1.0) was tried first (docs/photoreal-tiles.md): up to 0.85 it hugs the ESRGAN init and
adds little; at 1.0 it invents crackle and lattice patterns over plain walls. A tile is
a whole block face (two window bays), so a diffusion model has no real-world scale to
work at. Here the scale is explicit instead:

  base      the HD tile already shipped (assets/textures_hd, 512 px): the colours,
            layout and structure, i.e. the city as the player knows it.
  material  one CC0 photo-scanned material per tile (ambientCG, see MATERIALS), picked by
            the tile's material class (classify: Qwen3-VL-8B on the original art, or a
            hand label), tiled at its real size on a 4 m block.
  out       base * grain * relief, where grain is the material's luminance high-pass
            (its pores, aggregate, scratches, stains; never its bricks or slabs, so it
            cannot fight the art's own structure) and relief is the material's
            displacement high-pass shaded by a light from above-left (micro shadows that
            survive in a fixed-function renderer, which has no normal maps). Both fade
            out over openings, glass, lettering and ornament (the art's own local
            contrast), and over cutout texels.

The material repeats a whole number of times across the tile, so a tile still wraps
seamlessly. Alpha is the HD tile's own alpha, untouched.

The result is a separate set, gta2dx9_textures_photo/<style>/tile_NNNN.dds, which the
renderer loads before gta2dx9_textures_hd/ (`[renderer] photo_tiles`); never on an RTX
Remix device, whose PBR layer is keyed by the HD set's texture hashes.

    photoreal_tiles.py usage    <game/data> <out.json>             which tiles are walls / ground
    photoreal_tiles.py classify <64px dir> <usage.json> <style> <labels.json> [--hd dir] (GPU, resumable)
    photoreal_tiles.py build    <hd dir> <labels.json> <cc0 dir> <out dir> [--esrgan dir] [--tiles a,b] [--jobs N]
    photoreal_tiles.py sheet    <64px dir> <hd dir> <photo dir> <png> --tiles a,b,c
    photoreal_tiles.py fetch    <cc0 dir>                           download the CC0 materials
    photoreal_tiles.py resharpen <photo dir> <hd dir> <out dir> --tiles a,b   restore the art-scale contrast
    photoreal_tiles.py frames   <photo dir> <labels.json> <usage.json> <out dir> --style bil
                                        lift thin true-black frame bars of wall tiles (pm12)
    photoreal_tiles.py lotfield <tile dir> <out dir> --tiles a,b --target r,g,b
                                        flatten the asphalt's low-frequency tone of a tile family (pmq1)

Needs numpy, scipy, Pillow; classify also torch + transformers.
"""
import argparse, glob, json, os, sys, zipfile
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# class -> (ambientCG id, metres the 2K image covers, grain amount, relief amount)
MATERIALS = {
    "plaster":       ("Plaster001",        2.0, 0.55, 0.50),
    "painted_render":("PaintedPlaster017", 2.0, 0.45, 0.35),
    "stone":         ("Concrete031",       2.0, 0.55, 0.60),
    "concrete":      ("Concrete034",       2.0, 0.60, 0.55),
    "brick":         ("Concrete044A",      1.0, 0.50, 0.45),
    "painted_metal": ("PaintedMetal004",   1.0, 0.35, 0.25),
    "rusty_metal":   ("PaintedMetal009",   1.0, 0.55, 0.40),
    "bare_metal":    ("Metal012",          1.0, 0.35, 0.20),
    "wood":          ("Wood067",           1.0, 0.45, 0.30),
    "marble":        ("Marble012",         2.0, 0.30, 0.15),
    "glass":         (None,                0.0, 0.00, 0.00),
    "asphalt":       ("Asphalt026B",       2.0, 0.75, 0.55),
    "paving":        ("Concrete034",       2.0, 0.60, 0.50),
    "dirt":          ("Ground054",         2.0, 0.70, 0.55),
    "grass":         ("Grass004",          2.0, 0.70, 0.50),
    "gravel":        ("Gravel022",         1.0, 0.70, 0.60),
    "roof":          ("Concrete044A",      2.0, 0.60, 0.45),
    "skip":          (None,                0.0, 0.00, 0.00),   # signs, lettering, water, anything else
}
ORGANIC = {"grass", "dirt", "gravel"}   # the SD rendering of these is better than ESRGAN + grain
CLASSES = [c for c in MATERIALS if c != "skip"] + ["skip"]
BLOCK_M = 4.0           # a GTA2 block face, in metres
SIZE = 512

# ----------------------------------------------------------------------------- helpers
def gauss(a, s):
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(a, s, mode="wrap")

def lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722

def read_dds_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0

_mat_cache = {}
def material(cc0, mid, metres, size=SIZE):
    """(grain, height) of a material at the tile's scale: luminance high-pass as a ratio
    around 1, displacement high-pass around 0, both wrapping exactly across the tile."""
    key = (mid, metres, size)
    if key in _mat_cache: return _mat_cache[key]
    reps = max(1, int(round(BLOCK_M / metres)))
    cell = size // reps
    col = Image.open(glob.glob(os.path.join(cc0, mid, "*_Color.jpg"))[0]).convert("RGB").resize((cell, cell), Image.LANCZOS)
    dsp = glob.glob(os.path.join(cc0, mid, "*_Displacement.jpg"))
    L = lum(np.asarray(col).astype(np.float32) / 255.0)
    D = (np.asarray(Image.open(dsp[0]).convert("L").resize((cell, cell), Image.LANCZOS)).astype(np.float32) / 255.0
         if dsp else L.copy())
    L = np.tile(L, (reps, reps)); D = np.tile(D, (reps, reps))
    if L.shape[0] != size:      # size not a multiple of reps: stretch the last few texels
        L = np.asarray(Image.fromarray(L).resize((size, size), Image.BICUBIC)); D = np.asarray(Image.fromarray(D).resize((size, size), Image.BICUBIC))
    s = size / 16.0             # keep features under ~25 cm: grain, never structure
    g = np.log(np.clip(L, 0.02, 1)) - np.log(np.clip(gauss(L, s), 0.02, 1))
    g /= max(g.std(), 1e-4)
    h = D - gauss(D, s); h /= max(h.std(), 1e-4)
    _mat_cache[key] = (g.astype(np.float32), h.astype(np.float32))
    return _mat_cache[key]

def art_weight(rgba, size=SIZE):
    """1 on plain wall/ground, fading to ~0.25 over the art's own detail: openings, glass,
    lettering, ornament (local contrast of the original at 64 px scale) and cutouts."""
    L = lum(rgba[..., :3])
    s = size / 64.0
    m = gauss(L, 1.5 * s); v = np.sqrt(np.maximum(gauss(L * L, 1.5 * s) - m * m, 0))
    w = np.clip(1.0 - (v - 0.04) / 0.16, 0.35, 1.0)
    dark = np.clip((0.12 - m) / 0.08, 0, 1)            # voids and dark glass keep their look
    w = w * (1 - 0.7 * dark)
    w = gauss(w, s)
    return w * (rgba[..., 3] > 0.5)

def transfer(rgba, cls, cc0):
    mid, metres, ga, ra = MATERIALS[cls]
    if mid is None: return None
    g, h = material(cc0, mid, metres, rgba.shape[0])
    w = art_weight(rgba, rgba.shape[0])
    # relief: slope of the height toward a light from above-left (texture v points down)
    sh = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) * 0.7 + (np.roll(h, 1, 1) - np.roll(h, -1, 1)) * 0.3
    sh /= max(sh.std(), 1e-4)
    k = np.exp(w * (0.085 * ga * g + 0.06 * ra * sh))
    out = rgba.copy()
    out[..., :3] = np.clip(rgba[..., :3] * k[..., None], 0, 1)
    return out

# ----------------------------------------------------------------------------- usage
def road_lids(gmp):
    """tiles used as the lid of a road block (ground type 1): the painted road markings live
    there (tools/reauthor_road_markings.py re-authors them in the HD set), so their base stays
    the shipped HD tile"""
    import struct
    d = open(gmp, "rb").read(); off = 6; c = {}
    while off + 8 <= len(d):
        tag = d[off:off + 4].decode("latin1"); size = struct.unpack_from("<I", d, off + 4)[0]
        c[tag] = (off + 8, size); off += 8 + size
    o, _ = c["DMAP"]; base = o + 256 * 256 * 4
    ncol = struct.unpack_from("<I", d, base)[0]; nb = base + 4 + ncol * 4
    nblk = struct.unpack_from("<I", d, nb)[0]; bdata = nb + 4
    road = set()
    for i in range(nblk):
        b = struct.unpack_from("<5HBB", d, bdata + i * 12)
        if b[6] & 3 == 1 and b[4] & 0x3FF not in (0, 1023): road.add(b[4] & 0x3FF)
    return sorted(road)

def cmd_usage(a):
    """Which tiles the maps put on building sides and which on lids (ground, roofs), per
    style: tools/facade_depth.py's map reader (wil/bil/ste .gmp)."""
    import facade_depth
    out = {}
    for st in ("wil", "bil", "ste"):
        g = os.path.join(a.data, st + ".gmp")
        if os.path.exists(g):
            side, lid, flat = facade_depth.usage(g)
            # animated tiles (water, neon, screens) stay as they are: frames must match
            import dump_style_tiles
            _, anims = dump_style_tiles.gmp_tiles_and_anims(g)
            anim = sorted({b for b, _, _, fr in anims} | {f for _, _, _, fr in anims for f in fr})
            out[st] = {"side": side, "lid": lid, "flat": flat, "anim": anim, "road": road_lids(g)}
    json.dump(out, open(a.out, "w"))

# ----------------------------------------------------------------------------- classify
WALL = ["plaster", "painted_render", "stone", "concrete", "brick", "painted_metal", "rusty_metal",
        "bare_metal", "wood", "marble", "glass"]
GROUND = ["asphalt", "paving", "concrete", "dirt", "grass", "gravel", "roof", "wood", "bare_metal", "brick"]
PROMPT = ("This is a texture tile from a 1999 top-down city game; it covers {where}. "
          "Answer two lines. Line 1: yes if the tile shows a sign, logo, lettering, a neon or "
          "billboard picture, a screen or water, else no. Line 2: the real material of most of "
          "the {main}, exactly one word from: {words}.")

def cmd_classify(a):
    """One material class per used tile: Qwen3-VL-8B looks at the tile (the HD version when
    there is one) and answers whether it is a sign (-> skip) and which material, from the wall
    list for tiles used mostly on building sides and the ground list for lids. Resumable."""
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    usage = json.load(open(a.usage))[a.style]
    side, lid = usage.get("side", {}), usage.get("lid", {})
    tiles = sorted(set(map(int, side)) | set(map(int, lid)))
    out = json.load(open(a.labels)) if os.path.exists(a.labels) else {}
    mid = "Qwen/Qwen3-VL-8B-Instruct"
    proc = AutoProcessor.from_pretrained(mid)
    model = AutoModelForImageTextToText.from_pretrained(mid, torch_dtype=torch.bfloat16, device_map="cuda").eval()
    only = {int(x) for x in a.tiles.split(",")} if a.tiles else None
    anim = set(usage.get("anim", []))
    for t in tiles:
        if t in anim:
            out[str(t)] = {"cls": "skip", "mat": "anim", "sign": False, "side": int(side.get(str(t), 0)), "lid": int(lid.get(str(t), 0))}
            continue
        if only is not None and t not in only: continue
        if str(t) in out and only is None: continue
        p = os.path.join(a.tiles_dir, "tile_%04d.tga" % t)
        if not os.path.exists(p): continue
        ns, nl = int(side.get(str(t), 0)), int(lid.get(str(t), 0))
        is_side = ns >= nl
        words = WALL if is_side else GROUND
        where = ("part of the outside wall of a building, seen from the street" if is_side
                 else "the ground (road, pavement, park) or a flat roof, seen from above")
        main = "wall around the windows and doors" if is_side else "surface"
        hd = os.path.join(a.hd, "tile_%04d.dds" % t) if a.hd else ""
        im = (Image.open(hd).convert("RGB").resize((384, 384), Image.LANCZOS) if hd and os.path.exists(hd)
              else Image.open(p).convert("RGB").resize((384, 384), Image.NEAREST))
        msgs = [{"role": "user", "content": [{"type": "image", "image": im},
                 {"type": "text", "text": PROMPT.format(where=where, main=main, words=", ".join(words))}]}]
        inp = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                       return_tensors="pt").to(model.device)
        with torch.no_grad():
            ids = model.generate(**inp, max_new_tokens=12, do_sample=False)
        ans = proc.batch_decode(ids[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip().lower()
        lines = [l.strip(" .:-*") for l in ans.splitlines() if l.strip()]
        sign = bool(lines) and lines[0].replace("line 1", "").strip(" :").startswith("yes")
        rest = " ".join(lines[1:]) if len(lines) > 1 else ans
        word = next((w for w in words if w in rest.replace(" ", "_") or w.replace("_", " ") in rest), "skip")
        out[str(t)] = {"cls": "skip" if sign else word, "mat": word, "sign": sign, "side": ns, "lid": nl}
        print(t, out[str(t)]["cls"], repr(ans), flush=True)
        if len(out) % 25 == 0: json.dump(out, open(a.labels, "w"), indent=0)
    json.dump(out, open(a.labels, "w"), indent=0)

# ----------------------------------------------------------------------------- build
def write_dds(dst, rgba):
    """rgba float 0..1 -> DXT1 (opaque) or DXT5 DDS with a full mip chain; unlinks first, so it
    never writes through a hard link into a stage"""
    from pack_textures_dds import dds_header, encode_level
    alpha_raw = (rgba[..., 3] * 255 + 0.5).astype(np.uint8)
    has_alpha = alpha_raw.min() < 255
    rgb = Image.fromarray((np.clip(rgba[..., :3], 0, 1) * 255 + 0.5).astype(np.uint8))
    alpha = Image.fromarray(alpha_raw)
    fmt = "DXT5" if has_alpha else "DXT1"
    levels = []; w = h = rgb.size[0]
    cur = rgb.copy(); cur.putalpha(alpha)
    while True:
        levels.append(encode_level(cur, fmt))
        if w == 1 and h == 1: break
        w, h = max(1, w // 2), max(1, h // 2)
        cur = rgb.resize((w, h), Image.LANCZOS); cur.putalpha(alpha.resize((w, h), Image.BOX))
    if os.path.exists(dst): os.unlink(dst)
    with open(dst, "wb") as f:
        f.write(dds_header(rgb.size[0], rgb.size[1], len(levels), fmt.encode(), len(levels[0])))
        for lv in levels: f.write(lv)

def _build_one(args):
    hd, cc0, out_dir, t, cls, esr, keep_base = args
    src = os.path.join(hd, "tile_%04d.dds" % t)
    if not os.path.exists(src): return t, "missing"
    rgba = read_dds_rgba(src)
    e = os.path.join(esr, "tile_%04d.tga" % t) if esr else ""
    if e and os.path.exists(e) and not keep_base and cls not in ORGANIC:
        # the clean ESRGAN upscale as the base: no SD artefacts (cracked bricks, crackle on
        # plain concrete); organic ground and road lids keep the shipped HD tile
        rgba[..., :3] = np.asarray(Image.open(e).convert("RGB").resize(rgba.shape[:2][::-1], Image.LANCZOS)).astype(np.float32) / 255.0
    res = transfer(rgba, cls, cc0)
    if res is None:
        d0 = os.path.join(out_dir, "tile_%04d.dds" % t)
        if os.path.exists(d0): os.unlink(d0)      # a corrected-to-skip tile must not keep an old photo tile
        return t, "skip"
    write_dds(os.path.join(out_dir, "tile_%04d.dds" % t), res)
    return t, cls

def cmd_build(a):
    from multiprocessing import Pool
    labels = json.load(open(a.labels))
    if a.fixes:     # hand corrections: {style: {tile: class}}; a tile fixed to "skip" loses its photo tile
        for t, c in json.load(open(a.fixes)).get(a.style, {}).items():
            if c not in MATERIALS: raise SystemExit("fixes: unknown class %r for tile %s" % (c, t))
            if str(t) in labels: labels[str(t)] = dict(labels[str(t)], cls=c) if isinstance(labels[str(t)], dict) else c
    os.makedirs(a.out, exist_ok=True)
    road = set(json.load(open(a.usage))[a.style].get("road", [])) if a.usage else set()
    want = [int(x) for x in a.tiles.split(",")] if a.tiles else sorted(map(int, labels))
    jobs = [(a.hd, a.cc0, a.out, t, (labels[str(t)]["cls"] if isinstance(labels[str(t)], dict) else labels[str(t)]), a.esrgan, t in road)
            for t in want if str(t) in labels]
    counts = {}
    with Pool(a.jobs) as p:
        for t, r in p.imap_unordered(_build_one, jobs):
            counts[r] = counts.get(r, 0) + 1
    print(json.dumps(counts, sort_keys=True))

# ----------------------------------------------------------------------------- sheet
def cmd_sheet(a):
    S = 384
    tiles = [int(x) for x in a.tiles.split(",")]
    W = Image.new("RGB", (3 * (S + 4), len(tiles) * (S + 4)), (30, 30, 30))
    for y, t in enumerate(tiles):
        n = "tile_%04d" % t
        ims = [Image.open(os.path.join(a.tiles_dir, n + ".tga")).convert("RGB").resize((S, S), Image.NEAREST),
               Image.open(os.path.join(a.hd, n + ".dds")).convert("RGB").resize((S, S), Image.LANCZOS)]
        p = os.path.join(a.photo, n + ".dds")
        ims.append(Image.open(p).convert("RGB").resize((S, S), Image.LANCZOS) if os.path.exists(p) else Image.new("RGB", (S, S)))
        for x, im in enumerate(ims): W.paste(im, (x * (S + 4), y * (S + 4)))
    W.save(a.png)

# ----------------------------------------------------------------------------- frames
FRAME_FLOOR = 0.17      # luminance of a lifted frame bar (brick in these tiles is ~0.25-0.3)
FRAME_BLACK = 0.075     # texels darker than this are candidates
FRAME_WIDE = 22         # texels (of 512): black wider than this is a void (doorway, deep recess) and stays

def frame_floor(rgba, floor=FRAME_FLOOR, black=FRAME_BLACK, wide=FRAME_WIDE):
    """pm12: a window's frame bars are true black in the art (8-16/255). From the first-person
    eye 10-25 cm off a wall one bar fills a third of the frame as a black band. Lift THIN black
    structures (frame bars, sash bars, sills' shadow lines) to a dark painted-wood tone, keeping
    their own shading as grain; black areas wider than `wide` texels (doorways, voids) keep
    their look, and so do the rest of the tile's texels. Returns (rgba, lifted fraction)."""
    from scipy import ndimage as ndi
    size = rgba.shape[0]; k = size / 512.0
    rgb = rgba[..., :3]
    L = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    b = (L < black) & (rgba[..., 3] > 0.5)
    r = max(2, int(round(wide * k)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]; disk = xx * xx + yy * yy <= r * r
    # the wide black areas, regrown inside the black mask by r texels: an opening alone leaves
    # disk-shaped blobs (and round holes once their surroundings lift); the regrowth fills a
    # region's corners back while reaching only r texels along a thin bar that meets it
    void = ndi.binary_dilation(ndi.binary_opening(b, disk), structure=np.ones((3, 3), bool), iterations=r, mask=b)
    thin = b & ~void
    m = ndi.gaussian_filter(ndi.binary_dilation(thin, iterations=2).astype(np.float32), 1.2 * k)
    grain = np.clip(L - ndi.gaussian_filter(L, 3 * k), -0.04, 0.04)
    paint = np.array([1.06, 1.0, 0.90], np.float32)
    lift = np.maximum(paint * (floor + 1.5 * grain)[..., None], rgb)
    out = rgba.copy()
    out[..., :3] = rgb * (1 - m[..., None]) + lift * m[..., None]
    return out, float(thin.mean())

def cmd_frames(a):
    """photo tiles of building sides: frame_floor over each wall tile of `style` (side use more
    than lid use, a wall class, no cutout). Reads <photo dir>, writes <out dir> (may be the same)."""
    labels = json.load(open(a.labels)); use = json.load(open(a.usage))[a.style]
    os.makedirs(a.out, exist_ok=True)
    walls = set(WALL) - {"glass"}
    want = [int(x) for x in a.tiles.split(",")] if a.tiles else sorted(map(int, labels))
    done = []
    for t in want:
        src = os.path.join(a.photo, "tile_%04d.dds" % t)
        if not os.path.exists(src): continue
        lab = labels.get(str(t)); cls = lab["cls"] if isinstance(lab, dict) else lab
        if not a.tiles and (cls not in walls or use["side"].get(str(t), 0) <= use["lid"].get(str(t), 0)): continue
        rgba = read_dds_rgba(src)
        if not a.tiles and rgba[..., 3].min() < 0.5: continue        # fences, lattices: bars are see-through art
        Lm = float((rgba[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)).mean())
        if not a.tiles and Lm < a.min_mean: continue                   # dark materials: black is their look
        out, frac = frame_floor(rgba, a.floor)
        if frac < a.min_frac or (not a.tiles and frac > a.max_frac): continue   # >max: a dark pattern, not frames
        write_dds(os.path.join(a.out, "tile_%04d.dds" % t), out)
        done.append((t, round(frac, 4)))
    print(json.dumps({"style": a.style, "lifted": len(done), "tiles": done}))

# ----------------------------------------------------------------------------- resharpen
def band(L, k):
    from scipy import ndimage as ndi
    return ndi.gaussian_filter(L, 1.5 * k, mode="wrap") - ndi.gaussian_filter(L, 10.0 * k, mode="wrap")

def cmd_resharpen(a):
    """pm-photo-tiles-roof-and-brick-softer-than-plain-hd: a photo tile built on the clean ESRGAN base can
    carry less contrast at the art's own scale (a roof's corrugation, a wall's mortar) than the plain HD
    tile, so in the street views it reads softer. Here each listed photo tile's own band (gaussian 1.5 to 10
    texels of 512: the art's structure, not the fine crackle the SD upscale put into the HD set) is raised
    until its energy matches the HD tile's band (gain at most --max-gain); nothing is taken from the HD
    tile itself. Tiles already as sharp are left alone. Reads <photo dir>, writes <out dir>."""
    os.makedirs(a.out, exist_ok=True)
    done = []
    for t in [int(x) for x in a.tiles.split(",") if x]:
        src = os.path.join(a.photo, "tile_%04d.dds" % t); hd = os.path.join(a.hd, "tile_%04d.dds" % t)
        if not (os.path.exists(src) and os.path.exists(hd)): continue
        ph = read_dds_rgba(src); h = read_dds_rgba(hd)
        if h.shape != ph.shape:
            h = np.asarray(Image.fromarray((h * 255).astype(np.uint8)).resize(ph.shape[:2][::-1], Image.LANCZOS)).astype(np.float32) / 255
        k = ph.shape[0] / 512.0
        bp = band(lum(ph[..., :3]), k); bh = band(lum(h[..., :3]), k)
        m = ph[..., 3] > 0.5
        sp, sh = float(bp[m].std()), float(bh[m].std())
        if sp <= 1e-4 or sp >= a.target * sh: continue
        g = min(a.max_gain, a.target * sh / sp)
        out = ph.copy()
        out[..., :3] = np.clip(ph[..., :3] + ((g - 1.0) * bp)[..., None], 0, 1)
        write_dds(os.path.join(a.out, "tile_%04d.dds" % t), out)
        done.append((t, round(sp / sh, 3), round(g, 2)))
    print(json.dumps({"resharpened": len(done), "tiles": done}))

# ----------------------------------------------------------------------------- lotfield
def cmd_lotfield(a):
    """pmq1-bil-lot-tile-seam: the tiles of one asphalt surface (the bil lots: interior 737 and 745,
    kerb edges 754 and 742, bay line 767) were drawn in the 64 px art with different tones (737 eight
    levels darker) blended by soft gradients, and the HD/photo rendition kept a tone of its own per tile.
    The street views' tone match (src/renderer.cpp DdsBaseRgb) then tints each tile by ONE factor
    toward the district's asphalt median, which cannot make two tiles meet along an edge: the lot read as
    a patchwork of hard-edged squares. Here the asphalt body of each tile (the texels within --tol of
    the tile's median luminance, i.e. not the kerb, its shadow line or the paint) has its low-frequency
    colour (gaussian --sigma texels of 512, normalised over the body) replaced by --target, the tone
    match's own median, so every tile of the family meets its neighbour at the same colour and the
    runtime tint is ~1 for all of them. The grain, cracks, kerb and paint are kept as they are.
    Reads <tile dir>/tile_NNNN.dds (photo/ or roads/), writes <out dir>."""
    from scipy import ndimage as ndi
    os.makedirs(a.out, exist_ok=True)
    target = np.array([float(v) for v in a.target.split(",")], np.float32) / 255.0
    done = []
    for t in [int(x) for x in a.tiles.split(",") if x]:
        src = os.path.join(a.src, "tile_%04d.dds" % t)
        if not os.path.exists(src): continue
        ph = read_dds_rgba(src)
        k = ph.shape[0] / 512.0
        rgb = ph[..., :3]
        L = lum(ndi.gaussian_filter(rgb, (2 * k, 2 * k, 0), mode="reflect"))
        opaque = ph[..., 3] > 0.5
        med = float(np.median(L[opaque]))
        body = (np.abs(L - med) < a.tol / 255.0) & opaque
        body = ndi.binary_opening(body, iterations=2)
        w = body.astype(np.float32)
        sig = a.sigma * k
        den = ndi.gaussian_filter(w, sig, mode="reflect")
        low = np.stack([ndi.gaussian_filter(rgb[..., c] * w, sig, mode="reflect") for c in range(3)], -1) / np.maximum(den, 1e-4)[..., None]
        gain = target[None, None, :] / np.maximum(low, 1e-3)
        # full gain on the body, fading out over 3 texels into the kerb / paint (they keep their own tone)
        wb = np.clip(ndi.gaussian_filter(w, 3 * k, mode="reflect") * 1.5, 0, 1)[..., None]
        out = ph.copy()
        out[..., :3] = np.clip(rgb * (1.0 + (gain - 1.0) * wb), 0, 1)
        write_dds(os.path.join(a.out, "tile_%04d.dds" % t), out)
        before = (rgb[body].mean(0) * 255).round(1).tolist(); after = (out[..., :3][body].mean(0) * 255).round(1).tolist()
        done.append((t, round(float(body.mean()), 2), before, after))
    print(json.dumps({"lotfield": len(done), "tiles": done}))

# ----------------------------------------------------------------------------- fetch
def cmd_fetch(a):
    import urllib.request
    os.makedirs(a.cc0, exist_ok=True)
    for mid in sorted({m[0] for m in MATERIALS.values() if m[0]}):
        if glob.glob(os.path.join(a.cc0, mid, "*_Color.jpg")): continue
        z = os.path.join(a.cc0, mid + "_2K-JPG.zip")
        req = urllib.request.Request("https://ambientcg.com/get?file=%s_2K-JPG.zip" % mid, headers={"User-Agent": "gta2-asset-tool"})
        open(z, "wb").write(urllib.request.urlopen(req, timeout=300).read())
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.endswith(("_Color.jpg", "_Displacement.jpg")) and "/" not in n:
                    os.makedirs(os.path.join(a.cc0, mid), exist_ok=True)
                    open(os.path.join(a.cc0, mid, n), "wb").write(zf.read(n))
        print("fetched", mid)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("usage"); s.add_argument("data"); s.add_argument("out")
    s = sub.add_parser("classify"); s.add_argument("tiles_dir"); s.add_argument("usage"); s.add_argument("style"); s.add_argument("labels")
    s.add_argument("--hd", default="", help="HD tile dir (tile_NNNN.dds) shown to the model instead of the 64 px art")
    s.add_argument("--tiles", default="", help="only these tiles (re-classified even when present)")
    s = sub.add_parser("build"); s.add_argument("hd"); s.add_argument("labels"); s.add_argument("cc0"); s.add_argument("out")
    s.add_argument("--tiles", default=""); s.add_argument("--jobs", type=int, default=4)
    s.add_argument("--fixes", default="", help="JSON {style: {tile: class}} of hand-corrected labels (tools/photo_label_fixes.json)")
    s.add_argument("--esrgan", default="", help="ESRGAN upscale dir (tile_NNNN.tga) to use as the base colour")
    s.add_argument("--usage", default="", help="usage.json: road lids keep the HD base"); s.add_argument("--style", default="wil")
    s = sub.add_parser("sheet"); s.add_argument("tiles_dir"); s.add_argument("hd"); s.add_argument("photo"); s.add_argument("png")
    s.add_argument("--tiles", required=True)
    s = sub.add_parser("fetch"); s.add_argument("cc0")
    s = sub.add_parser("resharpen"); s.add_argument("photo"); s.add_argument("hd"); s.add_argument("out")
    s.add_argument("--tiles", required=True); s.add_argument("--target", type=float, default=1.0)
    s.add_argument("--max-gain", type=float, default=2.0)
    s = sub.add_parser("frames"); s.add_argument("photo"); s.add_argument("labels"); s.add_argument("usage"); s.add_argument("out")
    s.add_argument("--style", required=True); s.add_argument("--tiles", default="", help="only these tiles (no wall test)")
    s.add_argument("--floor", type=float, default=FRAME_FLOOR); s.add_argument("--min-frac", type=float, default=0.002)
    s.add_argument("--max-frac", type=float, default=0.20); s.add_argument("--min-mean", type=float, default=0.20)
    s = sub.add_parser("lotfield"); s.add_argument("src"); s.add_argument("out")
    s.add_argument("--tiles", required=True); s.add_argument("--target", default="77,80,64")
    s.add_argument("--sigma", type=float, default=40.0); s.add_argument("--tol", type=float, default=20.0)
    a = ap.parse_args()
    globals()["cmd_" + a.cmd](a)
