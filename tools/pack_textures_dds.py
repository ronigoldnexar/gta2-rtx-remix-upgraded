#!/usr/bin/env python3
"""Packs high-resolution tile candidates into block-compressed DDS files with mips.

    pack_textures_dds.py <orig 64px dump> <out dir> [--esrgan DIR] [--sd DIR]
                         [--size 512] [--sheet PNG] [--jobs N]

For every tile_NNNN.tga in the original dump (the renderer's gta2dx9_tiles\\ dump,
or tools/enhance_textures_sd.py extract) the candidates are read from the Real-ESRGAN
folder (tools/upscale_textures.py, any size, resampled to --size) and the Stable
Diffusion folder (tools/enhance_textures_sd.py, --out-size 512). One is chosen per
tile:

  fidelity  SSIM between the candidate shrunk back to 64 px and the original tile:
            how recognisable the tile still is (road markings, windows, signs).
  detail    variance of the Laplacian at full size: how much real surface detail
            the candidate carries.

The SD rendering wins when it is still faithful (SSIM >= --min-ssim and within
--ssim-slack of the ESRGAN one) and at least as sharp as --min-detail of the ESRGAN
candidate's edge detail; otherwise the clean ESRGAN upscale is used, so a sign or a
window never turns into something else and a soft rendering never replaces a crisp
one. The SD candidates are best made from the ESRGAN 256 px tiles (enhance_textures_sd
with the ESRGAN folder as input) and sharpened by a further Real-ESRGAN pass. Alpha is the original cutout,
upscaled nearest, kept hard; tiles with any transparency become DXT5, the rest DXT1.

The output tile_NNNN.dds is what src/renderer.cpp loads: a 128-byte DDS header, the
mip levels top down (Lanczos, down to 1x1), each a tightly packed row-major run of
4x4 blocks. 512 px: 175 KB a tile for DXT1 and 350 KB for DXT5, against 1 MB for a
256 px uncompressed TGA, which is what lets a 32-bit game process hold a level's
tiles at 512 px with mips.
"""
import argparse, os, struct, sys, time
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageFilter


def read_tga(path):
    return Image.open(path).convert("RGBA")


def box_filter(a, r):
    """Mean over a (2r+1)^2 window with edge clamping, via cumulative sums."""
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    n = 2 * r + 1
    return (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)


def ssim(a, b, r=3):
    """Structural similarity of two grey images in [0,1], uniform window."""
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ma, mb = box_filter(a, r), box_filter(b, r)
    va = box_filter(a * a, r) - ma * ma
    vb = box_filter(b * b, r) - mb * mb
    cov = box_filter(a * b, r) - ma * mb
    s = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(s.mean())


def grey(im):
    return np.asarray(im.convert("L")).astype(np.float64) / 255.0


def laplacian_var(im):
    g = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES)).astype(np.float64)
    return float(g.var())


def dds_header(w, h, mips, fourcc, level0_bytes):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000   # caps height width pixelformat mipmapcount linearsize
    caps = 0x1000 | 0x400000 | 0x8                          # texture mipmap complex
    pf = struct.pack("<II4sIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    return (b"DDS " + struct.pack("<IIIIIII", 124, flags, h, w, level0_bytes, 0, mips)
            + b"\0" * 44 + pf + struct.pack("<IIIII", caps, 0, 0, 0, 0))


def encode_level(im, fmt):
    """Pillow's BCn encoder writes a whole DDS; the block data follows its header."""
    import io
    buf = io.BytesIO()
    (im.convert("RGB") if fmt == "DXT1" else im.convert("RGBA")).save(buf, format="DDS", pixel_format=fmt)
    return buf.getvalue()[128:]


def pack_tile(args):
    name, orig_dir, esr_dir, sd_dir, out_dir, size, min_ssim, slack, min_detail = args
    orig = read_tga(os.path.join(orig_dir, name))
    alpha64 = orig.split()[3]
    has_alpha = alpha64.getextrema()[0] < 255
    cands = {}
    for key, d in (("esrgan", esr_dir), ("sd", sd_dir)):
        if d and os.path.exists(os.path.join(d, name)):
            im = read_tga(os.path.join(d, name)).convert("RGB")
            if im.size != (size, size):
                im = im.resize((size, size), Image.LANCZOS)
            cands[key] = im
    if not cands:
        return name, None, 0.0, 0.0, has_alpha
    og = grey(orig)
    score = {}
    for key, im in cands.items():
        small = im.resize((64, 64), Image.BOX)
        score[key] = (ssim(og, grey(small)), laplacian_var(im))
    choice = "esrgan" if "esrgan" in cands else "sd"
    if "sd" in cands and "esrgan" in cands:
        f_sd, f_esr = score["sd"][0], score["esrgan"][0]
        d_sd, d_esr = score["sd"][1], score["esrgan"][1]
        if f_sd >= min_ssim and f_sd >= f_esr - slack and d_sd >= min_detail * d_esr:
            choice = "sd"
    rgb = cands[choice]
    alpha = alpha64.resize((size, size), Image.NEAREST)
    fmt = "DXT5" if has_alpha else "DXT1"
    fourcc = b"DXT1" if fmt == "DXT1" else b"DXT5"
    levels = []
    w = h = size
    cur = rgb.copy(); cur.putalpha(alpha)
    while True:
        levels.append(encode_level(cur, fmt))
        if w == 1 and h == 1:
            break
        w, h = max(1, w // 2), max(1, h // 2)
        nrgb = rgb.resize((w, h), Image.LANCZOS)
        nal = alpha.resize((w, h), Image.BOX)
        cur = nrgb.copy(); cur.putalpha(nal)
    out = os.path.join(out_dir, name[:-4] + ".dds")
    with open(out, "wb") as f:
        f.write(dds_header(size, size, len(levels), fourcc, len(levels[0])))
        for lv in levels:
            f.write(lv)
    return name, choice, score[choice][0], score[choice][1], has_alpha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("orig"); ap.add_argument("out")
    ap.add_argument("--esrgan"); ap.add_argument("--sd")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--min-ssim", type=float, default=0.70)
    ap.add_argument("--ssim-slack", type=float, default=0.12)
    ap.add_argument("--min-detail", type=float, default=0.6,
                    help="SD must keep at least this fraction of the ESRGAN candidate's edge detail (it is softer at 512 px)")
    ap.add_argument("--sheet"); ap.add_argument("--sheet-limit", type=int, default=48)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 8)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    names = sorted(f for f in os.listdir(a.orig) if f.lower().endswith(".tga"))
    t0 = time.time()
    jobs = [(n, a.orig, a.esrgan, a.sd, a.out, a.size, a.min_ssim, a.ssim_slack, a.min_detail) for n in names]
    with Pool(a.jobs) as pool:
        results = pool.map(pack_tile, jobs, chunksize=4)
    chosen = {}
    counts = {"esrgan": 0, "sd": 0, None: 0}
    with open(os.path.join(a.out, "choices.txt"), "w") as f:
        for name, choice, fid, det, has_alpha in results:
            counts[choice] += 1
            chosen[name] = choice
            f.write(f"{name} {choice} ssim={fid:.3f} detail={det:.1f} {'DXT5' if has_alpha else 'DXT1'}\n")
    total = sum(os.path.getsize(os.path.join(a.out, f)) for f in os.listdir(a.out) if f.endswith(".dds"))
    print(f"{len(names)} tiles -> {a.out} in {time.time() - t0:.0f} s: {counts['sd']} SD, {counts['esrgan']} ESRGAN, "
          f"{counts[None]} without candidates; {total / 1e6:.0f} MB of DDS", flush=True)
    if a.sheet:
        cell = 160
        rows = [n for n in names if chosen.get(n)][:a.sheet_limit]
        sheet = Image.new("RGB", (cell * 4, cell * len(rows)), (30, 30, 30))
        for i, n in enumerate(rows):
            cols = [read_tga(os.path.join(a.orig, n)).convert("RGB").resize((cell, cell), Image.NEAREST)]
            for d in (a.esrgan, a.sd):
                p = os.path.join(d, n) if d else None
                cols.append(read_tga(p).convert("RGB").resize((cell, cell), Image.LANCZOS) if p and os.path.exists(p)
                            else Image.new("RGB", (cell, cell), (60, 60, 60)))
            cols.append(Image.open(os.path.join(a.out, n[:-4] + ".dds")).convert("RGB").resize((cell, cell), Image.LANCZOS))
            for j, im in enumerate(cols):
                sheet.paste(im, (j * cell, i * cell))
        sheet.save(a.sheet)
        print(f"{a.sheet}: columns original | ESRGAN | SD | chosen (decoded DDS)")


if __name__ == "__main__":
    main()
