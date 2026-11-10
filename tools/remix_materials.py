#!/usr/bin/env python3
"""Builds an RTX Remix material-replacement mod for GTA2's world tiles on Linux.

NVIDIA's own route to this is the RTX Remix Toolkit's AI Texture Tools, which
upscale a captured texture and generate its PBR maps, and its ingestion, which
writes the DDS files and the USD material layer. The Toolkit is a Windows-only
Omniverse application (see docs/remix-materials.md), so this is the same
pipeline written for Linux:

  1. The hash. Remix identifies a game texture by an XXH3-64 of its texels as
     uploaded; the renderer dumps every world tile it uploads as a 64x64 TGA
     (gta2dx9.ini: dump_tiles=1 -> gta2dx9_tiles\\tile_NNNN.tga), and the hash of
     that TGA's pixel bytes is the material's key. Checked against the water mod's
     known hashes (tile 608 -> A8B83A83052A85C0), which this reproduces exactly.
  2. The maps. Albedo from a high-resolution set (Real-ESRGAN x4 from
     tools/upscale_textures.py, optionally refined by tools/enhance_textures_sd.py),
     a tangent-space normal map from the albedo's luminance (height by
     band-pass, Sobel slopes), and a roughness map from local contrast and
     brightness (bright, flat texels - metal, glass - smoother; dark, busy
     texels - brick, tarmac - rougher). Metallic is left to the material default.
  3. The files. DDS with full mip chains in the formats the runtime reads
     directly: BC3 (DXT5) albedo with the cutout alpha, BC5 normals as unsigned
     octahedral - the one convention the runtime decodes (the Toolkit converts
     on ingestion; see make_water_mod.py) - and BC4 roughness. BC7 would be a
     little better for albedo; there is no BC7 encoder here without the
     Toolkit, and BC3 is what every DirectX 9 game of this era shipped.
  4. The layer. mod.usda overriding /RootNode/Looks/mat_<HASH>/Shader with
     AperturePBR_Opacity and the three textures, one material per tile hash,
     exactly the shape of the mod's own gta2rtx and gta2water layers.

    remix_materials.py <tile dump dir> <mod dir> --hd <hd dir> [<hd dir> ...] [--sd <dir>] [--size 256]

<tile dump dir> holds tile_NNNN.tga at 64x64 (the hashes); each --hd dir the
same names at high resolution (the first one that has a tile wins); --sd names
a folder whose tiles replace the albedo where present. Several districts can be
merged into one mod by running once per district with the same <mod dir>: the
layer is rewritten from everything found in <mod dir>/textures.

Under Remix the replacement applies in every view - the runtime has no notion
of the renderer's camera modes - so the top-down view shows the same art at
higher resolution, which is the intent: recognisable from above, detailed up
close. Needs numpy, Pillow and xxhash.
"""
import argparse, os, re, struct, sys, time
import numpy as np
import xxhash
from PIL import Image, ImageFilter

MDL = "AperturePBR_Opacity"

# ---------------------------------------------------------------- images --
def read_tga(path):
    d = open(path, "rb").read()
    if d[2] != 2 or d[16] != 32: raise ValueError(f"{path}: not a 32-bit uncompressed TGA")
    w = d[12] | (d[13] << 8); h = d[14] | (d[15] << 8)
    px = np.frombuffer(d[18:18 + w * h * 4], np.uint8).reshape(h, w, 4).copy()   # B G R A
    if not (d[17] & 0x20): px = px[::-1].copy()                                   # bottom-up file
    return px

def remix_hash(bgra_topdown):
    """XXH3-64 of the texels as the renderer uploads them: ARGB little-endian, rows top-down."""
    return "%016X" % xxhash.xxh3_64_intdigest(np.ascontiguousarray(bgra_topdown).tobytes())

def to_rgba(bgra):
    return bgra[..., [2, 1, 0, 3]]

def resize(rgba, size):
    im = Image.fromarray(rgba, "RGBA").resize((size, size), Image.LANCZOS)
    return np.asarray(im)

# ------------------------------------------------------------------ maps --
def normal_map(rgb, strength=2.2, wrap=True):
    """Tangent-space normals from a height field derived from the albedo: the
    band-passed luminance (fine detail over the large-scale shading), so a brick
    course reads as a ridge and a painted stripe does not become a step."""
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32) / 255.0
    im = Image.fromarray((lum * 255).astype(np.uint8), "L")
    fine = np.asarray(im.filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255.0
    coarse = np.asarray(im.filter(ImageFilter.GaussianBlur(6.0)), np.float32) / 255.0
    height = fine - coarse
    pad = np.pad(height, 1, mode="wrap" if wrap else "edge")
    # Sobel
    gx = (pad[:-2, 2:] + 2 * pad[1:-1, 2:] + pad[2:, 2:]) - (pad[:-2, :-2] + 2 * pad[1:-1, :-2] + pad[2:, :-2])
    gy = (pad[2:, :-2] + 2 * pad[2:, 1:-1] + pad[2:, 2:]) - (pad[:-2, :-2] + 2 * pad[:-2, 1:-1] + pad[:-2, 2:])
    n = np.stack([-gx * strength, gy * strength, np.ones_like(gx)], -1)   # x = +U, y = +V (DirectX: y down flipped below)
    n[..., 1] = -n[..., 1]   # DirectX tangent space: +V points down the image
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n

def roughness_map(rgb):
    """0 smooth .. 1 rough from local contrast and brightness, in 0..255."""
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32) / 255.0
    im = Image.fromarray((lum * 255).astype(np.uint8), "L")
    mean = np.asarray(im.filter(ImageFilter.GaussianBlur(3.0)), np.float32) / 255.0
    var = np.asarray(Image.fromarray(((lum - mean) ** 2 * 255 * 8).clip(0, 255).astype(np.uint8), "L")
                     .filter(ImageFilter.GaussianBlur(3.0)), np.float32) / 255.0
    rough = 0.55 + 0.35 * np.clip(var * 3.0, 0, 1) - 0.25 * np.clip((mean - 0.6) / 0.4, 0, 1)
    return (np.clip(rough, 0.2, 0.98) * 255).astype(np.uint8)

# ------------------------------------------------------------------- DDS --
def halve(a):
    h, w = a.shape[:2]
    h2, w2 = max(h // 2, 1), max(w // 2, 1)
    a = a[:h2 * 2 if h > 1 else 1, :w2 * 2 if w > 1 else 1]
    ry, rx = (2 if h > 1 else 1), (2 if w > 1 else 1)
    return a.reshape(h2, ry, w2, rx, *a.shape[2:]).mean(axis=(1, 3))

def blocks4(a):
    """(h, w, c) -> (bh, bw, 16, c) 4x4 blocks, edge padded."""
    h, w = a.shape[:2]
    bh, bw = (h + 3) // 4, (w + 3) // 4
    padded = np.pad(a, ((0, bh * 4 - h), (0, bw * 4 - w)) + ((0, 0),) * (a.ndim - 2), mode="edge")
    return padded.reshape(bh, 4, bw, 4, *a.shape[2:]).transpose(0, 2, 1, 3, *range(4, a.ndim + 2)).reshape(bh, bw, 16, *a.shape[2:])

def bc4_blocks(channel):
    """One BC4 block per 4x4 texels of a 0..255 channel, 8-value mode (from make_water_mod.py)."""
    blocks = blocks4(channel[..., None])[..., 0].astype(np.int32)
    bh, bw = blocks.shape[:2]
    hi = blocks.max(-1); lo = blocks.min(-1)
    span = np.maximum(hi - lo, 1)[..., None]
    step = np.clip(np.rint((hi[..., None] - blocks) * 7.0 / span), 0, 7).astype(np.uint64)
    step[(hi == lo)] = 0
    index = np.array([0, 2, 3, 4, 5, 6, 7, 1], np.uint64)[step]
    bits = np.zeros((bh, bw), np.uint64)
    for i in range(16):
        bits |= index[..., i] << np.uint64(3 * i)
    out = np.zeros((bh, bw, 8), np.uint8)
    out[..., 0] = hi; out[..., 1] = lo
    for b in range(6):
        out[..., 2 + b] = ((bits >> np.uint64(8 * b)) & np.uint64(0xFF)).astype(np.uint8)
    return out

def bc1_colour_blocks(rgb, four_colour=True):
    """BC1 colour blocks by range fit along the block's principal axis (good enough for
    albedo at 256-512 px; the Toolkit's compressor would do slightly better)."""
    blocks = blocks4(rgb).astype(np.float32)        # bh bw 16 3
    bh, bw = blocks.shape[:2]
    mean = blocks.mean(2, keepdims=True)
    centred = blocks - mean
    # principal axis per block via the covariance's power iteration (3 steps)
    cov = np.einsum("...ki,...kj->...ij", centred, centred)
    axis = np.ones((bh, bw, 3), np.float32)
    for _ in range(4):
        axis = np.einsum("...ij,...j->...i", cov, axis)
        axis /= np.linalg.norm(axis, axis=-1, keepdims=True) + 1e-6
    proj = np.einsum("...ki,...i->...k", centred, axis)
    lo = mean[..., 0, :] + axis * proj.min(-1, keepdims=True)
    hi = mean[..., 0, :] + axis * proj.max(-1, keepdims=True)
    def to565(c):
        c = np.clip(np.rint(c), 0, 255).astype(np.int32)
        return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)
    def from565(v):
        return np.stack([((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31], -1).astype(np.float32)
    c0, c1 = to565(hi), to565(lo)
    swap = c0 < c1
    c0s = np.where(swap, c1, c0); c1s = np.where(swap, c0, c1)
    same = c0s == c1s
    p0, p1 = from565(c0s), from565(c1s)
    palette = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], -2)   # bh bw 4 3
    d = ((blocks[..., :, None, :] - palette[..., None, :, :]) ** 2).sum(-1)    # bh bw 16 4
    idx = d.argmin(-1).astype(np.uint32)
    idx[same] = 0
    bits = np.zeros((bh, bw), np.uint32)
    for i in range(16):
        bits |= idx[..., i] << np.uint32(2 * i)
    out = np.zeros((bh, bw, 8), np.uint8)
    out[..., 0] = c0s & 255; out[..., 1] = c0s >> 8; out[..., 2] = c1s & 255; out[..., 3] = c1s >> 8
    for b in range(4):
        out[..., 4 + b] = (bits >> np.uint32(8 * b)) & 255
    return out

def bc3(rgba):
    alpha = bc4_blocks(rgba[..., 3])
    colour = bc1_colour_blocks(rgba[..., :3])
    return np.concatenate([alpha, colour], -1).tobytes()

def bc5(rg):
    return np.concatenate([bc4_blocks(rg[..., 0]), bc4_blocks(rg[..., 1])], -1).tobytes()

def bc4(r):
    return bc4_blocks(r).tobytes()

def dds(path, levels, fourcc, bytes_per_block):
    """levels: list of encoded mip blobs; first is mip 0 at (h, w) given by levels_shape."""
    data, (h, w) = levels
    header = struct.pack("<7I44x", 124, 0xA1007, h, w, len(data[0]), 0, len(data))
    pixfmt = struct.pack("<2I4s5I", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    caps = struct.pack("<5I", 0x401008, 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"DDS " + header + pixfmt + caps + b"".join(data))

def mips(a):
    out = [a]
    while out[-1].shape[0] > 1 or out[-1].shape[1] > 1:
        out.append(halve(out[-1]))
    return out

def octahedral(n):
    n = n / np.maximum(np.abs(n).sum(-1, keepdims=True), 1e-8)
    return np.stack([n[..., 0] + n[..., 1], n[..., 0] - n[..., 1]], -1) * 0.5 + 0.5

def write_albedo(path, rgba):
    data = [bc3(np.clip(np.rint(m), 0, 255).astype(np.uint8)) for m in mips(rgba.astype(np.float32))]
    dds(path, (data, rgba.shape[:2]), b"DXT5", 16)

def cutout_mips(rgba, ref=128.0):
    """FIX-REMIX-MATERIALS-3: the mip chain of a cut-out texture (fences, railings, leaf cards)
    that keeps its alpha-tested coverage. A plain box mip averages a 2-texel bar with the hole
    beside it to alpha < 128, so at distance the alpha test drops the bars (the shredded
    railing tops, pt-remix-third-distant-fence-and-railing-tops-shredded-horizontal-streaks)
    and the colour of each kept texel is darkened by the black holes. Here colour is averaged
    over the opaque texels only and each level's alpha is scaled so that the share of texels
    passing the test equals the top level's (Castano's coverage-preserving mips)."""
    a = rgba.astype(np.float32)
    cov0 = float((a[..., 3] >= ref).mean())
    out = [a]
    cur = a
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        w = (cur[..., 3:4] / 255.0)
        col = halve(cur[..., :3] * w) / np.maximum(halve(w), 1e-4)
        al = halve(cur[..., 3:4])
        nxt = np.concatenate([col, al], -1)
        if 0.0 < cov0 < 1.0 and nxt.shape[0] >= 4:
            lo, hi = 0.25, 8.0
            for _ in range(16):                       # scale so coverage matches the top level
                s = (lo + hi) / 2
                if float((np.minimum(al * s, 255) >= ref).mean()) < cov0: lo = s
                else: hi = s
            nxt[..., 3:4] = np.minimum(al * hi, 255)
        out.append(nxt); cur = nxt
    return out

def write_albedo_cutout(path, rgba):
    """write_albedo with cutout_mips (alpha-tested textures)."""
    data = [bc3(np.clip(np.rint(m), 0, 255).astype(np.uint8)) for m in cutout_mips(rgba)]
    dds(path, (data, rgba.shape[:2]), b"DXT5", 16)

def write_normal(path, n):
    data = []
    for level in mips(n):
        level = level / np.maximum(np.linalg.norm(level, axis=-1, keepdims=True), 1e-8)
        data.append(bc5(np.clip(np.rint(octahedral(level) * 255), 0, 255).astype(np.uint8)))
    dds(path, (data, n.shape[:2]), b"BC5U", 16)

def write_roughness(path, r):
    data = [bc4(np.clip(np.rint(m), 0, 255).astype(np.uint8)) for m in mips(r.astype(np.float32))]
    dds(path, (data, r.shape[:2]), b"BC4U", 8)

def write_height(path, hgt):
    """BC4 height (1 = surface, 0 = deepest) with a *max* mip chain: the runtime's
    quadtree POM reads the mips as a max-quadtree, and the raymarch mode only gets a
    slightly conservative coarse level from it."""
    levels = [hgt.astype(np.float32)]
    while levels[-1].shape[0] > 1 or levels[-1].shape[1] > 1:
        a = levels[-1]; h2, w2 = max(a.shape[0] // 2, 1), max(a.shape[1] // 2, 1)
        a = a[:h2 * 2 if a.shape[0] > 1 else 1, :w2 * 2 if a.shape[1] > 1 else 1]
        levels.append(a.reshape(h2, 2 if a.shape[0] > 1 else 1, w2, 2 if a.shape[1] > 1 else 1).max(axis=(1, 3)))
    dds(path, ([bc4(np.clip(np.rint(m), 0, 255).astype(np.uint8)) for m in levels], hgt.shape[:2]), b"BC4U", 8)

def small(a, size):
    """a uint8 map resampled to size x size (Lanczos)"""
    if a.shape[0] == size: return a
    return np.asarray(Image.fromarray(a, "L").resize((size, size), Image.LANCZOS))

# ------------------------------------------------------- DDS tile sets --
def dds_levels(path):
    """The mip levels (block bytes, top down) of a DXT1/DXT5 DDS as tools/pack_textures_dds.py writes it."""
    b = open(path, "rb").read()
    if b[:4] != b"DDS ": return None
    flags, h, w = struct.unpack_from("<III", b, 8)
    nmips = struct.unpack_from("<I", b, 28)[0] if flags & 0x20000 else 1
    bpb = {b"DXT1": 8, b"DXT5": 16}.get(b[84:88])
    if bpb is None: return None
    levels, off = [], 128
    for i in range(max(1, nmips)):
        n = ((max(1, w >> i) + 3) // 4) * ((max(1, h >> i) + 3) // 4) * bpb
        levels.append(b[off:off + n]); off += n
    return levels

def dds_hash(path, scheme="mip0"):
    """The hash Remix gives an HD tile: XXH3-64 of the top mip's block bytes (verified in game,
    see docs/remix-materials.md), or of the whole chain with scheme="all"."""
    levels = dds_levels(path)
    if levels is None: return None
    return "%016X" % xxhash.xxh3_64_intdigest(levels[0] if scheme == "mip0" else b"".join(levels))

def tile_classes(gmp_dir, style, hd_dir=None):
    """REMIX-MATERIALS: {tile: (ground, lift)} for one district from its .gmp. ground is "road"
    for a tile used mostly as the lid of road blocks, "pave" mostly as the lid of pavement or
    field blocks (paving, plazas, lawns, roofs), None otherwise (walls); lift is True for the
    curated dark foliage tiles (remix_pbr.VEG_LIFT). "flat" for the painted walls (remix_pbr.FLAT_WALL),
    "mural" for murals (remix_pbr.MURAL_WALL and mural_like on the HD tile in hd_dir), when not a lid; "cut"
    for the other cut-out wall tiles (fences, railings: coverage-preserving albedo mips, no
    parallax). See remix_pbr.GROUND_GAIN."""
    import remix_pbr
    from collections import Counter
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "linux", "docker"))
    import gmp
    out = {}
    path = os.path.join(gmp_dir, f"{style}.gmp")
    if os.path.exists(path):
        blocks, cols = gmp.load(path)
        lid, side, gt = Counter(), Counter(), {}
        for _, idx in cols.values():
            for i in idx:
                b = blocks[i]; t = b[4] & 1023
                if t: lid[t] += 1; gt.setdefault(t, Counter())[b[6] & 3] += 1
                for f in b[:4]:
                    if f & 1023: side[f & 1023] += 1
        for t in lid:
            if lid[t] <= side[t]: continue
            g = gt[t].most_common(1)[0][0]
            out[t] = ("road" if g == 1 else "pave" if g in (2, 3) else None, False)
    for t in remix_pbr.FLAT_WALL.get(style, ()):            # FIX-REMIX-MATERIALS-3: painted walls
        if t not in out: out[t] = ("flat", False)
    for t in remix_pbr.MURAL_WALL.get(style, ()):           # and murals
        if t not in out: out[t] = ("mural", False)
    if hd_dir and os.path.isdir(hd_dir):
        for f in os.listdir(hd_dir):
            m = re.match(r"tile_(\d{4})\.dds$", f)
            if not m or int(m.group(1)) in out: continue
            rgba = np.asarray(Image.open(os.path.join(hd_dir, f)).convert("RGBA"))
            if remix_pbr.mural_like(rgba):
                out[int(m.group(1))] = ("mural", False)
            elif 0.01 < float((rgba[::4, ::4, 3] < 128).mean()) < 0.99:
                out[int(m.group(1))] = ("cut", False)     # fences, railings, grilles: coverage mips, no parallax
    for t in remix_pbr.IRON_RAIL.get(style, ()):            # FIX-REMIX-MATERIALS-4: railings are painted iron
        out[t] = ("iron", False)
    for t in remix_pbr.VEG_LIFT.get(style, ()):
        out[t] = (out.get(t, (None, False))[0], "solid" if t in remix_pbr.VEG_SOLID.get(style, ()) else True)
    return out

def pbr_tile(job):
    """VISUALS-REMIX: every map of one HD tile (tools/remix_pbr.py), written next to its albedo.
    Normal at the tile's own 512 px (BC5 octahedral), roughness / wet roughness / metallic /
    height at --map-size (BC4). Returns (hash, displace_in, groundish, class shares).
    REMIX-MATERIALS: job may carry (ground, lift, albedo): a road/pave lid class for the
    relief, the foliage lift, and another DDS for the albedo (the re-authored road paint of
    assets/textures_hd/roads/<style>, which the renderer binds in the street views only;
    under Remix the plain tile's hash keys it, the clean paint is what is drawn)."""
    import shutil, remix_pbr
    path, h, tex_dir, size, map_size = job[:5]
    ground, lift, albedo, micro = (tuple(job[5:]) + (None, False, None, None))[:4] if len(job) > 5 else (None, False, None, None)
    src = albedo or path
    rgba = np.asarray(Image.open(src).convert("RGBA"))
    if rgba.shape[0] != size: rgba = resize(rgba, size)
    a_path = os.path.join(tex_dir, f"{h}.a.rtex.dds")
    if os.path.lexists(a_path): os.remove(a_path)       # never write through a hard link into another layer
    cut = lift != "solid" and float((rgba[..., 3] < 128).mean()) > 0.01
    if lift:
        rgba = remix_pbr.veg_albedo(rgba, solid=lift == "solid")
        (write_albedo_cutout if cut else write_albedo)(a_path, rgba)
    elif ground == "iron":                               # FIX-REMIX-MATERIALS-4: painted iron, coverage mips
        rgba = remix_pbr.iron_albedo(rgba)
        (write_albedo_cutout if cut else write_albedo)(a_path, rgba)
    elif cut:                                            # FIX-REMIX-MATERIALS-3: keep the bars at distance
        write_albedo_cutout(a_path, rgba)
    elif ground == "mural":                              # FIX-REMIX-MATERIALS-5: no painted lumps in a mosaic's pale pieces
        rgba = remix_pbr.mural_albedo(rgba)
        write_albedo(a_path, rgba)
    elif ground == "road" and albedo is None:            # FIX-REMIX-MATERIALS-3: no contour bands
        rgba = remix_pbr.deband(rgba)
        write_albedo(a_path, rgba)
    else:
        shutil.copyfile(src, a_path)
    mic = None
    if micro:                                            # FIX-REMIX-MATERIALS-4: a smooth lid gets a scan's micro-surface
        ms = remix_pbr.micro_surface(micro[2], micro[0], rgba.shape[0], micro[1])
        if ms is not None:
            gain, mh, mg = ms
            rgba = rgba.copy()
            rgba[..., :3] = np.clip(rgba[..., :3].astype(np.float32) * gain[..., None], 0, 255).astype(np.uint8)
            if os.path.lexists(a_path): os.remove(a_path)
            (write_albedo_cutout if cut else write_albedo)(a_path, rgba)
            mic = (mh, mg)
    for ext in "nrmhw":                                  # same for every other map (dds() opens "wb")
        p = os.path.join(tex_dir, f"{h}.{ext}.rtex.dds")
        if os.path.lexists(p): os.remove(p)
    r = remix_pbr.analyse(rgba, True, kind="tile", seed=h, ground=ground, micro=mic)
    write_normal(os.path.join(tex_dir, f"{h}.n.rtex.dds"), r["normal"])
    write_roughness(os.path.join(tex_dir, f"{h}.r.rtex.dds"), small(r["rough"], map_size))
    for key, ext in (("metal", "m"), ("height", "h")):
        p = os.path.join(tex_dir, f"{h}.{ext}.rtex.dds")
        if r[key] is not None:
            (write_height if ext == "h" else write_roughness)(p, small(r[key], map_size))
        elif os.path.exists(p): os.remove(p)
    p = os.path.join(tex_dir, f"{h}.w.rtex.dds")
    if r["groundish"]: write_roughness(p, small(r["rough_wet"], map_size))
    elif os.path.exists(p): os.remove(p)
    return h, r["displace"] if r["height"] is not None else 0.0, r["groundish"], r["cls"]

def dds_tiles(a, tex_dir, taken):
    """--dds-tiles: one material per HD DDS tile, keyed by the hash of what the game uploads.
    The DDS itself becomes the albedo (no re-encode); the other maps come from its pixels:
    with --pbr full (default) every map of tools/remix_pbr.py, with --pbr basic the older
    256 px band-pass normal and contrast roughness."""
    import json, shutil
    made = skipped = 0; t0 = time.time(); jobs = []
    micro_list = json.load(open(a.micro_list)) if a.cc0 else {}
    for d in a.dds_tiles:
        style = os.path.basename(os.path.normpath(d))
        classes = tile_classes(a.gmp_dir, style, d) if a.gmp_dir else {}
        mstyle = micro_list.get(style, {})
        roads = os.path.join(os.path.dirname(os.path.normpath(d)), "roads", style)
        for f in sorted(os.listdir(d)):
            if not f.endswith(".dds"): continue
            path = os.path.join(d, f)
            m = re.match(r"tile_(\d{4})\.dds$", f)
            ground, lift = classes.get(int(m.group(1)), (None, False)) if m else (None, False)
            mc = mstyle.get(str(int(m.group(1)))) if m and ground in ("pave", "road") else None
            micro = (mc["cls"], mc["amp"], a.cc0) if mc else None
            if a.only_classed and ground is None and not lift: continue
            if a.classes and ground not in a.classes and not (lift and "lift" in a.classes) \
                    and not (micro and "micro" in a.classes): continue
            if a.classes == {"micro"} and not micro: continue
            h = dds_hash(path, a.dds_hash)
            if h is None or h in taken: skipped += 1; continue
            if not a.force and os.path.exists(os.path.join(tex_dir, f"{h}.r.rtex.dds")): skipped += 1; continue
            taken.add(h)
            if a.pbr == "full":
                alb = os.path.join(roads, f) if ground == "road" and os.path.exists(os.path.join(roads, f)) else None
                jobs.append((path, h, tex_dir, a.size, a.map_size, ground, lift, alb, micro)); continue
            shutil.copyfile(path, os.path.join(tex_dir, f"{h}.a.rtex.dds"))
            rgba = np.asarray(Image.open(path).convert("RGBA"))
            if rgba.shape[0] != a.size: rgba = resize(rgba, a.size)
            write_normal(os.path.join(tex_dir, f"{h}.n.rtex.dds"), normal_map(rgba[..., :3]))
            write_roughness(os.path.join(tex_dir, f"{h}.r.rtex.dds"), roughness_map(rgba[..., :3]))
            made += 1
    if jobs:
        import multiprocessing as mp
        info_path = os.path.join(os.path.dirname(tex_dir), "pbr.json")
        info = json.load(open(info_path)) if os.path.exists(info_path) else {}
        with mp.Pool(a.jobs) as pool:
            for i, (h, disp, ground, cls) in enumerate(pool.imap_unordered(pbr_tile, jobs, chunksize=4)):
                info[h] = {"displace_in": disp, "wet": ground, "cls": cls}
                if a.gmp_dir:
                    j = next(j for j in jobs if j[1] == h)
                    if j[5]: info[h]["ground"] = j[5]
                    if j[6]: info[h]["lift"] = j[6]
                    if j[7]: info[h]["albedo"] = os.path.relpath(j[7], os.path.dirname(os.path.dirname(os.path.dirname(j[7]))))
                    if j[8]: info[h]["micro"] = [j[8][0], j[8][1]]
                if i % 200 == 0:   # also saved as it goes: an interrupted build keeps what it made
                    print(f"  {i}/{len(jobs)} tiles, {time.time() - t0:.0f} s", flush=True)
                    json.dump(info, open(info_path, "w"), indent=0, sort_keys=True)
        json.dump(info, open(info_path, "w"), indent=0, sort_keys=True)
        made += len(jobs)
    return made, skipped, time.time() - t0

# ------------------------------------------------------------------ USDA --
MATERIAL = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @{mdl}.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "{mdl}"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom asset inputs:normalmap_texture = @./textures/{h}.n.rtex.dds@ (
                    colorSpace = "raw"
                )
                custom asset inputs:reflectionroughness_texture = @./textures/{h}.r.rtex.dds@ (
                    colorSpace = "raw"
                )
                custom float inputs:metallic_constant = 0
                custom float inputs:reflection_roughness_constant = 0.8
                custom bool inputs:use_legacy_alpha_state = 1{metal}{height}{emissive}
                token outputs:out
            }}
        }}
'''
# FIX-REMIX: the water tiles (pbr.json "water": true, tools/remix_water.py): the tile's
# colour, a smooth dielectric and one shared tileable ripple normal, no roughness map.
WATER = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @{mdl}.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "{mdl}"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom asset inputs:normalmap_texture = @./textures/{ripple}@ (
                    colorSpace = "raw"
                )
                custom float inputs:metallic_constant = 0
                custom float inputs:reflection_roughness_constant = 0.08
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
'''
# Neon and lit signs (tools/remix_emissive.py writes the mask): the strokes glow.
EMISSIVE = '''
                custom asset inputs:emissive_mask_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom bool inputs:enable_emission = 1
                custom float inputs:emissive_intensity = {intensity}'''
EMISSIVE_INTENSITY = 30
# VISUALS-REMIX: per-texel metallic and the height field for Remix's parallax displacement.
METAL = '''
                custom asset inputs:metallic_texture = @./textures/{h}.m.rtex.dds@ (
                    colorSpace = "raw"
                )'''
HEIGHT = '''
                custom asset inputs:height_texture = @./textures/{h}.h.rtex.dds@ (
                    colorSpace = "raw"
                )
                custom float inputs:displace_in = {d}'''

def write_usda(mod_dir, out_name="mod.usda"):
    """The tile layer from what is in <mod>/textures: albedo + normal + roughness always,
    metallic / height (+ displace_in from pbr.json) / emission when their maps exist.
    The wet roughness (.w) is referenced only by the rain variant (wet_layer)."""
    import json
    tex = os.path.join(mod_dir, "textures")
    have = set(os.listdir(tex))
    hashes = sorted({f[:16] for f in have if re.match(r"[0-9A-F]{16}\.a\.rtex\.dds$", f) and f[:16] + ".n.rtex.dds" in have})
    info_path = os.path.join(mod_dir, "pbr.json")
    info = json.load(open(info_path)) if os.path.exists(info_path) else {}
    def prim(h):
        if info.get(h, {}).get("water") and "water_ripple.n.rtex.dds" in have:
            return WATER.format(h=h, mdl=MDL, ripple="water_ripple.n.rtex.dds")
        text = MATERIAL.format(
            h=h, mdl=MDL,
            metal=METAL.format(h=h) if f"{h}.m.rtex.dds" in have else "",
            height=HEIGHT.format(h=h, d=info.get(h, {}).get("displace_in") or 0.012) if f"{h}.h.rtex.dds" in have else "",
            emissive=EMISSIVE.format(h=h, intensity=EMISSIVE_INTENSITY) if f"{h}.e.rtex.dds" in have else "")
        return text
    body = "\n".join(prim(h) for h in hashes)
    text = ('#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n' + body + "    }\n}\n")
    open(os.path.join(mod_dir, out_name), "w", encoding="utf-8", newline="\n").write(text)
    return hashes

def wet_layer(mod_dir, out_name="mod_wet.usda"):
    """The rain variant of the finished layer (tiles, signs and cars): mod.usda with each
    tile's roughness swapped for its wet roughness (.w: glossier, puddles on ground-like
    tiles, water in the joints) where it has one. Remix reads mod.usda only, so the variant
    is installed by copying it over mod.usda (or MODS_HD_SRC pointing at a folder whose
    mod.usda is this file)."""
    tex = os.path.join(mod_dir, "textures"); have = set(os.listdir(tex))
    text = open(os.path.join(mod_dir, "mod.usda"), encoding="utf-8").read()
    n = 0
    def swap(m):
        nonlocal n
        h = m.group(1)
        if f"{h}.w.rtex.dds" in have: n += 1; return f"./textures/{h}.w.rtex.dds"
        return m.group(0)
    text = re.sub(r"\./textures/([0-9A-F]{16})\.r\.rtex\.dds", swap, text)
    open(os.path.join(mod_dir, out_name), "w", encoding="utf-8", newline="\n").write(text)
    return n

def validate(mod_dir):
    text = open(os.path.join(mod_dir, "mod.usda"), encoding="utf-8").read()
    prims = re.findall(r'over "mat_([0-9A-F]{16})"', text)
    problems = []
    if len(prims) != len(set(prims)): problems.append("duplicate material prims")
    refs = re.findall(r"@\./([^@]+)@", text)
    for r in refs:
        if not os.path.exists(os.path.join(mod_dir, r)): problems.append(f"missing {r}")
    if text.count("{") != text.count("}"): problems.append("unbalanced braces")
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(mod_dir) for f in fs)
    return prims, refs, problems, size

# ------------------------------------------------------------------ main --
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dump", help="renderer tile dump (tile_NNNN.tga at 64x64): the hashes")
    ap.add_argument("mod", help="mod folder to write (mod.usda + textures/)")
    ap.add_argument("--hd", nargs="+", default=[], help="high-resolution tile folders, first match wins")
    ap.add_argument("--sd", default=None, help="folder of SD-refined tiles used for the albedo where present")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--exclude", nargs="*", default=[], help="other mod layers (.usd/.usda) whose materials must not be overridden here")
    ap.add_argument("--validate-only", action="store_true", help="only check an existing mod against the dump")
    ap.add_argument("--dds-tiles", nargs="*", default=[], help="HD DDS tile folders (assets/textures_hd/<style>): materials keyed by the uploaded block data; the dump argument is then unused (pass -)")
    ap.add_argument("--dds-hash", choices=["mip0", "all"], default="mip0", help="which bytes of a DDS Remix hashes (mip0, verified)")
    ap.add_argument("--pbr", choices=["full", "basic"], default="full", help="full: every map of remix_pbr.py (VISUALS-REMIX); basic: the older normal + roughness")
    ap.add_argument("--map-size", type=int, default=256, help="roughness / metallic / height / wet maps (the normal is at --size)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--gmp-dir", default=None, help="REMIX-MATERIALS: game/data with <style>.gmp: lid classes (road paint flat, no parallax on lids), the foliage lift, and the re-authored road paint (<hd>/../roads/<style>) as the road lids' albedo")
    ap.add_argument("--only-classed", action="store_true", help="with --gmp-dir: only the tiles that have a class (road/pave lid or foliage lift); use with --force into a scratch layer, then tools/remix_layer_merge.py --tiles")
    ap.add_argument("--classes", type=lambda s: set(s.split(",")), default=None, help="with --only-classed: only these classes (road,pave,flat,mural,cut,iron,lift,micro), e.g. flat,cut")
    ap.add_argument("--cc0", default=None, help="FIX-REMIX-MATERIALS-4: the ambientCG folder of tools/photoreal_tiles.py (fetch): the smooth lids of --micro-list get the scan's micro-surface")
    ap.add_argument("--micro-list", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "remix_micro_tiles.json"), help="{style: {tile: {cls, amp}}} smooth ground lids and their photo-pass class")
    ap.add_argument("--wet-layer", action="store_true", help="only write <mod>/mod_wet.usda from the finished mod.usda (the rain variant)")
    a = ap.parse_args()
    if a.wet_layer:
        print(f"mod_wet.usda: {wet_layer(a.mod)} tile prims with wet roughness"); return
    if a.validate_only:
        dump_hashes = {remix_hash(read_tga(os.path.join(a.dump, f))) for f in os.listdir(a.dump) if f.endswith(".tga")}
        prims, refs, problems, size = validate(a.mod)
        unknown = [h for h in prims if h not in dump_hashes]
        if unknown: problems.append(f"{len(unknown)} prims not in the dump: {unknown[:3]}")
        print(f"{len(prims)} materials, {len(refs)} texture references, {len(dump_hashes)} dump hashes, "
              f"{len(set(prims) & dump_hashes)} matched, {size / 1e6:.1f} MB; {'ok' if not problems else problems}")
        sys.exit(1 if problems else 0)
    tex_dir = os.path.join(a.mod, "textures"); os.makedirs(tex_dir, exist_ok=True)
    taken = set()
    for layer in a.exclude:   # byte scan works for both usda text and usdc binaries (tokens are stored as strings)
        taken |= {m.decode() for m in re.findall(rb"mat_([0-9A-F]{16})", open(layer, "rb").read())}
    if a.dds_tiles:
        made, skipped, dt = dds_tiles(a, tex_dir, taken)
        hashes = write_usda(a.mod)
        prims, refs, problems, size = validate(a.mod)
        print(f"{made} DDS-keyed materials written, {skipped} skipped, {len(hashes)} materials in the layer, "
              f"{size / 1e6:.1f} MB, {dt:.0f} s; validation: {'ok' if not problems else problems[:5]}")
        return
    tiles = sorted(f for f in os.listdir(a.dump) if re.match(r"tile_\d{4}\.tga$", f))
    if a.limit: tiles = tiles[:a.limit]
    t0 = time.time(); made = skipped = fallback = 0
    for f in tiles:
        base = read_tga(os.path.join(a.dump, f))
        if base.shape[0] != 64 or base.shape[1] != 64: continue
        h = remix_hash(base)
        if h in taken: skipped += 1; continue
        if not a.force and os.path.exists(os.path.join(tex_dir, f"{h}.r.rtex.dds")): skipped += 1; continue
        src = None
        for d in ([a.sd] if a.sd else []) + a.hd:
            if os.path.exists(os.path.join(d, f)): src = os.path.join(d, f); break
        if src is None: fallback += 1
        rgba = to_rgba(read_tga(src)) if src else to_rgba(base)
        if rgba.shape[0] != a.size: rgba = resize(rgba, a.size)
        # The cutout stays the game's own: nearest from the 64x64 alpha.
        alpha = np.asarray(Image.fromarray(base[..., 3], "L").resize((a.size, a.size), Image.NEAREST))
        rgba = rgba.copy(); rgba[..., 3] = alpha
        write_albedo(os.path.join(tex_dir, f"{h}.a.rtex.dds"), rgba)
        write_normal(os.path.join(tex_dir, f"{h}.n.rtex.dds"), normal_map(rgba[..., :3]))
        write_roughness(os.path.join(tex_dir, f"{h}.r.rtex.dds"), roughness_map(rgba[..., :3]))
        made += 1
    hashes = write_usda(a.mod)
    prims, refs, problems, size = validate(a.mod)
    print(f"{made} materials written ({fallback} from the 64x64 original, no HD tile), {skipped} already there, "
          f"{len(hashes)} materials in the layer, {len(refs)} texture references, {size / 1e6:.1f} MB, "
          f"{time.time() - t0:.0f} s; validation: {'ok' if not problems else problems[:5]}")

if __name__ == "__main__":
    main()
