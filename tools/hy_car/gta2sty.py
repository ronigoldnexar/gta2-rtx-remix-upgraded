"""Minimal GTA2 style reader for the car tools: CARI comes from assets-src/cars/parse_sty.py; this adds the
sprite deltas (DELX/DELS, as src/gta2_style.cpp Style::DeltaPixels reads them) and a sprite's default palette."""
import struct

def _chunks(d):
    off = 6
    while off + 8 <= len(d):
        tag = d[off:off + 4].decode('latin1'); size = struct.unpack_from('<I', d, off + 4)[0]
        yield tag, off + 8, size
        off += 8 + size

class Style:
    PAGE = 256

    def __init__(self, path):
        d = self.d = open(path, 'rb').read()
        assert d[:4] == b'GBST'
        self.c = {t: (o, s) for t, o, s in _chunks(d)}
        palb = struct.unpack_from('<8H', d, self.c['PALB'][0])
        self.pal_base = {}
        acc = 0
        for name, n in zip(['tile', 'sprite', 'car_remap', 'ped_remap', 'code_obj_remap', 'map_obj_remap', 'user_remap', 'font_remap'], palb):
            self.pal_base[name] = acc; acc += n
        # DELX: per sprite (absolute number), its delta count and each delta's size in DELS, in order.
        self.deltas = {}
        o, s = self.c.get('DELX', (0, 0)); store = 0
        at = o
        while o and at + 4 <= o + s:
            spr = struct.unpack_from('<H', d, at)[0]; n = d[at + 2]; at += 4
            sizes = list(struct.unpack_from(f'<{n}H', d, at)); at += 2 * n
            offs = []
            for z in sizes: offs.append(store); store += z
            self.deltas[spr] = (offs, sizes)
        self.dels = d[self.c['DELS'][0]: self.c['DELS'][0] + self.c['DELS'][1]] if 'DELS' in self.c else b''

    def sprite_size(self, i):
        o = self.c['SPRX'][0]
        ptr, w, h = struct.unpack_from('<IBB', d := self.d, o + 8 * i)
        return w, h

    def palette(self, virtual):
        phys = struct.unpack_from('<H', self.d, self.c['PALX'][0] + 2 * virtual)[0]
        page, col = divmod(phys, 64)
        base = self.c['PPAL'][0] + page * 65536
        return [struct.unpack_from('<4B', self.d, base + ci * 256 + col * 4) for ci in range(256)]   # B G R A

    def car_palette(self, sprite):
        return self.palette(self.pal_base['sprite'] + sprite)

    def delta_pixels(self, sprite, delta):
        """[(x, y, palette index)] in the sprite's own pixels; [] when the sprite has no such delta."""
        if sprite not in self.deltas: return []
        offs, sizes = self.deltas[sprite]
        if delta >= len(sizes): return []
        b = offs[delta]; e = b + sizes[delta]; out = []; pos = 0; at = b
        while at + 3 <= e:
            pos += struct.unpack_from('<H', self.dels, at)[0]; n = self.dels[at + 2]; at += 3
            for k in range(n):
                if at + k < e: out.append(((pos + k) % self.PAGE, (pos + k) // self.PAGE, self.dels[at + k]))
            pos += n; at += n
        return out

    def delta_count(self, sprite):
        return len(self.deltas.get(sprite, ([], []))[1])
