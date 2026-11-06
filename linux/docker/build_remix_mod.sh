#!/usr/bin/env bash
# Rebuilds the gta2hd Remix material layer from the current 512 px DDS tile sets
# of all three districts, keyed by what the runtime hashes for them (the top
# mip's block bytes, verified in game: docs/remix-materials.md), plus glossy
# car-paint materials for the 3D car models. ~2.5 min on one CPU core.
set -e
cd "$(dirname "$0")/.."
MOD=${MOD:-repo/package/rtx-remix/mods/gta2hd}; SIZE=${SIZE:-256}
EXCL=$(find upstream-release/files/rtx-remix/mods -maxdepth 2 -name "*.usd*" | tr '\n' ' ')
rm -rf "$MOD"; mkdir -p "$MOD"
nice python3 repo/tools/remix_materials.py - "$MOD" --dds-tiles repo/assets/textures_hd/wil repo/assets/textures_hd/bil repo/assets/textures_hd/ste --size "$SIZE" --exclude $EXCL
nice python3 repo/tools/remix_model_materials.py repo/assets/models "$MOD"
du -sh "$MOD"; ls "$MOD/textures" | wc -l
