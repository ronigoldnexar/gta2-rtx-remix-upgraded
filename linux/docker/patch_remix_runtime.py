#!/usr/bin/env python3
"""Turns the fatal breakpoint after Remix's failed vkCreateDeferredOperationKHR
check (dxvk_raytracing.cpp:326) into a no-op, so the runtime carries on with a
Vulkan driver whose deferred host operations fail (Mesa lavapipe). Works on the
Remix Plus 1.5.1 x86 games release's .trex/d3d9.dll; it checks the bytes.

    patch_remix_runtime.py <.trex/d3d9.dll> <out.dll>
"""
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
optsize = struct.unpack_from("<H", data, pe + 20)[0]
sec = pe + 24 + optsize
rva = 0x3f65db
for i in range(nsec):
    vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
    if va <= rva < va + max(vsize, rawsize):
        off = rva - va + raw
        # the int3 sits right after the call that builds "[Vulkan call failed] ..." message
        if data[off] != 0xCC or data[off - 5] != 0xE8:
            sys.exit("unexpected bytes at the patch site; is this Remix Plus 1.5.1's .trex/d3d9.dll?")
        data[off] = 0x90
        open(dst, "wb").write(data)
        print("patched", dst)
        break
else:
    sys.exit("section not found")
