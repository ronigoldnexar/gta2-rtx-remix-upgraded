#!/usr/bin/env bash
# Rebuilds the gta2hd Remix material layer from the current 512 px DDS tile sets
# of all three districts, keyed by what the runtime hashes for them (the top
# mip's block bytes, verified in game: docs/remix-materials.md), then the
# emissive masks of the neon/lit-sign tiles, then the car materials (clear-coat
# paint, metal trim, lit tail lamps) for the 3D car models, then the rain variant
# mod_wet.usda. In that order: the tile and emissive passes rewrite the whole
# mod.usda, the car pass only its own prims, the wet pass copies the result.
# Tiles get every map of tools/remix_pbr.py (VISUALS-REMIX): a 512 px BC5 normal
# (structure + grain), 256 px BC4 roughness, wet roughness (ground-like tiles),
# metallic (where there is metal) and height for Remix's parallax displacement
# (relief tiles). ~15 min with JOBS=3. ZIP=1 also packs the release archive
# deliverables/remix_mod_gta2hd.zip (mod.usda, mod_wet.usda, pbr.json, textures/;
# it holds the game's art, so it is shipped as a release asset, never committed).
# MOD=<dir> builds elsewhere (e.g. a private copy to try under Remix with MODS_HD_SRC).
set -e
cd "$(dirname "$0")/.."
MOD=${MOD:-repo/package/rtx-remix/mods/gta2hd}; SIZE=${SIZE:-512}; MAPSIZE=${MAPSIZE:-256}; JOBS=${JOBS:-3}
MODELS=${MODELS:-repo/assets/models}; UPSCALED=${UPSCALED:-upscale/hd}
EXCL=$(find upstream-release/files/rtx-remix/mods -maxdepth 2 -name "*.usd*" | tr '\n' ' ')
rm -rf "$MOD/textures" "$MOD/pbr.json"; mkdir -p "$MOD"
nice python3 repo/tools/remix_materials.py - "$MOD" --dds-tiles repo/assets/textures_hd/wil repo/assets/textures_hd/bil repo/assets/textures_hd/ste --size "$SIZE" --map-size "$MAPSIZE" --jobs "$JOBS" --exclude $EXCL
[ -d "$UPSCALED" ] && nice python3 repo/tools/remix_emissive.py game/data "$MOD" repo/assets/textures_hd "$UPSCALED" | head -3
nice python3 repo/tools/remix_model_materials.py "$MODELS" "$MOD"
python3 repo/tools/remix_materials.py - "$MOD" --wet-layer
du -sh "$MOD"; ls "$MOD/textures" | wc -l
# (an absolute path for the archive: with "$OLDPWD/deliverables" the 8 Nov rebuild wrote
# no deliverables/remix_mod_gta2hd.zip)
if [ "${ZIP:-0}" = 1 ]; then ROOT=$PWD; mkdir -p deliverables; rm -f deliverables/remix_mod_gta2hd.zip; (cd "$(dirname "$MOD")" && zip -qr -0 "$ROOT/deliverables/remix_mod_gta2hd.zip" "$(basename "$MOD")/mod.usda" "$(basename "$MOD")/mod_wet.usda" "$(basename "$MOD")/pbr.json" "$(basename "$MOD")/textures"); ls -la deliverables/remix_mod_gta2hd.zip; fi
