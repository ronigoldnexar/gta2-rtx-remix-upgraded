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
# (relief tiles). ~15 min with JOBS=3 on an idle host; AGENTS.md "Host capacity": run it as
# flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10 bash build_remix_mod.sh. ZIP=1 also packs the release archive
# deliverables/remix_mod_gta2hd.zip (mod.usda, mod_wet.usda, pbr.json, textures/;
# it holds the game's art, so it is shipped as a release asset, never committed).
# MOD=<dir> builds elsewhere (e.g. a private copy to try under Remix with MODS_HD_SRC).
# FIX-REMIX-MATERIALS-6: the tools, models, tiles and the default MOD are those of the checkout
# that holds THIS script (REPO, e.g. a private worktree /tmp/wt-<you>), never the shared
# repo/ checkout: layer files built from a worktree landed uncommitted in repo/package three
# times on 10 Nov and blocked two restages. The workspace (game/data, upstream-release, upscale,
# deliverables) is WS. A copy of this script outside a git checkout (gamerun/build_remix_mod.sh)
# refuses to run without an explicit MOD. Test the result under Remix with PACKAGE=<REPO>/package
# on gamerun/playtest_remix.sh / remix_l4.sh (they mount ${PACKAGE:-repo/package} as /package).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)}
WS=${WS:-/mnt/gta2/gta2-linux}; [ -d "$WS/game/data" ] || WS=$(cd "$HERE/.." && pwd)
if [ -z "$REPO" ]; then [ -n "${MOD:-}" ] || { echo "build_remix_mod.sh: not inside a git checkout; set MOD=<your worktree>/package/rtx-remix/mods/gta2hd (and REPO=<your worktree>)" >&2; exit 2; }; REPO=$WS/repo; fi
cd "$WS"
MOD=${MOD:-$REPO/package/rtx-remix/mods/gta2hd}; SIZE=${SIZE:-512}; MAPSIZE=${MAPSIZE:-256}; JOBS=${JOBS:-3}
# inputs are read-only and partly untracked (HD tiles, 0NN_* car models are never in git), so they default to the shared checkout
MODELS=${MODELS:-$WS/repo/assets/models}; TILES=${TILES:-$WS/repo/assets/textures_hd}; UPSCALED=${UPSCALED:-upscale/hd}
case "$(cd "$(dirname "$MOD")" 2>/dev/null && pwd)" in "$WS"/repo/*) [ "$REPO" = "$WS/repo" ] && [ "${SHARED_OK:-0}" = 1 ] || { echo "build_remix_mod.sh: MOD is inside the shared checkout $WS/repo; build into your worktree (SHARED_OK=1 with REPO=$WS/repo overrides)" >&2; exit 2; };; esac
echo "build_remix_mod.sh: tools $REPO/tools -> MOD=$MOD (models $MODELS, tiles $TILES)"
EXCL=$(find upstream-release/files/rtx-remix/mods -maxdepth 2 -name "*.usd*" | tr '\n' ' ')
rm -rf "$MOD/textures" "$MOD/pbr.json"; mkdir -p "$MOD"
nice python3 "$REPO"/tools/remix_materials.py - "$MOD" --dds-tiles "$TILES"/wil "$TILES"/bil "$TILES"/ste --size "$SIZE" --map-size "$MAPSIZE" --jobs "$JOBS" --gmp-dir game/data --exclude $EXCL
[ -d "$UPSCALED" ] && nice python3 "$REPO"/tools/remix_emissive.py game/data "$MOD" "$TILES" "$UPSCALED" | head -3
nice python3 "$REPO"/tools/remix_model_materials.py "$MODELS" "$MOD"
python3 "$REPO"/tools/remix_materials.py - "$MOD" --wet-layer
# QB-25: facade depth (recessed windows/doors, sills) for the wall tiles, from the committed grounding
# boxes (tools/facade_boxes.json, docs/facade-depth.md); patches those prims in mod.usda and mod_wet.usda
[ "${FACADE:-1}" = 1 ] && nice python3 "$REPO"/tools/facade_depth.py build game/data "$TILES" "$MOD" "$REPO"/tools/facade_boxes.json | tail -5
du -sh "$MOD"; ls "$MOD/textures" | wc -l
# (an absolute path for the archive: with "$OLDPWD/deliverables" the 8 Nov rebuild wrote
# no deliverables/remix_mod_gta2hd.zip)
if [ "${ZIP:-0}" = 1 ]; then ROOT=$PWD; mkdir -p deliverables; rm -f deliverables/remix_mod_gta2hd.zip; (cd "$(dirname "$MOD")" && zip -qr -0 "$ROOT/deliverables/remix_mod_gta2hd.zip" "$(basename "$MOD")/mod.usda" "$(basename "$MOD")/mod_wet.usda" "$(basename "$MOD")/pbr.json" "$(basename "$MOD")/textures"); ls -la deliverables/remix_mod_gta2hd.zip; fi
