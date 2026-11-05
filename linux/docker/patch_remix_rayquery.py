#!/usr/bin/env python3
"""Makes VK_KHR_ray_query an optional rather than required device extension in
the Remix runtime, so the server creates its device on a GPU whose driver
exposes VK_KHR_ray_tracing_pipeline but not VK_KHR_ray_query (NVIDIA B200,
driver 580). Whether the driver then compiles Remix's ray query shaders is a
separate question; see docs/remix-gpu.md. Works on Remix Plus 1.5.1's
.trex/d3d9.dll (the DxvkDeviceExtensions constructor stores the mode of
khrRayQueries as `mov qword [rcx+0x1a8], 2`); it checks the bytes.

    patch_remix_rayquery.py <.trex/d3d9.dll> <out.dll>
"""
import sys
src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
off = 0x173ca7
want = bytes.fromhex("48c781a801000002000000")
if data[off:off + len(want)] != want:
    sys.exit("unexpected bytes at the patch site; is this Remix Plus 1.5.1's .trex/d3d9.dll?")
data[off + 7] = 1   # DxvkExtMode::Optional
open(dst, "wb").write(data)
print("patched", dst, ": VK_KHR_ray_query is now optional")
