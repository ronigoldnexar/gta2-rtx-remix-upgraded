#!/usr/bin/env python3
"""Dumps tiles straight from a style file, in the renderer's own dump format
(tile_NNNN.tga, 64x64, 32-bit top-down TGA, palette index 0 transparent), for
the tiles the in-game dump never captured: the frames of animated tiles (the
game only uploads the frame that is showing) and any tile used by the map that
the dump run did not walk past.

    dump_style_tiles.py <game/data> <style wil|bil|ste> <out dir> [--missing <hd dir>] [--all]

With --missing, only tiles that the map uses or that belong to an ANIM group and
have no tile_NNNN.dds in <hd dir> are written; --all writes every tile the map
uses or animates. Prints the list written and the animated groups.
"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assets-src', 'cars'))
import parse_sty  # noqa: E402
from PIL import Image  # noqa: E402

def sty_chunks(d):
    c = {}; off = 6
    while off + 8 <= len(d):
        tag = d[off:off + 4].decode('latin1'); size = struct.unpack_from('<I', d, off + 4)[0]
        c[tag] = (off + 8, size); off += 8 + size
    return c

def tile_rgba(st, c, i):
    d = st['d']; base = c['TILE'][0]
    page, k = divmod(i, 16); row, col = divmod(k, 4)
    pal = st['palette'](st['phys'](st['bases']['tile'] + i))
    img = Image.new('RGBA', (64, 64)); px = img.load()
    for y in range(64):
        o = base + page * 65536 + (row * 64 + y) * 256 + col * 64
        line = d[o:o + 64]
        for x, v in enumerate(line):
            if v == 0: px[x, y] = (0, 0, 0, 0)
            else:
                b, g, r, _ = pal[v]; px[x, y] = (r, g, b, 255)
    return img

def gmp_tiles_and_anims(path):
    d = open(path, 'rb').read(); c = {}; off = 6
    while off + 8 <= len(d):
        tag = d[off:off + 4].decode('latin1'); size = struct.unpack_from('<I', d, off + 4)[0]
        c[tag] = (off + 8, size); off += 8 + size
    o, sz = c['DMAP']; W = H = 256
    base = o + W * H * 4
    ncol = struct.unpack_from('<I', d, base)[0]; coldata = base + 4
    nblk_off = coldata + ncol * 4
    nblk = struct.unpack_from('<I', d, nblk_off)[0]; bdata = nblk_off + 4
    used = set()
    for bi in range(nblk):
        p = bdata + bi * 12
        for f in range(5):
            t = struct.unpack_from('<H', d, p + f * 2)[0] & 0x3FF
            if t not in (0, 1023): used.add(t)
    # which blocks are actually referenced by columns
    o2, sz2 = c['ANIM']; a = d[o2:o2 + sz2]; p = 0; anims = []
    while p + 6 <= len(a):
        b, rate, rep, n = struct.unpack_from('<HBBB', a, p); p += 6
        anims.append((b, rate, rep, list(struct.unpack_from(f'<{n}H', a, p)))); p += 2 * n
    return used, anims

def write_tga(img, path):
    w, h = img.size; px = img.load()
    hdr = bytearray(18); hdr[2] = 2; hdr[12] = w & 255; hdr[13] = w >> 8; hdr[14] = h & 255; hdr[15] = h >> 8; hdr[16] = 32; hdr[17] = 0x28
    body = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]; body += bytes((b, g, r, a))
    open(path, 'wb').write(bytes(hdr) + bytes(body))

def main():
    data, sty, out = sys.argv[1:4]
    hd = sys.argv[sys.argv.index('--missing') + 1] if '--missing' in sys.argv else None
    st = parse_sty.parse(os.path.join(data, sty + '.sty')); c = sty_chunks(st['d'])
    used, anims = gmp_tiles_and_anims(os.path.join(data, sty + '.gmp'))
    anim_tiles = {t for *_, ts in anims for t in ts} | {a[0] for a in anims}
    want = sorted(used | anim_tiles)
    have = set()
    if hd and os.path.isdir(hd):
        have = {int(f[5:9]) for f in os.listdir(hd) if f.endswith('.dds') and f.startswith('tile_')}
    os.makedirs(out, exist_ok=True); written = []
    for t in want:
        if hd and t in have: continue
        write_tga(tile_rgba(st, c, t), os.path.join(out, f'tile_{t:04d}.tga')); written.append(t)
    print(f'{sty}: map uses {len(used)} tiles, {len(anim_tiles)} animated frames in {len(anims)} groups; wrote {len(written)}: {written}')
    for b, rate, rep, ts in anims:
        print(f'  anim base {b} rate {rate} repeat {rep} frames {ts}')

if __name__ == '__main__':
    main()
