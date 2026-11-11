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
# CPU governor: linux/docker/cpu_governor.sh (cron, every minute) lets game containers use all 8 CPUs
# while nobody is connected to the play page and pins them back to 0-4 within a minute of a connection.
# Videos: linux/docker/videos_server.sh serves deliverables/web (faststart mp4 + index) on port 8081.
# QA scenarios: [STAGE=<dir>] gamerun/qa_run.sh <name> <seconds> [wall|backforth|fight|crash|respawn4|long]
# City sweep:   [STAGE=<dir>] gamerun/sweep_queue.sh wil:0/5 ... ; tools/sweep_detect.py
# Visual regression (run before committing anything the 3D views draw; docs/visual-regression.md):
#   GTA2_GPU=<n> tools/vreg/vreg.sh stage <your private stage>   |   tools/vreg/vreg.sh check <rev>
```

Results of a run: `out/<run>/gta2dx9.log` (look for `FAULT`, `view:`,
`frame times`), `shot_*.png`, `game.mp4`.

## Rules from round 2 (multi-agent host; details in docs/HANDOVER.md section 0)

- Never `git stash push`/`pop` in any worktree of `repo/`: `refs/stash` is shared by every worktree, so a pop
  takes another agent's hunks (16:16 UTC 10 Nov: FIX-CAMERA-16 and FIX-PERF-5 swapped stashes). Park work
  as a patch (`git diff > /tmp/x.patch; git checkout -- <files>`) or a WIP commit on your worktree branch.
- Never put a shell variable in an `rm` command typed into the agent shell (`rm -rf "$X"`):
  the harness safety check hangs the call forever. Use literal absolute paths or Python.
- Never run `rm` under `sudo`, and never remove anything under `/dev` (07:21 UTC 11 Nov: a `sudo rm -rf /dev/null`
  from a QA seat's shell broke every `>/dev/null` redirect on the host for a minute, ended that pass and knocked
  all restage chains out of their wait loops). The account's sudo covers everything; use it only for `docker`.
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
- Scripted runners that steer or aim from the `view: player` line: pass `-e GTA2DX9_STATE_EVERY=3`
  (the default 15 frames leaves facing and position half a second stale; docs/actions-3d.md).

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

## Host capacity (hard rules, after the 8 Nov overload that nearly took the host down)

The host has 8 CPUs and one L4. Load 60+ came from 20 agents each running a game, a build and analysis at once.
(The 9 Nov program host has 96 CPUs and eight L4s: the governor, slots and load limits scale with `nproc`,
see docs/throughput.md "Governor"; the per-agent rules below still apply, read "8 CPUs" as "the host's CPUs".)
- Game runs: only through `gamerun/slot.sh` (4 slots at 1.5 CPUs; runq refuses to start a run while the 1-minute
  load is above 1.5 x nproc (12 on 8 CPUs, 144 on the 96-CPU program host, where a load of 30-40 is normal: never skip a
  run for it), while MemAvailable is under 6 GB, or while `/tmp/gta2-load-hold` exists; each game session
  takes ~2.2 GB RAM, a Remix run ~2 GB, SDXL ~8 GB, TRELLIS ~6 GB on a 31 GB host). One run at a time per agent. Short runs (set the run
  length to what the check needs, never a default 10 minutes).
- Builds: `flock /tmp/gta2-build.lock nice -n 10 make -j4` (never -j8 while other agents work).
- GPU generation (SDXL, TRELLIS, Remix mod builds): one process at a time, `flock /tmp/gta2-gen.lock`, `taskset -c 0-4`, `nice -n 10`.
- Heavy host-side work (ffmpeg, PIL batches, pandas): `nice -n 15`, never in parallel with your own game run.
- The coordinator keeps at most 8 agents concurrent: at most 4 that need game runs, 2 that use the GPU, the rest offline.
- The shared `repo/stage` is built ONLY by `linux/docker/restage.sh`, which builds a detached worktree of committed HEAD
  (never the working tree, which holds other agents' partial edits: an unfinished lighting pass reached the play page once).
  Test your own build from a private stage copy. Commit before you want it on the play page.
- Play-page gate (after the untextured-figures incident, 8 Nov): `restage.sh` builds a complete candidate stage
  (DLLs from committed HEAD, models from assets/models, HD tiles from assets/textures_hd), runs
  `stage_check.py` (inventory against the manifest) and `stage_smoke.sh` (a scripted 3D run: no model/texture
  read errors, no faults, late frames in colour) and swaps only if both pass; `play.sh` refuses an unhealthy stage.
  Never copy anything into repo/stage by hand.
- `cpu_governor.sh` (cron) pauses the newest scripted containers when the load passes 20 and resumes them under 10;
  a paused run is not a failure, wait for it.
- Never start a second play container (Remix play on 8082 costs 4 CPUs) unless the owner asks.

## GitHub issues (progress and plan)

Issues on ronigoldnexar/gta2-rtx-remix-upgraded: tracking issue #1 (pinned: status table, mission
state, open items), stream issues cars #2, Remix #3, navigation/camera #4, actions/peds/police #5,
performance #6, missions #7, props/assets #8, QA/release #9, agent rules #10.

- At each commit, comment on your stream's issue: commit hash, what changed, what was verified vs
  untested, the doc section (`gh issue comment <n> --repo ronigoldnexar/gta2-rtx-remix-upgraded`).
- When a stream finishes, update its row and the open-items checklist in #1 and set the stream
  issue's `status:` label.
- Issues are public: no credentials, IPs, raw logs or game art; cite docs, not files under `out/`.
