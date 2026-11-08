#!/usr/bin/env bash
# Rebuilds the gta2hd Remix material layer from the current 512 px DDS tile sets
# of all three districts, keyed by what the runtime hashes for them (the top
# mip's block bytes, verified in game: docs/remix-materials.md), then the
# emissive masks of the neon/lit-sign tiles, then the car materials (clear-coat
# paint, metal trim, lit tail lamps) for the 3D car models. In that order: the
# tile and emissive passes rewrite the whole mod.usda, the car pass only its own
# prims. ~4 min on one CPU core. ZIP=1 also packs the release archive
# deliverables/remix_mod_gta2hd.zip (mod.usda + textures/; it holds the game's
# art, so it is shipped as a release asset, never committed).
set -e
cd "$(dirname "$0")/.."
MOD=${MOD:-repo/package/rtx-remix/mods/gta2hd}; SIZE=${SIZE:-256}
MODELS=${MODELS:-repo/assets/models}; UPSCALED=${UPSCALED:-upscale/hd}
EXCL=$(find upstream-release/files/rtx-remix/mods -maxdepth 2 -name "*.usd*" | tr '\n' ' ')
rm -rf "$MOD/textures"; mkdir -p "$MOD"
nice python3 repo/tools/remix_materials.py - "$MOD" --dds-tiles repo/assets/textures_hd/wil repo/assets/textures_hd/bil repo/assets/textures_hd/ste --size "$SIZE" --exclude $EXCL
[ -d "$UPSCALED" ] && nice python3 repo/tools/remix_emissive.py game/data "$MOD" repo/assets/textures_hd "$UPSCALED" | head -3
nice python3 repo/tools/remix_model_materials.py "$MODELS" "$MOD"
du -sh "$MOD"; ls "$MOD/textures" | wc -l
# (an absolute path for the archive: with "$OLDPWD/deliverables" the 8 Nov rebuild wrote
# no deliverables/remix_mod_gta2hd.zip)
if [ "${ZIP:-0}" = 1 ]; then ROOT=$PWD; mkdir -p deliverables; rm -f deliverables/remix_mod_gta2hd.zip; (cd "$(dirname "$MOD")" && zip -qr -0 "$ROOT/deliverables/remix_mod_gta2hd.zip" "$(basename "$MOD")/mod.usda" "$(basename "$MOD")/textures"); ls -la deliverables/remix_mod_gta2hd.zip; fi
