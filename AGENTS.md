# For agents working on this repository

Read first: `docs/HANDOVER.md` (state, architecture, pipeline, conventions),
then `linux/README.md` (Linux/Docker/GPU/Remix), `docs/qa-report.md` and
`docs/performance.md` (open issues with evidence), `assets/README.md` (asset
licences and regeneration).

## What this is

`gta2dx9.dll`: an in-process Direct3D 9 renderer for GTA2 9.6 with three camera
modes (classic top-down, third person, first person), a Linux port, HD tiles, a
3D model per vehicle type, skinned pedestrians, map objects and a sky in the
ground views. Branch `camera-modes` of ronigoldnexar/gta2-rtx-remix-upgraded.

## Commands

```
# Linux build (mingw-w64)                 # Windows build
flock /tmp/gta2-build.lock make -j8 stage  dll\build.bat ; vid\build.bat
make check                                 package.bat

# Run in a container (layout in docs/HANDOVER.md section 6)
docker build -t gta2-remixbox -f linux/docker/Dockerfile.wine9 linux/docker
docker run --rm --cpus=8 -v $PWD/../gamerun:/work -v $PWD/../game:/game:ro \
  -v $PWD/../upstream-release/files:/release:ro -v $PWD/stage:/stage:ro \
  -v $PWD/../remix-runtime/x86:/remix:ro -v $PWD/../out/run1:/out -w /work \
  gta2-remixbox bash /work/run_game.sh win32 240 0 /work/keys_demo_fp2.sh
# GPU: image gta2-gpugl (Dockerfile.gpu-gl), --gpus, run_game_gpu.sh
# QA scenarios: gamerun/qa_run.sh <wall|backforth|fight|crash|death|long> <seconds>
```

Results of a run: `out/<run>/gta2dx9.log` (look for `FAULT`, `view:`,
`frame times`), `shot_*.png`, `game.mp4`.

## Conventions

- Own one subsystem; re-read before editing; never revert others' hunks.
- Build only under the lock; game runs through `gamerun/slot.sh` on small hosts;
  GPU generation under `/tmp/gta2-gpu.lock`.
- Verify in the running game (frames + log) and say what is verified vs untested.
- Keep the classic top-down view byte-for-byte as the game draws it.
- Ini keys are documented in `package/gta2dx9.ini`; add new ones there.

## Don'ts

- Never download GTA2 or any copyrighted asset; never commit generated assets
  that embed the game's art (`assets/models/0NN_*`, `assets/textures_hd/`,
  `package/rtx-remix/mods/gta2hd/textures/`): ship those as release archives.
- No third-party models/textures without an MIT/CC0-class licence noted in `assets/README.md`.
- Do not claim RTX Remix works without real path-traced frames (see HANDOVER section 2).
- Do not `make clean` or rebuild `stage/` while another agent's run uses it without the lock.

## Running the game: use the queue and the fast path

- Queue every game run: `gamerun/runq.sh run -n <name> -- <docker run …>` (or the
  `gamerun/grun.sh <name> <secs> <keys>` wrapper); never poll the slot files
  yourself. `gamerun/runq.sh status` shows busy slots and waiting tickets.
  `GTA2_SLOTS` (default 4) is the number of concurrent scripted runs the host
  holds at the 30 fps cap (measured in `docs/throughput.md`).
- Keys scripts: get into the level with `bash /work/to_level.sh` (log-driven,
  about 15 s) instead of fixed sleeps; `gamerun/keys_views2_fast.sh` shows it.
- A run's read-only data is bind-mounted, not copied (`gamerun/game_mounts.sh`);
  the prefix comes prebaked from the `*-fast` image. Details and numbers:
  `docs/throughput.md`.

- Mission and other long scripted sessions that need no real-time video: run the game faster with
  `GTA2_SPEED=2` (or 3) and `FPS=0` on `gamerun/grun.sh`; the runners' timing scales automatically
  (see docs/throughput.md "Fast sessions"). Recordings for people stay at `GTA2_SPEED=1`.
