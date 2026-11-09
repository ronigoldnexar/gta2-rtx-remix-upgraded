# Visual regression harness (QA-REGRESSION, 9 Nov 2026)

The same frames on every run, compared with golden frames using a tolerance learned from
repeat runs. The goal is to catch a real regression (untextured figures, a missing sky, a
greyscale picture, a model gone, a camera change, undrawn magenta) without flagging the
street's own life. Run it before you commit anything that changes what the 3D views draw.

## Use

```
# before committing: capture from YOUR private stage (your working-tree build) and diff
tools/vreg/vreg.sh stage ~/gta2-linux/stage_<you>
# a committed revision (built in a /tmp worktree into a private stage), or a commit of one branch
# cherry-picked onto the buildable tip of another
tools/vreg/vreg.sh check <rev>
tools/vreg/vreg.sh check 16fcaf8+aa7d383
# diff an existing capture again (e.g. after reseeding)
tools/vreg/vreg.sh diff out/<run>
# new goldens, after an intended visual change has been reviewed: 3 captures of <rev>
tools/vreg/vreg.sh seed <rev> 3
```

Set `GTA2_GPU` to your GPU. A capture takes one game slot for about 4-6 minutes and is queued
through `gamerun/runq.sh`. It runs on its own CPU set (`10*GPU .. 10*GPU+9`, or `VREG_CPUSET`),
because runq otherwise pins it to `GAME_CPUSET` (0-4). The result is in
`out/<run>/vreg_report/report.md`, with a sheet (golden | run | changed tiles in red) for every
WARN/FAIL shot. The exit status is 1 if any shot FAILs.

**Your stage must have the regression camera.** It is present in any build of this tree from
the commit that added `dll/src/regress_cam.cpp` on. `check` builds older revisions with it
injected (`tools/vreg/inject_hook.py`).

## What is captured (`tools/vreg/shots.json`, `linux/docker/vreg_capture.py`)

Downtown (wil), the lighting clock held at 12:30 with a clear sky (`SETTINGS_SED`
`Paused=1, StartHour=12.5, ClearSky=1`), 1280x720, no video:

- `spawn_classic`, `spawn_third`, `spawn_first`: at the spawn, with no input except Return and V.
  These are the views' own cameras, so the camera code is under test too. The classic shot
  guards "classic stays byte-for-byte the game's".
- 9 points (police HQ, city info, bank, the traffic lights at 120,152, Yakuza, the raised w03
  street, m37, restart1, Loonies). Each is reached by developer warp
  (`GTA2DX9_SCENE_NO_CAR=1`), and each has 3 fixed poses:
  - `chase`: 3 blocks south-east, 2.6 up, looking at the player;
  - `street`: eye height looking north up the street, so facades and sky;
  - `high`: 7 west and 7 up looking east and down.

  The fixed poses come from `GTA2DX9_REGRESS_CAM=<file>` (`dll/src/regress_cam.cpp`): while the
  file holds `cam ex ey ez tx ty tz fov` in game coordinates, the street views draw from exactly
  that eye. It does nothing without the environment variable. It only applies after a view
  transition has finished, and never in the classic view.

That gives 30 frames in total. `out/<run>/vreg.jsonl` records where the player landed for each
frame. A shot whose warp landed elsewhere than the golden's is reported SKIP (a game-state
difference, not a rendering one).

## The comparison (`tools/vreg/vreg_diff.py`)

- Frames are reduced to 320x180 with a box filter (sub-pixel jitter and shimmer average out) and
  cut into 16x9 tiles.
- Each tile gets two distances: `pix`, the mean absolute pixel difference (a changed model,
  texture or shadow), and `mean`, the largest per-channel difference of the tile's mean colour
  (a tint, a lighting or fog change).
- A golden set keeps **every sample** of a shot (3 runs of one build). A run's tile distance is
  its smallest distance to any sample, so a car or a person present in one sample is matched by
  another.
- **Noise per tile** comes from leave-one-out: each sample is compared with the others the same
  way, and the largest of those distances is the tile's noise. A tile is changed when its
  distance is above `max(floor, 1.25 x noise + margin)`. The floors are pix 0.045 and mean 0.035;
  the margins are 0.015 and 0.012.
- **Verdict per shot:**
  - FAIL: more than 12 % of tiles changed (18 of 144), or a global check trips: frame missing;
    black; magenta pixels where the golden had none; chroma under half the golden's (colour
    drained); or mean brightness outside the golden range by 0.08.
  - WARN: more than 5 % of tiles changed (8 tiles).
  - PASS: otherwise.
- `seed` runs the same leave-one-out as a self-check and prints how many samples would WARN or
  FAIL against the others. That figure is the false-alarm rate of the tolerance on that build.

Goldens and frames are game art. They stay outside git under `<workspace>/vreg/goldens/<rev>`
(`goldens/current` is the set in force), with `manifest.json` (revision, sample hashes, landing
points) and `noise.json` (per-tile noise).

## Calibration and results

See the section below, written from the runs of 9 Nov.
