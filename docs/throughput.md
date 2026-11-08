# Throughput: more verification runs per hour on one small host

Every verification is a game run (Wine in Docker on the L4). This page records
what one host can run at once, how a run's start was shortened, and the queue
that keeps the slots full. Measured 7 Nov 2026 on the 8-CPU / one-L4 host while
three other streams and the player's container (`gta2-play-8090`) were active;
the host load column says how busy it was.

## Knobs (all in `gamerun/`, mirrored in `linux/docker/`)

| knob | what it does | default |
|---|---|---|
| `grun.sh <name> <secs> <keys> [docker -e …]` | the fast scripted run: queued, prebaked prefix, bind-mounted data, intro skipped, GPU render; output in `out/<name>` | `CPUS=2`, `FPS=15`, `GTA2_INTRO=0`, `IMAGE=gta2-gpugl-fast` |
| `runq.sh run [-p PRIO] [-n NAME] -- <cmd>` | FIFO with priorities over the slots (lower runs first); `runq.sh status`, `runq.sh wait` | `GTA2_SLOTS=4` |
| `slot.sh <cmd>` | kept for old callers; now `runq.sh run -p 5` | |
| `game_mounts.sh` | prints `-v` flags binding `game/data`, `gta2dx9_hd`, `gta2dx9_voice`, `gta2dx9_models`, `gta2dx9_textures_hd` read-only into the prefix path; the run scripts skip the copy of any mounted folder (`mountpoint -q`); not used with `SWAP_LEVEL` | used by `grun.sh`, `qa_run.sh`, `tour_run.sh`, `sweep_run.sh`, `remix_l4.sh` (`GTA2_FAST=0` turns it off) |
| `Dockerfile.fast` | a layer with a ready 32-bit prefix at `/opt/wp`; the run scripts copy it instead of `wineboot` | image `gta2-gpugl-fast` |
| `GTA2_INTRO=0` | the run scripts set `intro=0` in the ini (the mod's own intro skip) | `grun.sh` only; the other runners keep the intro unless asked, because their fixed-sleep keys scripts were timed with it |
| `to_level.sh` | inside a run: waits for the window, then taps Return every 1.5 s until the renderer logs `view: classic (player found`; replaces `sleep 10 … sleep 15 … 5 × Return` in keys scripts (`keys_views2_fast.sh` is the example) | |
| `tools/run_stats.py out/<run>…` | time to the level, frame-stage averages after it, worst wait, hitch frames, faults | |
| `play.sh` | `PLAY_CPUSET=5-7` pins the player's container to its own CPUs so scripted runs never starve it (opt-in; takes effect at the next `play.sh` start) | unpinned |

## Startup: before and after

Measured on the same 150 s `keys_views2` scenario, one copy, GPU render (`out/tp_old_n1` vs `out/tp_n1_a`):

| stage | old path | fast path |
|---|---|---|
| prefix | `wineboot -i`, 5.0 s | copy of the image's `/opt/wp`, 0.5 s |
| game + release + build copies into the prefix | 0.8 + 4.3 + 2.0 s (≈2 GB written per run) | 0.8 + 0.3 + 0.1 s (data, HD cars, voices, models, HD tiles are bind mounts) |
| intro movie | plays (≈25 s) | `intro=0` |
| front end | fixed sleeps 10 + 15 s, five Returns 6 s apart | `to_level.sh`: Return every 1.5 s until the renderer logs the level |
| **DLL attach → player in the level** | **38.2 s** | **9.7 s** (one copy), 12-17 s with four copies |
| keys script start → level | ≈61 s | 14.9 s (one copy), 20-21 s with three or four copies |
| wall time of a 150 s recording | 180 s | 178 s (the recording length dominates; use shorter `SECS` now that the level comes early) |

Target "level in ≤ 30 s" met. The intro skip is the mod's own `intro=0` (`dll/src/intro_movie.cpp`), no code change. The remix image has no `-fast` layer: `wineboot` in the patched Wine 10 image fails without a display during `docker build`, so Remix runs still pay the 5 s.

## Concurrency: N copies of the same 150 s scenario at `--cpus=2`

Four copies at once, `--cpus=2` each, no cpuset, while the player's container and other streams were running (host load at batch start in the first column). Numbers from `tools/run_stats.py`: averages over the frame summaries after the level (ms), the cap is 30 fps = 33 ms, `wait` is the idle time left per frame.

| copies (host load) | game step | world | sprites | present | wait (idle) | worst-wait floor | hitch frames | faults | views captured |
|---|---|---|---|---|---|---|---|---|---|
| 1 (10.1) | 8.5 | 1.9 | 3.8 | 0.9 | 21.3 | 29.2 | 382 | 0 | 9/9 |
| 2 (16.6) | 8.7, 9.2 | 1.7, 1.6 | 4.2, 4.2 | 0.7, 0.5 | 22.1, 21.6 | 28.1, 29.5 | 262, 281 | 0 | 9/9 both |
| 3 (9.1) | 10.1, 9.7, 9.6 | 1.6-1.7 | 5.0-5.6 | 0.2-0.5 | 21.4-22.1 | 24.7-28.2 | 320-331 | 0 | 9/9 all |
| 4 (13.3) | 10.5-11.6 | 2.0 | 5.3-5.9 | 0.7-1.2 | 20.4-21.3 | 28.5-31.4 | 354-367 | 0 | 9/9 all |

Every copy at every N held the 30 fps cap with ≥ 20 ms of idle per frame; the game step rose from 8.5 to 11.6 ms and the level took 12-17 s instead of 10 s at N = 4. Wall time per copy stayed 170-181 s. So `GTA2_SLOTS=4` at `CPUS=2` is the default (a fifth copy was not tried: 4 × 2 = 8 CPUs is the host). When the player is online, pin the play container (`PLAY_CPUSET=5-7` at its next start) so the scripted runs cannot take its cores; the measurements above were taken with the player's container unpinned and running.

## Remix

`gamerun/remix_cache/gta2.dxvk-cache` is reused (the runtime logs "Read 81 valid state cache entries"), but that is DXVK's state cache (22 KB); the 3-minute "Compiling shaders" at every Remix start is the NVIDIA driver's own shader/pipeline cache being rebuilt, which lives in the container's `/root/.nv` and `/root/.cache/nvidia` and was lost with the container. Mounting those two directories from the host (`gamerun/nv_cache/{nv,cache}`) keeps them: after one Remix run the directory holds the driver's `GLCache` and `ComputeCache` (25 files, 35 MB). Second run with the cache mounted: wall time 541 → 508 s for the same 420 s recording (33 s less), DLL attach → level 228 → 182 s (46 s less); the `keys_remix_short` script still waits its fixed `LEVEL_WAIT=60`, so the remaining time to the level is the script, not the compile (a `to_level.sh`-style wait would take it too).

`remix_l4.sh` does not add these mounts by itself yet; pass `-v "$PWD/gamerun/nv_cache/nv:/root/.nv" -v "$PWD/gamerun/nv_cache/cache:/root/.cache"` as its extra docker flags (the files are root-owned: read them with sudo).

## Fidelity check

Old path vs fast path, one copy each, same scenario: identical asset loads (186 models, 231 mapped object sprites, 818 HD tiles), all nine view screenshots in both, same frame-stage profile (game 7.0 vs 8.5 ms, wait 23.6 vs 21.3 ms), 0 faults in both. The fast run logged more sprite-stage hitch lines (the renderer's 300-line budget was reached; the old run logged 58 after the level). Two diagnostics isolate it: the fast path with the intro left on (`out/tp_diag_intro`) and the fast path without the bind mounts (`out/tp_diag_nomount`) both show the same 300 lines, so neither the intro skip nor the mounts causes them; they track the host's load from the other streams' containers (every fast run above ran beside two to four other game containers, the old-path run ran last with the host quieter). A quiet-host A/B is the one check not done.

## Fast sessions: the game itself at 2x or 3x (`GTA2_SPEED`)

GTA2 steps its simulation once per rendered frame and scales nothing by elapsed
time (the game's own pacer returns a hardcoded 33 ms; the registry's
`max_frame_rate`/`min_frame_rate` are read as booleans), so the renderer's frame
cap is the game's speed. A scripted mission session that needs no real-time video
can therefore run the game faster:

    GTA2_SPEED=2 FPS=0 PRIO=4 gamerun/grun.sh myrun 900 keys_mission_wil.sh -e MISSIONS="wil_tra wil_ye1"

- `GTA2_SPEED=N` sets `fps_cap=30*N` in the ini **and** `FpsCap` in the saved
  settings file (`gta2dx9_settings.ini` overrides the ini at startup; the run
  scripts now honour `SETTINGS_SED` for this), and exports `GTA2_SPEED` into the
  container.
- `drive_lib.py` reads `GTA2_SPEED` and divides every `time.sleep` (and so every
  key hold and poll) by it for all modules that import it: the runners' timings
  are written in game seconds and stay valid. `mission_lib.speed_of` reports
  blocks per game second, and every `MARK` line carries `game=<s>` from the
  renderer's frame counter (`frame / 30`).
- `FPS=0` records no video (screenshots every `SHOTS_EVERY` s, default 5);
  `RES=low` renders at 960x540. Both cut the capture's CPU share.
- A keys script that has finished touches `/out/.keys_done` (`keys_mission_wil.sh`,
  `keys_mission_districts.sh` do); `run_game_gpu.sh` then ends the run at its next
  screenshot (the recorder stopped, the log copied) instead of holding the slot to `SECS`.

Measured (TUTORIAL + GET ZITZAKI, `keys_mission_wil.sh`, same build, same host load):

| run | cap | `--cpus` | concurrent containers (host load) | achieved | game step / present / idle ms | TUTORIAL | GET ZITZAKI |
|---|---|---|---|---|---|---|---|
| `out/speed1x_wil` | 30 | 2 | 4 (load 20-30) | 25.7 fps = **0.86x** | 9.4 / 1.1 / 13.9 | phone not answered (runner state, see below) | complete, 1026 s wall |
| `out/speed2x_wil` | 60 | 2 | 4 | 32.7 fps = **1.09x** | 12.3 / 3.3 / 0.6 | phone not answered | JOB FAILED after a warp to the mission car (734 s) |
| `out/speed3x_wil` | 90 | 2 | 4 | 33.5 fps = **1.12x** | 10.6 / 4.1 / 0.0 | phone not answered | stuck: could not enter the car after the warp (738 s) |
| `out/speed2x_c4` (views scenario, 300 s) | 60 | 4 | 4 (load 30) | 50.1 fps = **1.67x** | 15.3 / 5.3 / 1.5 | - | - |

Reading it: the cap is honoured (the limiter logs 60/90 fps), but at `--cpus=2` with four
containers on the 8-CPU host a frame costs ~30 ms of CPU (the game's own single-threaded step
10-12 ms, our sprites 5-6, present 3-4, the rest), so the game cannot go faster than ~33 fps
whatever the cap: "2x" delivered 1.09x, and the 1x baseline itself ran at 0.86x. With four CPUs
the same session reached 1.67x on a host at load 30. The speed-up is therefore bounded by CPU
headroom, not by the game: use `GTA2_SPEED=2` with `CPUS=4` and at most two concurrent sessions
(the game step is 5 ms on a quiet host, where 60 fps is reachable); `GTA2_SPEED=3` is out of
reach on this host. Game physics at the effective 1.1-1.7x showed no faults; whether driving
stays controllable at a true 2x was not reached in a mission run (the GET ZITZAKI failures at
"2x" and "3x" happened at 1.1x and are the runner's own: in all three runs the tutorial phone
was not answered by the runner's current code, which another stream was editing at the time, so
the 1x result is the only clean completion). `frames_rendered()` in `mission_lib.py` (the
renderer's 256-frame summaries) is the game clock the marks use; the mission line's `frame=`
field is not a counter.
