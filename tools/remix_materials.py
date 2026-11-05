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

def write_normal(path, n):
    data = []
    for level in mips(n):
        level = level / np.maximum(np.linalg.norm(level, axis=-1, keepdims=True), 1e-8)
        data.append(bc5(np.clip(np.rint(octahedral(level) * 255), 0, 255).astype(np.uint8)))
    dds(path, (data, n.shape[:2]), b"BC5U", 16)

def write_roughness(path, r):
    data = [bc4(np.clip(np.rint(m), 0, 255).astype(np.uint8)) for m in mips(r.astype(np.float32))]
    dds(path, (data, r.shape[:2]), b"BC4U", 8)

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
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
'''

def write_usda(mod_dir):
    hashes = sorted({re.match(r"([0-9A-F]{16})\.a\.rtex\.dds$", f).group(1)
                     for f in os.listdir(os.path.join(mod_dir, "textures")) if re.match(r"[0-9A-F]{16}\.a\.rtex\.dds$", f)})
    body = "\n".join(MATERIAL.format(h=h, mdl=MDL) for h in hashes)
    text = ('#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n' + body + "    }\n}\n")
    open(os.path.join(mod_dir, "mod.usda"), "w", encoding="utf-8", newline="\n").write(text)
    return hashes

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
    a = ap.parse_args()
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
