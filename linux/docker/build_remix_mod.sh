#!/usr/bin/env bash
# Rebuilds the gta2hd Remix material layer for all three districts from the
# current 512 px DDS tile sets (albedo) keyed by the 64 px tiles dumped straight
# from the style files (the hashes Remix sees when the game uploads its own tiles).
set -e
cd "$(dirname "$0")/.."
IN=/tmp/modin; MOD=repo/package/rtx-remix/mods/gta2hd_new; SIZE=${SIZE:-256}
rm -rf "$IN" "$MOD"; mkdir -p "$IN" "$MOD"
EXCL=$(find upstream-release/files/rtx-remix/mods -maxdepth 2 -name "*.usd*" | tr '\n' ' ')
for d in wil bil ste; do
  mkdir -p "$IN/$d/dump" "$IN/$d/hd"
  python3 repo/tools/dump_style_tiles.py game/data "$d" "$IN/$d/dump" --all > "$IN/$d.dump.log" 2>&1
  python3 - "$d" "$IN/$d/hd" <<'PY'
import sys, os, numpy as np
from PIL import Image
d, out = sys.argv[1:3]
src = f"repo/assets/textures_hd/{d}"
n = 0
for f in sorted(os.listdir(src)):
    if not f.endswith(".dds"): continue
    im = Image.open(os.path.join(src, f)).convert("RGBA")
    px = np.asarray(im)[..., [2, 1, 0, 3]]   # B G R A, top-down
    h, w = px.shape[:2]
    hdr = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, w & 255, w >> 8, h & 255, h >> 8, 32, 0x28])
    open(os.path.join(out, f[:-4] + ".tga"), "wb").write(hdr + px.tobytes()); n += 1
print(d, n, "tiles converted")
PY
  nice python3 repo/tools/remix_materials.py "$IN/$d/dump" "$MOD" --hd "$IN/$d/hd" --size "$SIZE" --exclude $EXCL 2>&1 | tail -2
done
du -sh "$MOD"; ls "$MOD/textures" | wc -l
