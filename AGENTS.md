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
# while game runs may be active: linux/docker/restage.sh (waits for the build lock
# and all four game slots; a make stage mid-run leaves that run with white figures)
make check                                 package.bat

# Run in a container (layout in docs/HANDOVER.md section 6)
docker build -t gta2-remixbox -f linux/docker/Dockerfile.wine9 linux/docker
docker run --rm --cpus=8 -v $PWD/../gamerun:/work -v $PWD/../game:/game:ro \
  -v $PWD/../upstream-release/files:/release:ro -v $PWD/stage:/stage:ro \
  -v $PWD/../remix-runtime/x86:/remix:ro -v $PWD/../out/run1:/out -w /work \
  gta2-remixbox bash /work/run_game.sh win32 240 0 /work/keys_demo_fp2.sh
# GPU: image gta2-gpugl (Dockerfile.gpu-gl), --gpus, run_game_gpu.sh
# QA scenarios: [STAGE=<dir>] gamerun/qa_run.sh <name> <seconds> [wall|backforth|fight|crash|respawn4|long]
# City sweep:   [STAGE=<dir>] gamerun/sweep_queue.sh wil:0/5 ... ; tools/sweep_detect.py
```

Results of a run: `out/<run>/gta2dx9.log` (look for `FAULT`, `view:`,
`frame times`), `shot_*.png`, `game.mp4`.

## Rules from round 2 (multi-agent host; details in docs/HANDOVER.md section 0)

- Never put a shell variable in an `rm` command typed into the agent shell (`rm -rf "$X"`):
  the harness safety check hangs the call forever. Use literal absolute paths or Python.
- Restage the shared `stage/` only with `linux/docker/restage.sh` (waits for the build lock
  and all four game slots). Test from a private copy: `cp -al repo/stage ~/gta2-linux/stage_<you>`,
  then `STAGE=<dir>` on `grun.sh` / `qa_run.sh` / `sweep_run.sh`.
- Game runs under `nohup` through `gamerun/grun.sh` / `slot.sh` / `runq.sh` (slots 1-4,
  containers on CPUs 0-4). Never stop the user's play container `gta2-play-<port>` (CPUs 5-7).
- `GTA2_DIRECT_KEYS=1` (nav_map=0 for the run) for any scripted play in third/first person;
  the shipped `nav_map=1` makes the arrows camera-relative and breaks scripted turns.
- Bash poll loops under 8 minutes.
- Release archives: `python3 tools/pack_release.py <out> [linux people cars textures remix]`;
  layouts in HANDOVER section 0. Cars and avatars never go into git; code-object models do.
- QA probes: `[devtools] force_wanted=N` (police 1-6 stars), `force_sirens=1`,
  `GTA2DX9_SCENE_NO_CAR=1` (warp to the point, not to a car), `GTA2DX9_LOG_VEHICLES=1`
  (vehicle list for finding an ambulance, a cop car, the train), `GTA2DX9_LOG_PED_FRAMES=1`
  (`npc shot` lines). `linux/docker/qa3_probe.py` frames the ambulance and police gunfire.

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
