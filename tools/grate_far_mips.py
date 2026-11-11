#!/usr/bin/env python3
"""FIX-WORLD-20 (FIX-WORLD-19 residual): the street views' roof/vent grates without the distance shimmer.

    grate_far_mips.py <in dir> <out dir> [--tiles 87,95,193] [--from-level 3]

Downtown's grates (87 louvre, 95 vent slats, 193 fine grate: one-texel slats in the 64 px art) are alpha-tested
cutouts. Their photo-set DDS (gta2dx9_textures_hd/photo/wil, street views only; the classic view keeps the plain
HD set) box-filters the cutout down the mip chain, so at the 128 and 64 px levels the slats are a 1-2 texel
pattern with 74-83 % of texels over the alpha reference: from the kerb a grate 10-20 blocks off sparkles as the
pattern beats against the pixel grid. This rewrites the levels from --from-level (default 3 = 64 px) down as
OPAQUE, their colour the cutout's colour premultiplied by its coverage (the holes taken as black: the dark attic
plates FIX-WORLD-19 put behind the sloped grates, a dark interior elsewhere), so a far grate reads as a dark
slatted panel with no alpha test left to alias. The levels above are copied byte for byte (the near look is
unchanged). Run with the feel_tools venv (numpy, Pillow). Outputs go outside git (game art); the next restage
carries them.
"""
import argparse, os, struct, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_textures_dds import dds_header, encode_level


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("indir"); ap.add_argument("outdir")
    ap.add_argument("--tiles", default="87,95,193")
    ap.add_argument("--from-level", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for t in [int(s) for s in a.tiles.split(",")]:
        name = "tile_%04d.dds" % t
        src = open(os.path.join(a.indir, name), "rb").read()
        h = struct.unpack_from("<7I", src, 4)
        size, mips, fourcc = h[3], h[6], src[84:88]
        if fourcc != b"DXT5" or h[2] != size:
            print(name, "skipped: not a square DXT5"); continue
        rgba = np.asarray(Image.open(os.path.join(a.indir, name)).convert("RGBA")).astype(np.float32)
        cov = rgba[..., 3:4] / 255.0
        prem = rgba[..., :3] * cov
        out = bytearray(src[:128]); off = 128; w = size
        for lvl in range(mips):
            n = max(1, (w + 3) // 4) ** 2 * 16
            if lvl < a.from_level:
                out += src[off:off + n]
            else:
                k = size // w
                c = prem.reshape(w, k, w, k, 3).mean(axis=(1, 3))
                im = Image.fromarray(np.dstack([np.clip(c + 0.5, 0, 255), np.full((w, w, 1), 255.0)]).astype(np.uint8), "RGBA")
                if w < 4:   # BCn needs 4x4 blocks: encode a 4x4 copy, keep its first block
                    blk = encode_level(im.resize((4, 4), Image.NEAREST), "DXT5")[:16]
                else:
                    blk = encode_level(im, "DXT5")
                assert len(blk) == n, (name, lvl, len(blk), n)
                out += blk
            off += n; w //= 2
        open(os.path.join(a.outdir, name), "wb").write(bytes(out))
        print(name, "levels %d.. opaque (of %d), coverage %.0f %%" % (a.from_level, mips, float(cov.mean()) * 100))


if __name__ == "__main__":
    main()
