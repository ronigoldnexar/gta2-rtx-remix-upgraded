#!/usr/bin/env bash
# sweep_run.sh <district> <chunk i/n> [seconds]: one chunk of the city sweep on the GPU
# image, magenta clear, sky off, devtools keys on. Output: out/sweep_<district>_<i>/
cd "$(dirname "$0")/.."
Dd=$1; CH=$2; S=${3:-900}; I=${CH%/*}; N=sweep_${Dd}_${TAG:-}$I; rm -rf "out/$N"; mkdir -p "out/$N"
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F11/; /^\[sky\]/,/^\[/ s/^enabled=.*/enabled=0/'
# GTA2_DIRECT_KEYS=1 (default here): nav_map=0, so the quarter turns are the game's own Left key
[ "${GTA2_DIRECT_KEYS:-1}" = 1 ] && SED="$SED; s/^nav_map=.*/nav_map=0/"
# the sweep's own keys file: the sweep, then .keys_done so the run ends when the chunk is done (not at S).
# After a death in a swapped district (bil/ste) the game refuses or misplaces every later warp (the player
# locator follows another ped; docs/city-sweep.md): two points whose four warp attempts all went unseen end
# the chunk early; points from a death on go to a retry plan (SWEEP_PLAN=/work/sweep_plan_<d>_<tag>retry<k>.json).
cat > "out/$N/keys_sweep_chunk.sh" <<'KEYS'
python3 -u /work/sweep.py & P=$!
while kill -0 $P 2>/dev/null; do sleep 3
  if [ "$(grep -c 'warp attempt 4: no devtools line' /out/keys.log 2>/dev/null)" -ge 2 ]; then
    echo "sweep_run: warps refused (player lost after a death): ending the chunk"; kill $P; break; fi
  # sweep.py sometimes prints its final "done" and does not exit: end the chunk there too
  if tail -1 /out/keys.log 2>/dev/null | grep -q ' done$'; then sleep 2; kill $P 2>/dev/null; break; fi
done
touch /out/.keys_done
KEYS
# GPU: the game GPUs of the 8x L4 host (3-7, by chunk); GPU 0 is Remix's. GPU=<n> overrides.
GPU=${GPU:-$((3 + I % 5))}
gamerun/slot.sh sudo -n docker run --rm --gpus "\"device=$GPU\"" \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility -e FPS=15 --cpus=4 \
  -e INI_SED="$SED" -e GTA2_DIRECT_KEYS="${GTA2_DIRECT_KEYS:-1}" -e SWAP_LEVEL=$Dd -e GTA2DX9_CLEAR_MAGENTA=1 \
  -e SWEEP_DISTRICT=$Dd -e SWEEP_CHUNK=$CH -e SCENE_KEY=F11 -e GTA2DX9_SCENE_NO_CAR=1 -e SWEEP_PLAN=${SWEEP_PLAN:-/work/sweep_plan_$Dd.json} \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} SWAP_LEVEL=$Dd gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" \
  -v "${STAGE:-$PWD/repo/stage}:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/$N:/out" \
  -w /work ${IMAGE:-$(sudo -n docker image inspect gta2-gpugl-fast >/dev/null 2>&1 && echo gta2-gpugl-fast || echo gta2-gpugl)} bash /work/run_game_gpu.sh win32 "$S" 0 /out/keys_sweep_chunk.sh > "out/$N.run.log" 2>&1
echo "$N finished: $(grep -c FAULT out/$N/gta2dx9.log 2>/dev/null) faults, $(wc -l < out/$N/sweep.jsonl 2>/dev/null) points"
