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
- `spawn_portrait_front`: a fixed pose 0.75 blocks in front of the player where he starts (he
  faces north there), looking at his chest, for his textures, clothes and model. (A pose behind
  him lands inside the stair railing.)
  A person is about 0.45 blocks tall, so 1 block is about 4 m.
- 9 points (police HQ, city info, bank, the traffic lights at 120,152, Yakuza, the raised w03
  street, m37, restart1, Loonies). Each is reached by developer warp
  (`GTA2DX9_SCENE_NO_CAR=1`), and each has 3 fixed poses:
  - `chase`: 3 blocks south-east, 2.6 up, looking at the point;
  - `street`: 1.6 up (a first-floor window) looking north up the street, so facades and sky;
  - `high`: 7 west and 7 up looking east and down.

  These are scene views: after a warp the player himself is not drawn (see "Findings").

  The fixed poses come from `GTA2DX9_REGRESS_CAM=<file>` (`dll/src/regress_cam.cpp`): while the
  file holds `cam ex ey ez tx ty tz fov` in game coordinates, the street views draw from exactly
  that eye. It does nothing without the environment variable. It only applies after a view
  transition has finished, and never in the classic view.

That gives 31 frames in total. `out/<run>/vreg.jsonl` records where the player landed for each
frame. A shot whose warp landed elsewhere than the golden's is reported SKIP (a game-state
difference, not a rendering one).

## The comparison (`tools/vreg/vreg_diff.py`)

- Frames are reduced to 320x180 with a box filter (sub-pixel jitter and shimmer average out) and
  cut into 16x9 tiles.
- Each tile gets three distances:
  - `pix`, the mean absolute pixel difference (a changed model, texture or shadow);
  - `mean`, the largest per-channel difference of the tile's mean colour (a tint, a lighting or
    fog change);
  - `detail`, the relative change of the tile's fine detail (mean |Laplacian| at 640x360), for
    sharpness and grain.
- A golden set keeps **every sample** of a shot (3 runs of one build). A run's tile distance is
  its smallest distance to any sample, so a car or a person present in one sample is matched by
  another.
- **Noise per tile** comes from leave-one-out: each sample is compared with the others the same
  way, and the largest of those distances is the tile's noise. A tile is changed when its
  distance is above `max(floor, 1.25 x noise + margin)`. The floors are pix 0.045, mean 0.035 and
  detail 0.30; the margins are 0.015, 0.012 and 0.08.
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

### What it can and cannot see (measured on 9 Nov, below)

- Sees: models appearing, disappearing or changing size; texture swaps; lighting, fog and sky
  changes; colour drain; undrawn magenta; and HD tiles missing or replaced, when they are within
  a few blocks of the camera.
- A third tile measure, `detail` (the mean |Laplacian| of the 640x360 grey image, compared
  relatively), catches sharpness and grain changes that the reduction averages away. Its floor
  is a 30 % relative change.
- Weak: tile texture far from the camera (at 20+ blocks, HD and the game's own tiles are nearly
  the same at any resolution). Pedestrians and traffic are only seen where they happen to be in
  frame, and the street is quiet at 12:30, so a crowd regression may slip by. The spawn portraits
  look at the player himself. In `spawn_third` the views' own chase camera settles at a slightly
  different orbit each run, so that shot only catches large changes.
- Not covered: motion (animation, camera feel), Remix, other districts, night.

## Calibration and results (9 Nov 2026)

Goldens: `16fcaf8` (camera-modes after MERGE-RECONCILE, the last revision that builds; see below)
with its tracked models over the 8 Nov `repo/stage` art. Captures took 175-190 s of game time
each. Queue waits were 5-25 minutes, because the governor's 8-CPU thresholds pause runs on the
96-CPU host (issue #10).

| Run | Result | Reading |
|---|---|---|
| 2 clean runs, sky clock free | 0 false alarms of 60 leave-one-out, but the street shots had 31-92 noisy tiles (clouds follow the host's uptime) | led to `RegressClock` |
| clean runs a-c, clock held | leave-one-out 0 of 90; noisy tiles 0-3 per shot except `spawn_third` (59, the chase camera's settle) | tolerance mostly at the floors |
| held-out clean runs d, e (against a-c) | each PASS 29, WARN 1, FAIL 0 (`spawn_first`: the SAVES neon border in another phase; `spawn_third`: camera settle) | false alarms stay WARN; d-k then joined the goldens |
| **goldens in force: 11 clean runs a-k** (`goldens/16fcaf8_v4`) | leave-one-out **0 WARN/FAIL of 333** samples | |
| CONTROL: sky off (`[sky] enabled=0`) | FAIL 30 of 31 (the spawn portrait was not in that run); the classic view PASSes (it draws no sky) | gross change, caught everywhere it should be |
| CONTROL: no HD tiles | FAIL 15, WARN 7, PASS 9 | subtle change caught near the camera; far shots pass |
| `16fcaf8`+2d6b038+8ba42ea (QB-13 audio, QB-20 locomotion) | PASS all 30 scene shots | no visual regression |
| ...+aa7d383 (QB-36 booth)+1f5b243 (QB-9 density)+294fdc2 (CROWD)+36b4ce8 (ASSET-PEDS), 3 separate runs | each: FAIL 1, `spawn_first`, 22 tiles: the phone booth smaller and further away; the player's portrait PASSes | **QB-36's intended change**, found and localised; the bisect puts it at aa7d383 |
| ...+b648111 (ASSET-BUILDINGS, photo tiles), `repo/stage` art | the same booth FAIL only | the DLL change alone draws nothing new (no `photo/` folder in the stage) |
| same, workspace `assets/` art (`VREG_ART=assets`: what the next restage ships) | FAIL 4 (`m37_chase` roof tile softer and smudged, `lights23_chase`, `spawn_first`), WARN 3 (`policehq_chase`, `spawn_third`, `spawn_classic`: the plaza paving is smoother **in the classic view**) | the photo tiles change the look, including the classic view: for the ASSET-BUILDINGS owner and a reviewer to accept or not before the restage |

## Reseed of 9 Nov 2026 (QA-RESEED, goldens `48a9b58`)

The goldens of `16fcaf8` predated the day's accepted work. One capture of `48a9b58` against them:
PASS 22, WARN 4, FAIL 5 (not the 30 of 31 first reported; the classic and most scene shots held).
Every pair was looked at (sheets in `out/vreg_48a9b58_1109_142048/vreg_report/`, not in git):

| Shot | Difference | Verdict |
|---|---|---|
| `spawn_classic` | none (0 tiles) | the classic view is byte-for-byte as before |
| `spawn_third` (FAIL, 125) | the chase camera sits behind the player, who is now drawn full figure; the old golden had a far orbit | accepted: f4b5544 (boom as a rate-limited state), 48a9b58 |
| `spawn_first` (FAIL, 73) | smaller phone booth, an orange objective arrow with distance, a passing pedestrian beside the eye in 2 of 5 captures | accepted: aa7d383 (booth), af1dc60 (objective markers); the pedestrian is crowd (294fdc2, 36b4ce8), not a fixed element |
| `spawn_portrait_front` (FAIL, 48) | the player wears a dark shirt and jeans instead of the striped shirt and shorts; the mailbox is a post box | accepted: 36b4ce8, ceb9ff9 (ped outfits), fd2d678 (post box) |
| `lights23_chase` (FAIL, 37), `lights23_street` (WARN) | road paint re-authored (clean lane dashes, readable SLOW text, crosswalks), asphalt tone-matched across tiles | accepted: 89a990c, c69c620 |
| `cityinfo_chase`, `policehq_chase` (WARN) | objective arrow and distance label added; lamp posts moved to the kerb; paving tone | accepted: af1dc60, c2bdb0c, b648111 (street views only since 9edb1cf) |
| `m37_chase` (FAIL, 47), `m37_street` (WARN) | the roof and brick wall are softer, lower contrast, with paler mortar than the plain HD tile | **looks wrong**: defect `pm-photo-tiles-roof-and-brick-softer-than-plain-hd` filed in `defects/open/` (photo tiles of b648111/8861319) |
| all other shots | PASS, 0-7 tiles, with the objective arrow in frame | no change |

The goldens in force are now `goldens/48a9b58`: **5 clean captures** of that build (155 samples), leave-one-out
**0 WARN/FAIL of 155**. A fresh capture of the same build against them is PASS 31 of 31 (WARN 0, FAIL 0, no SKIP). The m37 shots are seeded
as they look today (the soft roof): when the defect is fixed, reseed those two shots on purpose.
`goldens/16fcaf8_v4` is kept beside it. Use `vreg.sh seed <rev> 5` for the next reseed.

Findings:

- **After a developer warp the player's own figure is not drawn in the 3D views.** The
  regression camera frames the point where he stands, and the city sweep's natural third-person
  frames after a warp show the same: other people are drawn, he is not. A small marker stays at
  his feet. This was not looked into further (live_geometry's owner); it limits every warp-based
  tool (sweep, regression), not normal play as far as is known.
- Not testable directly: the tip of `night-skills-2026-11-09` (from `14ae447` to `b648111`) does
not compile. `dll/src/beats.cpp` (in the WIP snapshot `14ae447`) calls `Hud3dGameText`, which
only exists on camera-modes (`4227371`, QB-17/18 hud3d hunks). Each commit was therefore tested
cherry-picked onto `16fcaf8` (`vreg.sh check 16fcaf8+<commit>...`). The only conflicts were in
`package/gta2dx9.ini` text; the stage takes its ini from `repo/stage`.
