#!/usr/bin/env bash
# PLAYTEST-REMIX launcher: remix_l4.sh's run, but holding only this GPU's lock (/tmp/gta2-gpu<N>-remix.lock),
# so it does not queue behind a Remix session on another GPU. usage: playtest_remix.sh <name> <secs> <district wil|ste|bil> <hours> <points> [docker -e ...]
cd /mnt/gta2/gta2-linux; NAME=$1; SECS=$2; DIST=$3; HRS=$4; PTS=$5; shift 5
# REMIX_NVCACHE=1: keep the NVIDIA driver's shader cache (/root/.nv, /root/.cache) between runs (gamerun/nv_cache): a warm cache makes the "Compiling shaders" wait seconds, not minutes (docs/throughput.md "Remix")
NVC=; [ "${REMIX_NVCACHE:-0}" = 1 ] && { mkdir -p "$PWD/gamerun/nv_cache/nv" "$PWD/gamerun/nv_cache/cache"; NVC="-v $PWD/gamerun/nv_cache/nv:/root/.nv -v $PWD/gamerun/nv_cache/cache:/root/.cache"; }
G=${GTA2_GPU:-1}; rm -rf "out/$NAME"; mkdir -p "out/$NAME"
SW=(); [ "$DIST" != wil ] && { export SWAP_LEVEL=$DIST; SW=(-e SWAP_LEVEL=$DIST); }
flock /tmp/gta2-gpu$G-remix.lock gamerun/slot.sh sudo -n docker run --rm --cpuset-cpus=${CPUSET:-$((G*10))-$((G*10+9))} --gpus "\"device=$G\"" $(gamerun/nv_devices.sh $G) -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=${CPUS:-8} $NVC \
  "${SW[@]}" -e MODS_HD=1 -e RTX_EXTRA=/work/rtx_play.conf.extra -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e DISTRICT=$DIST -e "HOURS=$HRS" -e "POINTS=$PTS" \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=${HRS%%,*}/" "$@" \
  $(ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} gamerun/game_mounts.sh) -e GTA2_INTRO=0 -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" \
  -v "$PWD/remix-runtime/x86:/remix:ro" -v "${PACKAGE:-$PWD/repo/package}:/package:ro" -v "$PWD/out/$NAME:/out" -w /work \
  ${REMIX_IMAGE:-gta2-remix-gpu2} bash /work/run_game_remix_gpu.sh "$SECS" /work/${RKEYS:-keys_remix_playtest.sh} > "out/$NAME.run.log" 2>&1
grep -v "ALSA\|fixme\|Parent window\|GTA2\|^t=" "out/$NAME.run.log" | tail -8
