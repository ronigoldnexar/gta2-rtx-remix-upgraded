#!/usr/bin/env python3
"""mp4check.py <file>...: the top-level atoms in order; faststart = moov before mdat"""
import struct, sys
for p in sys.argv[1:]:
    f = open(p, "rb"); order = []; off = 0
    while True:
        h = f.read(8)
        if len(h) < 8: break
        size, typ = struct.unpack(">I4s", h)
        if size == 1: size = struct.unpack(">Q", f.read(8))[0]; hdr = 16
        else: hdr = 8
        order.append(typ.decode("latin1"))
        if size < hdr: break
        off += size; f.seek(off)
    fs = "moov" in order and "mdat" in order and order.index("moov") < order.index("mdat")
    print(p, " ".join(order), "FASTSTART" if fs else "NOT faststart")
