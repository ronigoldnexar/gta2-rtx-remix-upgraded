#!/usr/bin/env python3
"""Mark a COPY of a 32-bit Windows executable large-address-aware (FIX-PERF-5).

GTA2's gta2.exe (9.6) is a 2 GB process: its PE header lacks IMAGE_FILE_LARGE_ADDRESS_AWARE
(Characteristics bit 0x0020). On 64-bit Windows (and under 64-bit Wine) the same process
gets 4 GB of address space once the bit is set. Our Linux runners have always set it on the
copy inside the Wine prefix (linux/laa.sh); on Windows nobody did, so the owner's box hits
the 2 GB wall (docs/performance.md "The 32-bit address space on Windows").

usage:
    python set_laa.py <path to your gta2.exe> [<output path>]

The original is never written. Without an output path the copy is written next to it as
gta2_laa.exe. To use it, keep a backup of the original, then rename the copy to gta2.exe
(or point your launcher at it). Run again on the copy to check: it says "already".
Never commit or distribute a game binary; run this on your own copy.
"""
import os
import shutil
import struct
import sys

LAA = 0x0020


def characteristics_offset(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("not an MZ executable")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("no PE header")
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    if machine != 0x014C:
        raise ValueError("not a 32-bit x86 executable (machine 0x%04x)" % machine)
    return pe + 4 + 18   # IMAGE_FILE_HEADER.Characteristics


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = argv[1]
    dst = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(src)), "gta2_laa.exe")
    with open(src, "rb") as f:
        data = bytearray(f.read())
    off = characteristics_offset(data)
    ch = struct.unpack_from("<H", data, off)[0]
    if ch & LAA:
        print("%s is already large-address-aware (Characteristics 0x%04x); nothing written" % (src, ch))
        return 0
    if os.path.abspath(dst) == os.path.abspath(src):
        print("refusing to write over the original; give another output path")
        return 2
    struct.pack_into("<H", data, off, ch | LAA)
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)
    print("%s written: Characteristics 0x%04x -> 0x%04x (large-address-aware). The original is unchanged." % (dst, ch, ch | LAA))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
